import asyncio
import hashlib
import sqlite3
import threading
from unittest.mock import patch

from backend.domain.errors import ResearchError
from backend.storage.repository import Repository
from tests.support import APITestCase, HTML, TOKEN


class APITests(APITestCase):
    async def test_health_auth_origin_and_host(self):
        self.assertEqual((await self.send('GET','/v1/health')).status_code,200)
        self.assertEqual((await self.send('GET','/v1/research',headers={'Authorization':''})).status_code,401)
        self.assertEqual((await self.send('GET','/v1/research',headers={'Origin':'https://evil.example'})).status_code,403)
        self.assertEqual((await self.send('GET','/v1/health',headers={'Host':'evil.example'})).status_code,400)

    async def test_evidence_and_unknowns_persist_after_restart(self):
        response = await self.research()
        self.assertEqual(response.status_code,200,response.text)
        result = response.json()
        self.assertFalse(result['synthetic'])
        self.assertEqual(result['identity_status'],'unresolved')
        self.assertIn('business_location',result['unknowns'])
        evidence = {e['id']:e for e in result['evidence']}
        for contact in result['contacts']:
            self.assertEqual(contact['attribution_state'],'extracted')
            for eid in contact['evidence_ids']:
                self.assertIn(contact['raw_value'],evidence[eid]['excerpt'])
                self.assertEqual(evidence[eid]['content_hash'],hashlib.sha256(HTML.encode()).hexdigest())
                self.assertEqual(evidence[eid]['source_url'],'https://synthetic.example/')
        repository = Repository(self.directory/'leaddesk.sqlite3')
        self.assertEqual(repository.get(result['id'])['contacts'],result['contacts'])
        with repository.connect() as db:
            self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM schema_migration').fetchone()[0], 18)
            with self.assertRaises(sqlite3.IntegrityError): db.execute("UPDATE evidence SET excerpt='changed'")

    async def test_idempotency_does_not_refetch_and_input_conflict(self):
        first = (await self.research()).json()
        repeat = (await self.research()).json()
        self.assertEqual(first['id'],repeat['id']); self.assertEqual(len(self.calls),1)
        self.assertEqual((await self.research(product='Changed offer')).status_code,409)
        self.assertEqual(len((await self.send('GET','/v1/research')).json()),1)

    async def test_correction_suppresses_research_history_and_future_same_host(self):
        first = (await self.research()).json()
        second = (await self.research('second',url='https://synthetic.example/contact')).json()
        unrelated = (await self.research('other',url='https://another.example/')).json()
        contact = next(c for c in first['contacts'] if c['type']=='phone')
        corrected = await self.send('POST','/v1/feedback',json={'contact_id':contact['id'],'category':'wrong_branch','comment':'Wrong branch','expected_value':'+1 202-555-0199'})
        self.assertEqual(corrected.status_code,200,corrected.text)
        self.assertTrue(next(c for c in corrected.json()['contacts'] if c['id']==contact['id'])['suppressed'])
        history = (await self.send('GET',f"/v1/research/{second['id']}")).json()
        self.assertTrue(next(c for c in history['contacts'] if c['type']=='phone')['suppressed'])
        third = (await self.research('third')).json()
        self.assertTrue(next(c for c in third['contacts'] if c['type']=='phone')['suppressed'])
        other = (await self.send('GET',f"/v1/research/{unrelated['id']}")).json()
        self.assertFalse(next(c for c in other['contacts'] if c['type']=='phone')['suppressed'])
        repeat = (await self.research()).json()
        self.assertTrue(next(c for c in repeat['contacts'] if c['type']=='phone')['suppressed'])
        self.assertEqual(repeat['feedback'][0]['expected_value'],'+1 202-555-0199')
        self.assertFalse(any(c['raw_value']=='+1 202-555-0199' for c in repeat['contacts']))

    async def test_directory_and_same_name_sites_never_auto_merge_or_attribute(self):
        first = (await self.research()).json()
        second = (await self.research('other',url='https://unrelated.example/')).json()
        self.assertNotEqual(first['business_id'],second['business_id'])
        self.assertEqual(first['canonical_name'],second['canonical_name'])
        directory = next(c for c in first['contacts'] if c['type']=='email')
        self.assertEqual(directory['attribution_state'],'extracted')
        self.assertIn('ownership',first['unknowns']['contact_ownership'])

    async def test_network_failure_has_no_fabricated_record_and_can_retry(self):
        self.failure = ResearchError('Temporary network failure',retryable=True,status=502)
        response = await self.research()
        self.assertEqual(response.status_code,502)
        self.assertTrue(response.json()['retryable'])
        self.assertEqual((await self.send('GET','/v1/research')).json(),[])
        self.failure = None
        self.assertEqual((await self.research()).status_code,200)

    async def test_synthetic_demo_uses_no_network_and_stays_labelled(self):
        response = await self.send('POST','/v1/demo',headers={'Idempotency-Key':'demo'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['synthetic'])
        self.assertEqual(len(response.json()['contacts']),3)
        self.assertEqual(self.calls,[])

    async def test_input_size_validation_and_unknown_contact(self):
        self.assertEqual((await self.research(product=' ')).status_code,422)
        self.assertEqual((await self.research(url='http://127.0.0.1/')).status_code,403)
        self.assertEqual((await self.send('POST','/v1/feedback',json={'contact_id':'nonexistent','category':'wrong_contact'})).status_code,404)
        self.assertEqual((await self.send('POST','/v1/research',content='x'*17000)).status_code,413)

    async def test_built_frontend_and_assets_are_served_with_security_headers(self):
        from backend.settings import ROOT
        import re
        if not (ROOT/'apps/web/dist/index.html').exists():
            self.skipTest('Build the frontend to verify serving its assets')
        response = await self.send('GET','/')
        self.assertEqual(response.status_code,200)
        self.assertIn('LeadDesk',response.text)
        self.assertEqual(response.headers['X-Frame-Options'],'DENY')
        self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
        script = re.search(r'src="([^"]+\.js)"',response.text).group(1)
        asset = await self.send('GET',script)
        self.assertEqual(asset.status_code,200)
        self.assertIn('javascript',asset.headers['content-type'])
        self.assertNotIn(TOKEN,asset.text)

    async def test_hardware_and_benchmark_routes_require_auth_and_same_origin(self):
        for method, path in [('POST', '/v1/hardware/profile'), ('GET', '/v1/benchmarks'),
                             ('GET', '/v1/benchmarks/missing'), ('POST', '/v1/benchmarks/parser')]:
            response = await self.send(method, path, json={}, headers={'Authorization': ''})
            self.assertEqual(response.status_code, 401, response.text)
        response = await self.send('POST', '/v1/hardware/profile', headers={'Origin': 'https://other.example'})
        self.assertEqual(response.status_code, 403)
        snapshot = (await self.send('POST', '/v1/hardware/profile')).json()
        self.assertEqual(snapshot['execution']['mode'], 'cpu')
        self.assertIsNone(snapshot['execution']['model'])

    async def test_parser_benchmark_history_idempotency_and_validation(self):
        headers = {'Idempotency-Key': 'parser-one'}
        first = await self.send('POST', '/v1/benchmarks/parser', json={'sample_count': 2}, headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        report = first.json()
        self.assertEqual(report['sample_count'], 10)
        self.assertEqual(report['passed_count'], 10)
        self.assertEqual(self.calls, [])
        repeat = await self.send('POST', '/v1/benchmarks/parser', json={'sample_count': 2}, headers=headers)
        self.assertEqual(repeat.json(), report)
        self.assertEqual((await self.send('GET', f"/v1/benchmarks/{report['id']}")).json(), report)
        self.assertEqual(len((await self.send('GET', '/v1/benchmarks')).json()), 1)
        self.assertEqual((await self.send('GET', '/v1/research')).json(), [])
        conflict = await self.send('POST', '/v1/benchmarks/parser', json={'sample_count': 3}, headers=headers)
        self.assertEqual(conflict.status_code, 409)
        for payload in ({'sample_count': 201}, {'sample_count': True}, {'model': 'unselected'}):
            response = await self.send('POST', '/v1/benchmarks/parser', json=payload, headers=headers)
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual((await self.send('POST', '/v1/benchmarks/parser', json={})).status_code, 422)
        self.assertEqual((await self.send('GET', '/v1/benchmarks/missing')).status_code, 404)

    async def test_benchmark_and_research_share_a_single_execution_slot(self):
        from backend.evaluation.runner import run_parser_benchmark

        entered, release = threading.Event(), threading.Event()

        def blocked_benchmark(hardware, sample_count):
            entered.set()
            if not release.wait(4):
                raise RuntimeError('Test failed to release benchmark')
            return run_parser_benchmark(hardware, sample_count)

        with patch('backend.api.app.run_parser_benchmark', side_effect=blocked_benchmark):
            pending = asyncio.create_task(self.send('POST', '/v1/benchmarks/parser',
                json={'sample_count': 2}, headers={'Idempotency-Key': 'running'}))
            try:
                for _ in range(100):
                    if entered.is_set():
                        break
                    await asyncio.sleep(.01)
                self.assertTrue(entered.is_set())
                rejected = await self.research()
                self.assertEqual(rejected.status_code, 429)
                self.assertTrue(rejected.json()['retryable'])
                self.assertEqual(self.calls, [])
            finally:
                release.set()
                await pending
        self.assertEqual((await self.research()).status_code, 200)
