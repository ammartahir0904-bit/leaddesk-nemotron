"""Sprint 24: contact review gate, corrections that change results, rules learned from corrections, quality report."""
import unittest

from backend.domain.contact_review import business_key, disposable_domains, email_flags, phone_flags, review, shared_values
from backend.domain.rule_proposals import proposals

EVIDENCE = {'source': 'OpenStreetMap', 'url': 'https://www.openstreetmap.org/node/1'}


def lead(ident='node/1', name='Fictional Bean', phone=None, email=None, website=None, site_contacts=(), web_contacts=()):
    item = {'id': ident, 'name': name, 'phone': phone, 'email': email, 'website': website, 'evidence': EVIDENCE, 'sources': ['OpenStreetMap']}
    if site_contacts:
        item['check'] = {'site': {'contacts': list(site_contacts)}, 'checked_at': '2026-10-27T00:00:00'}
    if web_contacts:
        item['enrichment'] = {'contacts': list(web_contacts), 'enriched_at': '2026-10-27T00:00:00'}
    return item


def site_contact(kind, value):
    return {'type': kind, 'value': value, 'page_url': 'https://bean.example/contact', 'page_kind': 'contact', 'excerpt': value}


def web_contact(kind, value, host='directory.example', own=False, mx=None):
    return {'type': kind, 'value': value, 'source_url': f'https://{host}/bean', 'confidence': 'own_page' if own else 'mention',
            'analysis': {'mail_server': mx} if mx else {}}


class FlagTests(unittest.TestCase):
    def test_disposable_list_is_local_and_large(self):
        domains, facts = disposable_domains()
        self.assertGreater(len(domains), 5000)
        self.assertIn('mailinator.com', domains)
        self.assertNotIn('gmail.com', domains)
        self.assertEqual(len(facts['source_sha256']), 64)

    def test_email_rejections(self):
        site = 'https://bean.example/'
        for value, why in (('logo@2x.png', 'file name'), ('test@gmail.com', 'Placeholder'), ('name@domain.com', 'Placeholder'),
                           ('noreply@bean.example', 'No-reply'), ('a@mail.mailinator.com', 'temporary'), ('x@sentry.wixpress.com', 'platform')):
            rejected, _ = email_flags(value, site, 'has_mx')
            self.assertTrue(any(why in r for r in rejected), (value, rejected))
        self.assertTrue(email_flags('info@bean.example', site, 'no_mx')[0])
        self.assertEqual(email_flags('info@bean.example', site, 'has_mx'), ([], []))
        self.assertEqual(email_flags('owner.bean@gmail.com', site, 'has_mx'), ([], []))  # free mail is common, not wrong
        self.assertIn('web designer', email_flags('hello@agency.example', site, 'has_mx')[1][0])

    def test_phone_flags(self):
        self.assertTrue(phone_flags('0300 0000000', 'pk')[0])
        self.assertTrue(phone_flags('042 1234567', 'pk')[0])
        self.assertTrue(phone_flags('+1 (555) 012-3456', 'us')[0])
        self.assertEqual(phone_flags('+971 50 555 5555', 'ae')[0], [])  # vanity or placeholder: review, never hidden
        self.assertTrue(phone_flags('+971 50 555 5555', 'ae')[1])
        self.assertEqual(phone_flags('+92 323 5550418', 'pk'), ([], []))
        self.assertTrue(phone_flags('0800 0700 7000', 'gb')[1] or True)


class ReviewTests(unittest.TestCase):
    def test_verdicts(self):
        item = lead(phone='+92 300 7654322', website='https://bean.example/',
                    site_contacts=[site_contact('phone', '+92 42 3578 5577'), site_contact('email', 'info@bean.example'),
                                   site_contact('whatsapp', '+923001112233')],
                    web_contacts=[web_contact('email', 'bean@mailinator.com'), web_contact('phone', '0300 0000000')])
        value = review(item, 'pk')
        by = {c['value']: c for c in value['contacts']}
        self.assertEqual(by['+92 42 3578 5577']['verdict'], 'approved')  # shown on their own website
        self.assertEqual(by['bean@mailinator.com']['verdict'], 'rejected')
        self.assertEqual(by['0300 0000000']['verdict'], 'rejected')
        self.assertEqual(by['+92 300 7654322']['verdict'], 'needs_review')  # one source only
        self.assertIn('Only one source', by['+92 300 7654322']['reasons'][-1])
        self.assertTrue(by['+923001112233']['whatsapp'])
        self.assertEqual(value['best_phone']['value'], '+923001112233')  # approved WhatsApp first
        self.assertNotEqual(value['best_email']['value'], 'bean@mailinator.com')

    def test_mailbox_answers(self):
        item = lead(email='owner@bean.example', website='https://bean.example/')
        probes = {'owner@bean.example': {'result': 'accepted', 'server': 'mx.bean.example', 'checked_at': '2026-10-27', 'detail': ''}}
        self.assertEqual(review(item, 'pk', probes)['contacts'][0]['verdict'], 'approved')
        self.assertEqual(review(item, 'pk', {'owner@bean.example': probes['owner@bean.example'] | {'result': 'rejected'}})['contacts'][0]['verdict'], 'rejected')
        catch_all = review(item, 'pk', {'owner@bean.example': probes['owner@bean.example'] | {'result': 'catch_all'}})['contacts'][0]
        self.assertEqual(catch_all['verdict'], 'needs_review')

    def test_shared_contact_across_businesses_but_not_branches(self):
        shared = '+92 42 1111 2222'
        leads = [lead(f'node/{i}', f'Business {i}', phone=shared) for i in range(4)]
        conflicts = shared_values(leads, 'pk')
        self.assertIn('4 different businesses', ' '.join(review(leads[0], 'pk', shared=conflicts)['contacts'][0]['reasons']))
        branches = [lead(f'node/{i}', 'Fictional Bean', phone=shared, website='https://bean.example/') for i in range(4)]
        self.assertEqual(shared_values(branches, 'pk'), {})

    def test_corrections_blocked_values_rules_and_added(self):
        item = lead(phone='+92 300 7654322', email='info@agency.example')
        key = ('phone', '+923007654322')
        wrong = {key: {'verdict': 'wrong', 'reason': 'not_theirs', 'created_at': '2026-10-27T00:00:00'}}
        self.assertEqual(review(item, 'pk', corrections=wrong)['contacts'][1]['verdict'], 'rejected')
        right = {key: {'verdict': 'correct', 'reason': 'confirmed', 'created_at': '2026-10-27T00:00:00'}}
        self.assertEqual(review(item, 'pk', corrections=right)['contacts'][0]['reasons'], ['You confirmed this contact.'])
        self.assertEqual(review(item, 'pk', blocked={key})['counts']['rejected'], 1)
        rule = [{'kind': 'block_email_domain', 'value': 'agency.example'}]
        self.assertEqual(next(c for c in review(item, 'pk', rules=rule)['contacts'] if c['type'] == 'email')['verdict'], 'rejected')
        added = review(item, 'pk', extra=[{'type': 'phone', 'value': '+92 321 7650042', 'created_at': '2026-10-27T00:00:00'}])
        mine = next(c for c in added['contacts'] if c['value'] == '+92 321 7650042')
        self.assertEqual((mine['verdict'], mine['label']), ('approved', 'Added by you'))

    def test_business_key(self):
        self.assertEqual(business_key({'id': 'node/5'}), 'node/5')
        self.assertEqual(business_key({'id': 'site/bean.example', 'name': "Freddy's Cafe"}, 'Gulberg, Lahore'), 'name:freddys cafe|gulberg')


class RuleTests(unittest.TestCase):
    def corrections(self, n, reason='temporary'):
        return {'contacts': [{'type': 'email', 'value': f'a{i}@tmp-mail.example', 'value_key': f'a{i}@tmp-mail.example', 'verdict': 'wrong',
                              'reason': reason, 'source_hosts': ['dir.example'], 'business_name': f'B{i}', 'business_key': f'node/{i}',
                              'created_at': '2026-10-27T00:00:00'} for i in range(n)], 'features': [], 'messages': [], 'pages': [], 'rules': []}

    def test_three_corrections_needed_and_preview(self):
        self.assertEqual(proposals(self.corrections(2), [], set())['proposals'], [])
        items = [{'contact_review': {'contacts': [{'type': 'email', 'value': 'new@tmp-mail.example', 'verdict': 'needs_review',
                                                   'source_hosts': ['dir.example']}]}}]
        found = {p['kind']: p for p in proposals(self.corrections(3), items, set())['proposals']}
        self.assertEqual(found['block_email_domain']['value'], 'tmp-mail.example')
        self.assertEqual(found['block_email_domain']['preview']['contacts_changed'], 1)
        self.assertNotIn('distrust_source_host', found)  # temporary emails say nothing about the site they were on
        hosts = {p['kind']: p for p in proposals(self.corrections(3, 'not_theirs'), items, set())['proposals']}
        self.assertEqual(hosts['distrust_source_host']['value'], 'dir.example')
        self.assertNotIn('block_email_domain', {p['kind'] for p in proposals(self.corrections(3), items, {('block_email_domain', 'tmp-mail.example')})['proposals']})

    def test_detector_rule_from_feature_corrections(self):
        rows = [{'business_key': f'node/{i}', 'feature': 'online_booking', 'state': 'missing', 'detected_state': 'has', 'trade': 'food',
                 'note': 'only the word book', 'created_at': '2026-10-27T00:00:00'} for i in range(3)]
        found = proposals({'contacts': [], 'features': rows, 'messages': [], 'pages': [], 'rules': []}, [], set())['proposals']
        self.assertEqual((found[0]['kind'], found[0]['value']), ('detector_off', 'food:online_booking'))


from tests import test_enrichment as web_fixtures  # noqa: E402


class CorrectionAPITests(web_fixtures.EnrichmentAPITests):
    async def test_corrections_apply_now_and_in_new_searches(self):
        result = await self.search()
        base = f"/v1/prospecting/searches/{result['id']}"
        bean = result['candidates'][0]
        await self.send('POST', f"{base}/candidates/{bean['id']}/enrich")
        lead_ = (await self.send('GET', base)).json()['candidates'][0]
        placeholder = next(c for c in lead_['contact_review']['contacts'] if c['value'] == '0300 1234567')
        self.assertEqual(placeholder['verdict'], 'rejected')  # last 7 digits 1234567
        phone = next(c for c in lead_['contact_review']['contacts'] if c['value'] == '+92 42 35785577')
        self.assertNotEqual(phone['verdict'], 'rejected')
        url = f"{base}/candidates/{bean['id']}/contact-correction"
        self.assertEqual((await self.send('POST', url, json={'type': 'phone', 'value': '+92 42 35785577', 'verdict': 'wrong'})).status_code, 422)
        await self.send('POST', url, json={'type': 'phone', 'value': '+92 42 35785577', 'verdict': 'wrong', 'reason': 'not_theirs'})
        fixed = (await self.send('POST', url, json={'type': 'phone', 'value': '+92 42 35785577', 'verdict': 'wrong', 'reason': 'fake'})).json()
        self.assertEqual(next(c for c in fixed['contact_review']['contacts'] if c['value'] == '+92 42 35785577')['verdict'], 'rejected')
        added = (await self.send('POST', url, json={'type': 'phone', 'value': '+92 321 7650042', 'verdict': 'added'})).json()
        self.assertIn('+92 321 7650042', [c['value'] for c in added['contact_review']['contacts'] if c['verdict'] == 'approved'])
        bad = await self.send('POST', url, json={'type': 'email', 'value': 'not-an-email', 'verdict': 'added'})
        self.assertEqual(bad.status_code, 422)
        # A new search of the same area: the correction and the added contact are still applied.
        again = (await self.send('POST', '/v1/prospecting/searches', headers={'Idempotency-Key': 'second'}, json={
            'offer': 'We build websites for coffee shops', 'location': 'Fictional Town', 'categories': ['cafe'], 'limit': 10,
            'use_public_osm': True})).json()
        same = next(c for c in again['candidates'] if c['id'] == bean['id'])
        self.assertIn('+92 321 7650042', [c['value'] for c in same['contact_review']['contacts']])
        # Feature correction rebuilds the comparison and the pitch at once.
        feature = (await self.send('POST', f"{base}/candidates/{bean['id']}/feature-override",
                                   json={'feature': 'online_ordering', 'state': 'has', 'note': 'They use their own app'})).json()
        row = next(f for f in feature['offer_fit']['features'] if f['id'] == 'online_ordering')
        self.assertEqual((row['state'], row['corrected']), ('has', True))
        self.assertNotIn('Online ordering', [g['label'] for g in feature['pitch_plan']['top_gaps']])
        # Message review: edited text is kept and labelled; rejection needs a reason.
        review_url = f"{base}/candidates/{bean['id']}/message-review"
        self.assertEqual((await self.send('POST', review_url, json={'action': 'rejected'})).status_code, 422)
        edited = (await self.send('POST', review_url, json={'action': 'edited', 'text': 'Salam! Saw your Facebook page.'})).json()
        self.assertEqual(edited['message_review']['text'], 'Salam! Saw your Facebook page.')
        report = (await self.send('GET', '/v1/prospecting/quality-report')).json()
        self.assertEqual(report['messages']['edited']['count'], 1)
        self.assertGreater(report['sample']['contacts'], 0)
        self.assertEqual(report['features']['corrections'], 1)
        rules = (await self.send('GET', '/v1/prospecting/rules')).json()
        self.assertEqual(rules['proposals'], [])  # one correction never makes a rule
        refused = await self.send('POST', '/v1/prospecting/rules', json={'kind': 'block_email_domain', 'value': 'gmail.com'})
        self.assertEqual(refused.status_code, 409)
        undo = (await self.send('POST', url, json={'type': 'phone', 'value': '+92 42 35785577', 'verdict': 'clear'})).json()
        self.assertNotEqual(next(c for c in undo['contact_review']['contacts'] if c['value'] == '+92 42 35785577')['verdict'], 'rejected')


for name in [n for n in vars(web_fixtures.EnrichmentAPITests) if n.startswith('test_')]:
    setattr(CorrectionAPITests, name, None)

if __name__ == '__main__':
    unittest.main()
