import socket
import time
import unittest
from unittest.mock import patch

from backend.adapters.fetch import CrossHostRedirect, fetch_page, public_addresses, request, validate_url
from backend.domain.errors import ResearchError


class FetchTests(unittest.TestCase):
    def test_disallow_local_addresses_credentials_schemes_and_ports(self):
        for url in ['file:///etc/passwd', 'http://localhost', 'http://127.0.0.1', 'http://[::1]',
                    'http://169.254.169.254', 'http://10.0.0.1', 'http://224.0.0.1', 'http://user:pw@example.com',
                    'https://example.com:8000', 'http://example.local', 'http://example.com/\nheader']:
            with self.subTest(url=url), self.assertRaises(ResearchError): validate_url(url)

    def test_mixed_public_private_dns_is_rejected(self):
        with patch('socket.getaddrinfo', return_value=[(2,1,6,'',('93.184.216.34',443)),(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ResearchError) as error: public_addresses('example.com',443,1)
            self.assertEqual(error.exception.status, 403)

    def test_dns_failure_is_retriable(self):
        with patch('socket.getaddrinfo', side_effect=socket.gaierror()):
            with self.assertRaises(ResearchError) as error: public_addresses('example.com',443,1)
            self.assertTrue(error.exception.retryable)

    def test_robots_block_stops_before_page(self):
        with patch('backend.adapters.fetch.request', return_value=(200, {}, b'User-agent: *\nDisallow: /private')) as transport:
            with self.assertRaises(ResearchError): fetch_page('https://example.com/private')
            self.assertEqual(transport.call_count, 1)

    def test_redirect_cannot_bypass_robots(self):
        responses = [(200, {}, b'User-agent: *\nDisallow: /private'),
                     (302, {'location':'/private'}, b'')]
        with patch('backend.adapters.fetch.request', side_effect=responses) as transport:
            with self.assertRaises(ResearchError): fetch_page('https://example.com/')
            self.assertEqual(transport.call_count, 2)

    def test_robots_redirect_to_another_host_is_followed_but_private_is_not(self):
        # www.example.com/robots.txt -> example.com/robots.txt (RFC 9309), then the page itself.
        responses = [(301, {'location': 'https://example.com/robots.txt'}, b''), (200, {}, b'User-agent: *\nDisallow: /private'),
                     (200, {'content-type': 'text/html'}, b'<h1>Synthetic</h1>')]
        with patch('backend.adapters.fetch.request', side_effect=responses) as transport:
            self.assertEqual(fetch_page('https://www.example.com/').html, '<h1>Synthetic</h1>')
            self.assertEqual(transport.call_args_list[1].args[0], 'https://example.com/robots.txt')
        with patch('backend.adapters.fetch.request', side_effect=[(301, {'location': 'http://127.0.0.1/robots.txt'}, b'')]):
            with self.assertRaises(ResearchError): fetch_page('https://www.example.com/')

    def test_redirect_to_private_address_or_different_host_blocked(self):
        for location in ['http://127.0.0.1/', 'https://other.example/']:
            with self.subTest(location=location), patch('backend.adapters.fetch.request', side_effect=[(404, {}, b''), (302, {'location':location}, b'')]):
                with self.assertRaises(ResearchError) as caught: fetch_page('https://example.com/')
                # A page forwarding to another host is reported with where it goes, so the caller can decide.
                if location.startswith('https://other'):
                    self.assertIsInstance(caught.exception, CrossHostRedirect)
                    self.assertEqual(caught.exception.location, location)

    def test_success_and_non_html_rejection(self):
        with patch('backend.adapters.fetch.request', side_effect=[(404, {}, b''), (200, {'content-type':'text/html; charset=utf-8'}, b'<h1>Synthetic</h1>')]):
            self.assertEqual(fetch_page('https://example.com/').html, '<h1>Synthetic</h1>')
        with patch('backend.adapters.fetch.request', side_effect=[(404, {}, b''), (200, {'content-type':'application/pdf'}, b'data')]):
            with self.assertRaises(ResearchError): fetch_page('https://example.com/')

    def test_temporary_http_failure_is_retriable(self):
        with patch('backend.adapters.fetch.request', side_effect=[(404, {}, b''), (503, {}, b'')]):
            with self.assertRaises(ResearchError) as error: fetch_page('https://example.com/')
            self.assertTrue(error.exception.retryable)

    def test_transport_pins_address_and_preserves_hostname_for_tls(self):
        with patch('backend.adapters.fetch.public_addresses', return_value=['93.184.216.34']), patch('backend.adapters.fetch.PinnedHTTPSConnection') as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 200
            response.getheaders.return_value = [('content-type','text/html')]
            response.read1.side_effect = [b'<p>Fixture</p>', b'']
            _, _, body = request('https://example.com/', time.monotonic()+5)
            self.assertEqual(body,b'<p>Fixture</p>')
            self.assertEqual(connection.call_args.args[:3], ('example.com',443,'93.184.216.34'))
            self.assertEqual(connection.return_value.request.call_args.kwargs['headers']['Host'], 'example.com')

    def test_over_limit_body_and_compression_rejected(self):
        import gzip
        bomb = gzip.compress(b'\0' * 4_000_000)  # about 4 KB that would inflate past the 3 MB limit
        for headers, chunks in [([], [b'x'*3_000_001]), ([('content-encoding','br')], []), ([('content-encoding','gzip')], [bomb, b'']),
                                ([('content-encoding','gzip')], [b'not gzip at all'])]:
            with self.subTest(headers=headers), patch('backend.adapters.fetch.public_addresses', return_value=['93.184.216.34']), patch('backend.adapters.fetch.PinnedHTTPSConnection') as connection:
                response = connection.return_value.getresponse.return_value
                response.status = 200; response.getheaders.return_value = headers; response.read1.side_effect = chunks
                with self.assertRaises(ResearchError): request('https://example.com/', time.monotonic()+5)

    def test_certificate_and_connection_failures_are_named(self):
        import ssl
        bad = ssl.SSLCertVerificationError(1, 'certificate verify failed')
        bad.verify_message = 'unable to get local issuer certificate'
        for error, words in ((bad, 'security certificate could not be verified (unable to get local issuer certificate)'),
                             (ConnectionResetError(), 'dropped the connection'), (TimeoutError(), 'timed out')):
            with self.subTest(error=type(error).__name__), patch('backend.adapters.fetch.public_addresses', return_value=['93.184.216.34']), \
                    patch('backend.adapters.fetch.PinnedHTTPSConnection') as connection:
                connection.return_value.request.side_effect = error
                with self.assertRaises(ResearchError) as caught:
                    request('https://example.com/', time.monotonic() + 5)
                self.assertIn(words, str(caught.exception))
        self.assertFalse(caught.exception.retryable is False)

    def test_gzip_pages_are_inflated(self):
        import gzip
        with patch('backend.adapters.fetch.public_addresses', return_value=['93.184.216.34']), patch('backend.adapters.fetch.PinnedHTTPSConnection') as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 200; response.getheaders.return_value = [('content-encoding', 'gzip')]
            response.read1.side_effect = [gzip.compress(b'<p>Hello</p>'), b'']
            self.assertEqual(request('https://example.com/', time.monotonic()+5)[2], b'<p>Hello</p>')
