"""Contact verification and competitor comparison; no network (fake mail servers, fixture data)."""
import struct
import unittest

import httpx

from backend.adapters.dns_mx import _query, parse_hosts
from backend.adapters.osm import OSMClient
from backend.adapters.smtp_probe import SMTPProbe, classify
from backend.api.app import create_app
from backend.domain.competitors import compare, competitor_line
from backend.domain.places import opportunity
from backend.domain.verification import phone_facts, verify
from backend.settings import Settings
from tests import test_overture as overture_fixtures
from tests import test_prospecting as fixtures
from tests.support import TOKEN


class FakeServer:
    """Records the SMTP conversation; answers RCPT from a table."""

    def __init__(self, answers, log):
        self.answers, self.log = answers, log

    def ehlo_or_helo_if_needed(self):
        self.log.append('EHLO')

    def mail(self, sender):
        self.log.append(f'MAIL FROM:<{sender}>')
        return 250, b'OK'

    def rcpt(self, address):
        self.log.append(f'RCPT TO:<{address}>')
        for prefix, answer in self.answers.items():
            if address.startswith(prefix):
                return answer
        return self.answers['*']

    def data(self, *_):  # pragma: no cover - must never be called
        raise AssertionError('DATA must never be sent')

    def rset(self):
        self.log.append('RSET')

    def quit(self):
        self.log.append('QUIT')


def probe_with(answers, hosts=('mx.example',)):
    log = []
    probe = SMTPProbe(lambda domain: list(hosts), connect=lambda host: FakeServer(answers, log))
    probe.last = {}  # no spacing delay in tests
    return probe, log


class SMTPProbeTests(unittest.TestCase):
    def test_accepted_rejected_catch_all_and_no_mail_server(self):
        probe, log = probe_with({'owner@': (250, b'2.1.5 OK'), 'leaddesk-': (550, b'5.1.1 No such user'), '*': (550, b'5.1.1 User unknown')})
        self.assertEqual(probe.check('owner@clinic.example')['result'], 'accepted')
        self.assertEqual(log[:3], ['EHLO', 'MAIL FROM:<>', 'RCPT TO:<owner@clinic.example>'])
        self.assertTrue(log[3].startswith('RCPT TO:<leaddesk-'))  # catch-all test address
        self.assertNotIn('DATA', ' '.join(log))
        self.assertEqual(probe.check('gone@clinic.example')['result'], 'rejected')
        catch_all, _ = probe_with({'*': (250, b'OK')})
        self.assertEqual(catch_all.check('anyone@catchall.example')['result'], 'catch_all')
        none = SMTPProbe(lambda domain: [], connect=lambda host: self.fail('no server to contact'))
        self.assertEqual(none.check('a@nomail.example')['result'], 'no_mail_server')

    def test_blocks_and_greylisting_are_not_answers(self):
        self.assertEqual(classify(554, b'5.7.1 Service unavailable; client host blocked using Spamhaus'), 'blocked')
        self.assertEqual(classify(451, b'4.7.1 Greylisted, try again later'), 'unknown')
        self.assertEqual(classify(550, b'5.1.1 The email account that you tried to reach does not exist'), 'rejected')

    def test_blocked_ipv4_port_25_is_remembered(self):
        import socket
        from unittest import mock
        attempts = []

        class Slow:
            def __init__(self, **_):
                pass

            def connect(self, address, port):
                attempts.append(address)
                raise socket.timeout('timed out')
        probe = SMTPProbe(lambda domain: ['mx.yahoo.example'])
        probe.last = {}
        infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.1', 25)), (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.2', 25))]
        with mock.patch('socket.getaddrinfo', return_value=infos), mock.patch('smtplib.SMTP', Slow):
            first = probe.check('a@yahoo.example')
            second = probe.check('b@yahoo.example')
        self.assertEqual((first['result'], second['result']), ('unreachable', 'unreachable'))
        self.assertIn('blocks outgoing port 25 over IPv4', second['detail'])
        self.assertEqual(attempts, ['192.0.2.1'])  # after one timeout the family is skipped

    def test_results_are_cached_for_a_day(self):
        probe, log = probe_with({'*': (550, b'5.1.1 unknown')})
        probe.check('x@a.example')
        count = len(log)
        probe.check('X@a.example')
        self.assertEqual(len(log), count)

    def test_mx_host_names_are_parsed_with_compression(self):
        ident, query = _query('clinic.example')
        name = b'\x06clinic\x07example\x00'
        answer = (b'\xc0\x0c' + struct.pack('>HHIH', 15, 1, 300, 8) + struct.pack('>H', 20) + b'\x03mx2\xc0\x0c' +
                  b'\xc0\x0c' + struct.pack('>HHIH', 15, 1, 300, 8) + struct.pack('>H', 10) + b'\x03mx1\xc0\x0c')
        reply = struct.pack('>HHHHHH', ident, 0x8180, 1, 2, 0, 0) + name + struct.pack('>HH', 15, 1) + answer
        self.assertEqual(parse_hosts(ident, reply), ['mx1.clinic.example', 'mx2.clinic.example'])


def lead(**extra):
    return {'id': 'overture/a', 'name': 'Fictional Realty', 'phone': '+92 300 1234567', 'phones': ['+92 300 1234567', '042-5754416'],
            'email': 'realty@gmail.com', 'emails': ['realty@gmail.com'], 'sources': ['Overture Maps'], 'field_sources': {},
            'evidence': {'url': 'https://map.example/a', 'datasets': ['meta'], 'updated': '2025-03-01'},
            'check': None, 'enrichment': None, 'website': None, 'websites': [], 'socials': [], 'lat': 31.5, 'lon': 74.3,
            'category': None, 'overture_category': 'real_estate_agent', 'category_label': 'Real estate agents'} | extra


class VerificationTests(unittest.TestCase):
    def test_numbering_plan_flags_old_format_numbers(self):
        self.assertEqual((phone_facts('0300 1234567', 'pk')['valid'], phone_facts('0300 1234567', 'pk')['line']), (True, 'mobile'))
        old = phone_facts('042-5754416', 'pk')
        self.assertFalse(old['valid'])
        self.assertIn('old-format', old['problem'])

    def test_statuses_and_reasons(self):
        site = {'checked_at': '2026-10-24T10:00:00', 'site': {'contacts': [{'type': 'phone', 'value': '0300-1234567', 'page_url': 'https://realty.example/contact'}]}}
        result = verify(lead(check=site), 'pk', {'realty@gmail.com': {'result': 'rejected', 'detail': '550', 'server': 'gmail', 'checked_at': '2026-10-24T10:00:00'}})
        by_value = {c['value']: c for c in result['contacts']}
        mobile = by_value['+92 300 1234567']
        self.assertEqual((mobile['status'], mobile['e164'], mobile['network']), ('confirmed', '+923001234567', 'Jazz'))
        self.assertIn('Shown on their own website (read 2026-10-24).', mobile['reasons'])
        self.assertEqual(by_value['042-5754416']['status'], 'likely_wrong')
        self.assertEqual(by_value['realty@gmail.com']['status'], 'likely_wrong')
        self.assertEqual(result['best'], {'type': 'phone', 'value': '+923001234567', 'status': 'confirmed'})
        accepted = verify(lead(phones=[]), 'pk', {'realty@gmail.com': {'result': 'accepted', 'server': 'gmail-smtp-in.l.google.com',
                                                                       'detail': '250', 'checked_at': '2026-10-24T10:00:00'}})
        email = next(c for c in accepted['contacts'] if c['type'] == 'email')
        self.assertEqual(email['status'], 'confirmed')
        self.assertIn('no email was sent', email['reasons'][0])
        single = verify(lead(phones=[]), 'pk')
        self.assertEqual({c['status'] for c in single['contacts']}, {'single_source'})

    def test_two_map_sources_corroborate(self):
        osm = lead(id='node/1', sources=['OpenStreetMap', 'Overture Maps'], also={'datasets': ['meta'], 'updated': '2025-03-01'},
                   phones=['+923001234567'], email=None, emails=[])
        phone = verify(osm, 'pk')['contacts'][0]
        self.assertEqual(phone['status'], 'corroborated')
        self.assertEqual([s['source'] for s in phone['seen_in']], ['OpenStreetMap', 'Overture Maps (meta)'])

    def test_score_counts_only_verified_contacts(self):
        item = lead()
        item['verification'] = verify(item, 'pk', {'realty@gmail.com': {'result': 'rejected', 'detail': '', 'server': 's', 'checked_at': 'x'}})
        reasons = opportunity(item, 'web_presence')['reasons']
        self.assertIn('+5 phone from a single source (not confirmed)', reasons)
        self.assertIn('+0 email: every known email looks wrong', reasons)


def site_check(grade, score, booking='not_found', whatsapp='not_found'):
    signals = [{'id': 'online_booking', 'state': booking, 'evidence': {'url': 'https://x.example/book', 'text': 'Book now'} if booking == 'yes' else None},
               {'id': 'whatsapp', 'state': whatsapp, 'evidence': None}]
    return {'site': {'signals': signals}, 'health': {'grade': grade, 'score': score}, 'checked_at': '2026-10-24T10:00:00'}


class CompetitorTests(unittest.TestCase):
    def test_findings_name_competitors_and_evidence(self):
        me = lead()
        rivals = [lead(id='overture/b', name='Rival Homes', lat=31.501, website='https://rival.example/', check=site_check('B', 82, booking='yes'),
                       socials=['https://www.facebook.com/rival', 'https://instagram.com/rival']),
                  lead(id='overture/c', name='Other Estates', lat=31.502, website='https://other.example/', socials=['https://www.facebook.com/o']),
                  lead(id='overture/far', name='Far Away Realty', lat=31.6, website='https://far.example/'),
                  lead(id='overture/d', name='Dental Place', overture_category='dental_clinic', category_label='Dentists', lat=31.5),
                  lead(id='overture/e', name='Builder Homes', overture_category='home_developer', lat=31.5005, website='https://bh.example/')]
        result = compare(me, [me] + rivals)
        # Same chosen business type (even a different map category) within 3 km, nearest first.
        self.assertEqual([r['name'] for r in result['competitors']], ['Builder Homes', 'Rival Homes', 'Other Estates'])
        texts = [f['text'] for f in result['findings']]
        self.assertIn('3 of 3 nearby competitors have their own website (Builder Homes, Rival Homes, Other Estates); Fictional Realty does not.', texts)
        self.assertIn('Best website nearby: Rival Homes, grade B (82/100); Fictional Realty has no working website.', texts)
        summary = next(f for f in result['findings'] if f.get('feature') == 'all')
        self.assertEqual(summary['text'], 'Competitor websites nearby offer online booking (Rival Homes); '
                                          'Fictional Realty has none of these without a website.')
        self.assertEqual(summary['evidence'][0]['url'], 'https://x.example/book')
        # With its own (read) website, each missing feature is its own finding.
        mine = lead(website='https://me.example/', check=site_check('C', 65))
        per_feature = compare(mine, [mine] + rivals)
        booking = next(f for f in per_feature['findings'] if f.get('feature') == 'online_booking')
        self.assertEqual(booking['text'], '1 competitor nearby offers online booking (Rival Homes); Fictional Realty: not found on its website.')
        self.assertIn('Best website nearby: Rival Homes, grade B (82/100); Fictional Realty\'s is C (65).', [f['text'] for f in per_feature['findings']])
        self.assertIn('2 nearby competitors are on Facebook; no Facebook page found for Fictional Realty.', texts)
        self.assertEqual(result['unchecked_websites'], ['overture/e', 'overture/c'])
        self.assertTrue(competitor_line(me, result).startswith('3 of 3 nearby competitors have their own website'))
        self.assertIsNone(compare(lead(id='overture/alone', lat=10.0), [me]))


class VerificationAPITests(fixtures.ProspectingAPITests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.client.aclose()
        self.smtp, self.log = probe_with({'*': (550, b'5.1.1 User unknown')})
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=fixtures.PLACE)
                                        if request.url.host == 'nominatim.openstreetmap.org' else httpx.Response(502, json={}))
        self.fetched = []

        def fetcher(url):
            self.fetched.append(url)
            return fixtures.Page(url, b'', '<title>Hyde Park Realty</title><p>Call +92 42 3577 0048</p>')
        self.app = create_app(Settings(self.directory, TOKEN), fetcher=fetcher, osm_client=OSMClient(transport),
                              mx_lookup=lambda d: 'has_mx', overture_client=overture_fixtures.FakeOverture(), smtp_probe=self.smtp)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://testserver',
                                        headers={'Authorization': f'Bearer {TOKEN}'})

    async def test_verify_reads_site_and_checks_mailboxes_only_on_request(self):
        result = await self.search(categories=['real_estate'], use_overture=True, offer='We build websites for real estate agents')
        hyde = next(c for c in result['candidates'] if c['name'] == 'Hyde Park Realty')
        base = f"/v1/prospecting/searches/{result['id']}/candidates/{hyde['id']}"
        plain = (await self.send('POST', base + '/verify', json={})).json()
        self.assertEqual(self.log, [])  # no mail server contacted without opt-in
        self.assertEqual(plain['steps'][0], {'step': 'read_website', 'status': 'done'})
        phone = next(c for c in plain['verification']['contacts'] if c['type'] == 'phone')
        self.assertEqual(phone['status'], 'confirmed')  # the same number is on their website
        full = (await self.send('POST', base + '/verify', json={'check_mailboxes': True})).json()
        email = next(c for c in full['verification']['contacts'] if c['type'] == 'email')
        self.assertEqual((email['value'], email['status']), ('info@hydepark.example', 'likely_wrong'))
        saved = (await self.send('GET', f"/v1/prospecting/searches/{result['id']}")).json()
        again = next(c for c in saved['candidates'] if c['id'] == hyde['id'])
        self.assertEqual(again['verification']['counts']['likely_wrong'], 1)
        self.assertEqual((await self.send('POST', base + '/verify', json={'check_mailboxes': 'yes'})).status_code, 422)
        bulk = (await self.send('POST', f"/v1/prospecting/searches/{result['id']}/verify", json={'limit': 5})).json()
        self.assertEqual(bulk, {'verified': 1, 'remaining': 0})

    async def test_compare_reads_competitor_websites(self):
        result = await self.search(categories=['real_estate'], use_overture=True, offer='We build websites for real estate agents', key='cmp')
        garden = next(c for c in result['candidates'] if c['name'] == 'Garden Homes')
        compared = (await self.send('POST', f"/v1/prospecting/searches/{result['id']}/candidates/{garden['id']}/compare", json={'limit': 3})).json()
        self.assertEqual([s['name'] for s in compared['steps']], ['Hyde Park Realty'])
        self.assertIn('https://hydepark.example/', self.fetched)  # HTTPS tried first
        self.assertEqual(compared['competitors']['competitors'][0]['grade'] is not None, True)
        self.assertTrue(any('own website' in f['text'] for f in compared['competitors']['findings']))


for name in [n for n in vars(fixtures.ProspectingAPITests) if n.startswith('test_')]:
    setattr(VerificationAPITests, name, None)

if __name__ == '__main__':
    unittest.main()
