"""Deterministic contact analysis and DNS reply parsing; no network."""
import struct
import unittest

from backend.adapters.dns_mx import MXLookup, parse
from backend.domain.contact_analysis import analyse_contacts, analyse_email, analyse_phone, contact_points

MX = {'gmail.com': 'has_mx', 'brew.example': 'has_mx', 'agency.example': 'has_mx', 'dead.example': 'no_domain', 'null.example': 'null_mx'}.get


def reply(ident, rcode=0, answers=()):
    header = struct.pack('>HHHHHH', ident, 0x8180 | rcode, 1, len(answers), 0, 0)
    question = b'\x07example\x03com\x00' + struct.pack('>HH', 15, 1)
    body = b''.join(b'\xc0\x0c' + struct.pack('>HHIH', kind, 1, 60, len(data)) + data for kind, data in answers)
    return header + question + body


class DNSTests(unittest.TestCase):
    def test_reply_parsing(self):
        self.assertEqual(parse(7, reply(7, answers=[(15, b'\x00\x0a\x04mail\xc0\x0c')])), 'has_mx')
        self.assertEqual(parse(7, reply(7, answers=[(15, b'\x00\x00\x00')])), 'null_mx')
        self.assertEqual(parse(7, reply(7, answers=[(5, b'\xc0\x0c')])), 'no_mx')
        self.assertEqual(parse(7, reply(7, rcode=3)), 'no_domain')
        for bad in (b'', reply(8), reply(7, rcode=2)):
            with self.assertRaises(ValueError):
                parse(7, bad)

    def test_invalid_domain_is_not_queried(self):
        lookup = MXLookup(servers=['192.0.2.1'], timeout=.01)
        self.assertEqual(lookup('bad..domain'), 'invalid')
        self.assertEqual(lookup('-bad.example'), 'invalid')


class EmailTests(unittest.TestCase):
    def test_signals(self):
        role = analyse_email('info@brew.example', 'https://www.brew.example/', MX)
        self.assertEqual((role['mailbox'], role['provider'], role['matches_website'], role['quality']), ('role', 'own_domain', True, 'good'))
        free = analyse_email('owner.name@gmail.com', 'https://brew.example', MX)
        self.assertEqual((free['mailbox'], free['provider'], free['quality']), ('named', 'free_mail', 'good'))
        self.assertEqual(free['warnings'], [])
        agency = analyse_email('studio@agency.example', 'https://brew.example', MX)
        self.assertIn('web agency', agency['warnings'][0])
        self.assertEqual(analyse_email('sales@dead.example', None, MX)['quality'], 'unusable')
        self.assertEqual(analyse_email('a@null.example', None, MX)['mail_server'], 'null_mx')
        self.assertEqual(analyse_email('noreply@brew.example', None, MX)['quality'], 'unusable')
        self.assertEqual(analyse_email('not-an-email', None, MX)['quality'], 'invalid')
        self.assertEqual(analyse_email('x@brew.example')['quality'], 'unchecked')


class PhoneTests(unittest.TestCase):
    def test_formats(self):
        cases = [('0300 1234567', 'pk', '+923001234567', 'mobile'), ('3001234567', 'pk', '+923001234567', 'mobile'),
                 ('042-35785577', 'pk', '+924235785577', 'landline_or_other'), ('+971 50 123 4567', 'pk', '+971501234567', 'mobile'),
                 ('00447700900123', None, '+447700900123', 'mobile'), ('(202) 555-0148', 'us', '+12025550148', 'unknown'),
                 ('357855773', 'pk', None, 'unknown'), ('92 301 7654320', 'pk', '+923017654320', 'mobile'),
                 ('+92 42 352466 9192', 'pk', None, 'unknown'), ('+1 202 555 01489', None, None, 'unknown'), ('12345', 'pk', None, 'unknown'), ('0300 1234567', None, None, 'unknown')]
        for raw, country, e164, line in cases:
            with self.subTest(raw=raw, country=country):
                value = analyse_phone(raw, country)
                self.assertEqual((value['e164'], value['line']), (e164, line))
        self.assertIsNone(analyse_phone('042-35785577', 'pk')['whatsapp_link'])
        self.assertEqual(analyse_phone('0300 1234567', 'pk')['whatsapp_link'], 'https://wa.me/923001234567')

    def test_combined_summary_and_points(self):
        value = analyse_contacts('info@brew.example; bad', '0300 1234567 / 042-35785577', 'https://brew.example', 'pk', MX)
        self.assertEqual(len(value['items']), 4)
        self.assertEqual(value['reachable_by'], 'email and phone')
        self.assertEqual(contact_points(value), (2, ['email domain can receive mail', 'mobile number']))
        self.assertEqual(analyse_contacts(None, None)['reachable_by'], None)


if __name__ == '__main__':
    unittest.main()
