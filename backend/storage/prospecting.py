"""Saved prospect searches, cached geocodes and website-check links."""
import json

from backend.domain.errors import ResearchError
from backend.domain.competitors import compare, competitor_line
from backend.domain.contact_review import business_key, review as review_contacts, shared_values, value_key
from backend.domain.enrichment import apply_feedback, classify, tidy
from backend.domain.identity import TRUSTED
from backend.domain.offer_fit import offer_fit, pitch
from backend.domain.places import opportunity, pitch_line
from backend.domain.verification import verify
from backend.storage.repository import now, request_hash, uid

MAX_SEARCHES = 500


class ProspectRepository:
    def __init__(self, repository):
        self.repository = repository

    def cached_place(self, location):
        key = ' '.join(location.casefold().split())
        with self.repository.connect() as db:
            row = db.execute('SELECT result_json FROM geocode_cache WHERE query=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def cache_place(self, location, place):
        key = ' '.join(location.casefold().split())
        with self.repository.connect() as db:
            db.execute('INSERT OR REPLACE INTO geocode_cache VALUES(?,?,?)', (key, json.dumps(place), now()))

    def replay(self, key, payload):
        digest = request_hash({'operation': 'prospect_search', 'input': payload.model_dump()})
        with self.repository.connect() as db:
            row = db.execute('SELECT id,request_hash FROM prospect_search WHERE idempotency_key=?', (key,)).fetchone()
        if row and row['request_hash'] != digest:
            raise ResearchError('This search request key was used with different inputs.', status=409)
        return (self.get(row['id']) if row else None), digest

    def save(self, key, digest, payload, result):
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT id FROM prospect_search WHERE idempotency_key=?', (key,)).fetchone()
            if row:
                search_id = row['id']
            else:
                if db.execute('SELECT COUNT(*) FROM prospect_search').fetchone()[0] >= MAX_SEARCHES:
                    raise ResearchError('Saved search limit reached (500). Delete old searches.', status=429)
                search_id = uid()
                db.execute('INSERT INTO prospect_search VALUES(?,?,?,?,?,?)',
                           (search_id, key, digest, now(), json.dumps(payload.model_dump()), json.dumps(result)))
        return self.get(search_id)

    def get(self, search_id):
        with self.repository.connect() as db:
            row = db.execute('SELECT * FROM prospect_search WHERE id=?', (search_id,)).fetchone()
            if row is None:
                raise ResearchError('Prospect search not found.', status=404)
            checks = {r['candidate_id']: json.loads(r['result_json']) | {'research_id': r['research_id'] or None, 'checked_at': r['checked_at']}
                      for r in db.execute('SELECT * FROM prospect_check WHERE search_id=?', (search_id,))}
            enriched = {r['candidate_id']: json.loads(r['result_json']) | {'enriched_at': r['enriched_at']}
                        for r in db.execute('SELECT * FROM prospect_enrichment WHERE search_id=?', (search_id,))}
            verified = {r['candidate_id']: json.loads(r['result_json']) | {'verified_at': r['verified_at']}
                        for r in db.execute('SELECT * FROM prospect_verification WHERE search_id=?', (search_id,))}
            learned = self.learned(db)
            blocked = {(r['kind'], r['value_key']) for r in db.execute('SELECT kind,value_key FROM blocked_value')}
            reviews = {r['candidate_id']: dict(r) for r in db.execute('SELECT * FROM message_review WHERE search_id=?', (search_id,))}
            pack = db.execute('SELECT features_json FROM offer_pack WHERE search_id=?', (search_id,)).fetchone()
            chosen = set(json.loads(pack[0])) if pack else None
            feedback = {}
            for r in db.execute('SELECT candidate_id,url,verdict FROM web_feedback WHERE search_id=?', (search_id,)):
                feedback.setdefault(r['candidate_id'], {})[r['url']] = r['verdict']
            analyses = {r['candidate_id']: json.loads(r['result_json']) | {'created_at': r['created_at'], 'verdict': r['verdict'],
                                                                           'verdict_note': r['verdict_note'], 'verdict_at': r['verdict_at']}
                        for r in db.execute('SELECT * FROM prospect_ai WHERE search_id=?', (search_id,))}
        result = json.loads(row['result_json'])
        location = json.loads(row['input_json'])['location']
        keys = {item['id']: business_key(item, location) for item in result['candidates']}
        with self.repository.connect() as db:
            marks = ','.join('?' * len(keys)) or "''"
            corrections, pages, overrides = {}, {}, {}
            for r in db.execute(f'SELECT * FROM contact_correction WHERE business_key IN ({marks})', list(keys.values())):
                corrections.setdefault(r['business_key'], []).append(dict(r))
            for r in db.execute(f'SELECT * FROM page_feedback WHERE business_key IN ({marks})', list(keys.values())):
                pages.setdefault(r['business_key'], {})[r['url']] = r['verdict']
            for r in db.execute(f'SELECT * FROM feature_override WHERE business_key IN ({marks})', list(keys.values())):
                overrides.setdefault(r['business_key'], {})[r['feature']] = dict(r)
        for item in result['candidates']:
            item['business_key'] = keys[item['id']]
            # Page answers given for this business in any search apply here too; this search's own answers win.
            feedback[item['id']] = pages.get(item['business_key'], {}) | feedback.get(item['id'], {})
            item['check'] = checks.get(item['id'])
            # The user's "Is this them?" answers apply on every read, so a correction takes effect at once.
            item['enrichment'] = apply_feedback(tidy(enriched.get(item['id'])), feedback.get(item['id']))
            item['web_feedback'] = feedback.get(item['id']) or {}
            item['ai'] = analyses.get(item['id'])
            web = item['enrichment']
            if web:
                # Transparent bonus for what web search found on the business's own pages.
                for found, label in ((web['website_candidates'], 'own website found online'),
                                     (web['social_pages'], 'social profile found online'),
                                     ([c for c in web['contacts'] if c.get('confidence') == 'own_page'], 'contact on their own page')):
                    if found:
                        item['priority_points'] += 1
                        item['priority_reasons'] = item['priority_reasons'] + [label]
            site, identity = (item['check'] or {}).get('site'), (item['check'] or {}).get('identity')
            down = (item['check'] or {}).get('unreachable')
            if down and result.get('offer_kind') == 'web_presence':
                item['priority_points'] += 2
                item['priority_reasons'] = item['priority_reasons'] + [f"listed website could not be loaded ({item['check']['checked_at'][:10]})"]
            elif down:
                item['priority_reasons'] = item['priority_reasons'] + ['listed website could not be loaded']
            if identity and identity['verdict'] in {'different_business', 'possible_other_branch'}:
                item['priority_reasons'] = item['priority_reasons'] + ['checked website may be another business or branch (not credited)']
            elif site:
                # Gaps on their own website that relate to the user's product: +1 each, at most +3.
                gaps = [g['label'].casefold() for g in site['signals'] if g['gap'] and g.get('relevant')][:3]
                item['priority_points'] += len(gaps)
                item['priority_reasons'] = item['priority_reasons'] + [f'website gap: {g}' for g in gaps]
            # Social pages their own website links to (footer icons, schema.org sameAs): the most reliable social source.
            item['site_socials'] = []
            if site and (not identity or identity['verdict'] in TRUSTED):
                for url in site.get('social_links') or []:
                    kind, platform = classify(url)
                    if kind in {'social', 'link_hub'} and platform not in {s['platform'] for s in item['site_socials']} \
                            and item['web_feedback'].get(url) != 'no':
                        item['site_socials'].append({'platform': platform, 'url': url, 'source': 'linked from their website'})
            item.setdefault('sources', ['OpenStreetMap'])
            record = verified.get(item['id'])
            item['verification'] = verify(item, result['place'].get('country_code'), record['probes']) | {
                'verified_at': record['verified_at']} if record else None
            item['_probes'] = record['probes'] if record else None
        country = result['place'].get('country_code')
        shared = shared_values(result['candidates'], country)
        for item in result['candidates']:
            # The contact review gate: only approved and needs-review contacts are used anywhere downstream.
            mine = corrections.get(item['business_key'], [])
            item['contact_review'] = review_contacts(
                item, country, item.pop('_probes'), shared,
                {(c['type'], c['value_key']): c for c in mine}, blocked, learned,
                [{'type': c['type'], 'value': c['value'], 'created_at': c['created_at']} for c in mine if c['verdict'] == 'added'])
        for item in result['candidates']:
            # Second pass: competitors need every business's checks and enrichment loaded.
            item['competitors'] = compare(item, result['candidates'])
            health = (item['check'] or {}).get('health')
            item['opportunity'] = opportunity(item, result.get('offer_kind'), health)
            item['pitch'] = pitch_line(item, None, item['opportunity']['website_status'], health)
            line = competitor_line(item, item['competitors'])
            item['pitch_competitors'] = line
            # What the user delivers vs. what this business has, and the rules-first pitch, from current evidence.
            offer = json.loads(row['input_json'])['offer']
            item['offer_fit'] = offer_fit(item, offer, result.get('offer_kind'), item['opportunity']['website_status'], chosen,
                                          overrides.get(item['business_key']), learned)
            item['pitch_plan'] = pitch(item, offer, item['offer_fit'], json.loads(row['input_json'])['location'], item['opportunity']['website_status'])
            if item['ai'] and item['ai'].get('method') == 'ollama_pitch_polish_v1':
                item['ai']['stale'] = item['ai']['template_message'] != item['pitch_plan']['message']
            reviewed = reviews.get(item['id'])
            if reviewed:
                reviewed['stale'] = reviewed['template_message'] != item['pitch_plan']['message'] and reviewed['action'] != 'edited'
            item['message_review'] = reviewed
        return {'id': row['id'], 'created_at': row['created_at'], 'input': json.loads(row['input_json']),
                'offer_pack': sorted(chosen) if chosen is not None else None} | result

    def all_searches(self):
        with self.repository.connect() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM prospect_search ORDER BY created_at')]
        return [self.get(i) for i in ids]

    def recent(self, offset=0):
        with self.repository.connect() as db:
            total = db.execute('SELECT COUNT(*) FROM prospect_search').fetchone()[0]
            rows = db.execute('SELECT id,created_at,input_json,result_json FROM prospect_search ORDER BY created_at DESC,id DESC LIMIT 20 OFFSET ?', (offset,)).fetchall()
        items = []
        for row in rows:
            data, result = json.loads(row['input_json']), json.loads(row['result_json'])
            items.append({'id': row['id'], 'created_at': row['created_at'], 'location': data['location'], 'offer': data['offer'],
                          'categories': data['categories'], 'name_keyword': data['name_keyword'],
                          'place': result['place']['display_name'], 'count': len(result['candidates'])})
        return {'items': items, 'total': total, 'offset': offset, 'next_offset': offset + 20 if offset + 20 < total else None}

    def candidate(self, search_id, candidate_id):
        search = self.get(search_id)
        item = next((c for c in search['candidates'] if c['id'] == candidate_id), None)
        if item is None:
            raise ResearchError('Business not found in this search.', status=404)
        return search, item

    def record_check(self, search_id, candidate_id, research_id, result):
        with self.repository.connect() as db:
            db.execute('INSERT OR REPLACE INTO prospect_check VALUES(?,?,?,?,?)',
                       (search_id, candidate_id, research_id, json.dumps(result), now()))

    @staticmethod
    def learned(db):
        return [dict(r) | {'evidence': json.loads(r['evidence_json']), 'preview': json.loads(r['preview_json'])}
                for r in db.execute("SELECT * FROM learned_rule WHERE status='active'")]

    def correct_contact(self, search_id, item, kind, value, verdict, reason, country, hosts):
        """A correction keyed to the business, so it also applies in future searches. 'clear' removes it."""
        key = value_key(kind, value, country)
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if verdict == 'clear':
                # The block list entry first: it is found through the correction being removed.
                db.execute('DELETE FROM blocked_value WHERE correction_id IN (SELECT id FROM contact_correction WHERE business_key=? '
                           'AND type=? AND value_key=?)', (item['business_key'], kind, key))
                db.execute('DELETE FROM contact_correction WHERE business_key=? AND type=? AND value_key=?', (item['business_key'], kind, key))
                return
            ident = uid()
            db.execute('INSERT INTO contact_correction VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(business_key,type,value_key) DO UPDATE SET '
                       'verdict=excluded.verdict, reason=excluded.reason, value=excluded.value, source_hosts=excluded.source_hosts, '
                       'search_id=excluded.search_id, created_at=excluded.created_at',
                       (ident, item['business_key'], item['name'], kind, value.strip(), key, verdict, reason, json.dumps(hosts), search_id, now()))
            # An updated correction keeps its first id; the block list must point at that one.
            ident = db.execute('SELECT id FROM contact_correction WHERE business_key=? AND type=? AND value_key=?',
                               (item['business_key'], kind, key)).fetchone()[0]
            if verdict == 'wrong' and reason in {'fake', 'temporary'}:
                # Fake or temporary values are blocked for every business, in every search.
                db.execute('INSERT OR REPLACE INTO blocked_value VALUES(?,?,?,?,?)', (kind, key, reason, ident, now()))
                if kind == 'email' and reason == 'temporary':
                    db.execute('INSERT OR REPLACE INTO blocked_value VALUES(?,?,?,?,?)', ('email_domain', key.rpartition('@')[2], reason, ident, now()))
            elif verdict != 'wrong':
                db.execute('DELETE FROM blocked_value WHERE kind=? AND value_key=?', (kind, key))

    def page_answer(self, business, url, verdict):
        with self.repository.connect() as db:
            if verdict == 'clear':
                db.execute('DELETE FROM page_feedback WHERE business_key=? AND url=?', (business, url))
            else:
                db.execute('INSERT OR REPLACE INTO page_feedback VALUES(?,?,?,?)', (business, url, verdict, now()))

    def override_feature(self, business, feature, state, note, trade, detected):
        with self.repository.connect() as db:
            if state == 'clear':
                db.execute('DELETE FROM feature_override WHERE business_key=? AND feature=?', (business, feature))
            else:
                db.execute('INSERT OR REPLACE INTO feature_override VALUES(?,?,?,?,?,?,?)', (business, feature, state, note, trade, detected, now()))

    def review_message(self, search_id, candidate_id, action, problem, text, template, ai_used):
        with self.repository.connect() as db:
            if action == 'clear':
                db.execute('DELETE FROM message_review WHERE search_id=? AND candidate_id=?', (search_id, candidate_id))
            else:
                db.execute('INSERT OR REPLACE INTO message_review VALUES(?,?,?,?,?,?,?,?)',
                           (search_id, candidate_id, action, problem, text, template, int(ai_used), now()))

    def corrections(self):
        with self.repository.connect() as db:
            return {'contacts': [dict(r) | {'source_hosts': json.loads(r['source_hosts'])} for r in db.execute('SELECT * FROM contact_correction')],
                    'features': [dict(r) for r in db.execute('SELECT * FROM feature_override')],
                    'messages': [dict(r) for r in db.execute('SELECT * FROM message_review')],
                    'pages': [dict(r) for r in db.execute('SELECT * FROM page_feedback')],
                    'rules': [dict(r) | {'evidence': json.loads(r['evidence_json']), 'preview': json.loads(r['preview_json'])}
                              for r in db.execute('SELECT * FROM learned_rule ORDER BY approved_at DESC')]}

    def save_rule(self, kind, value, description, evidence, preview):
        with self.repository.connect() as db:
            db.execute('INSERT INTO learned_rule VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(kind,value) DO UPDATE SET status=\'active\', '
                       'changed_at=excluded.changed_at, preview_json=excluded.preview_json, evidence_json=excluded.evidence_json',
                       (uid(), kind, value, description, 'active', json.dumps(evidence), json.dumps(preview), now(), now()))

    def set_rule(self, rule_id, status):
        with self.repository.connect() as db:
            if not db.execute('UPDATE learned_rule SET status=?, changed_at=? WHERE id=?', (status, now(), rule_id)).rowcount:
                raise ResearchError('Rule not found.', status=404)

    def site_analysis_replay(self, key, digest):
        with self.repository.connect() as db:
            row = db.execute('SELECT id,request_hash FROM site_analysis WHERE idempotency_key=?', (key,)).fetchone()
        if row and row['request_hash'] != digest:
            raise ResearchError('This analysis request key was used with different inputs.', status=409)
        return self.site_analysis(row['id']) if row else None

    def save_site_analysis(self, key, digest, payload, result):
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT id FROM site_analysis WHERE idempotency_key=?', (key,)).fetchone()
            if row:
                analysis_id = row['id']
            else:
                if db.execute('SELECT COUNT(*) FROM site_analysis').fetchone()[0] >= MAX_SEARCHES:
                    raise ResearchError('Saved website analysis limit reached (500). Delete old analyses.', status=429)
                analysis_id = uid()
                db.execute('INSERT INTO site_analysis VALUES(?,?,?,?,?,?)', (analysis_id, key, digest, now(), json.dumps(payload), json.dumps(result)))
        return self.site_analysis(analysis_id)

    def update_site_analysis(self, analysis_id, result):
        with self.repository.connect() as db:
            db.execute('UPDATE site_analysis SET result_json=? WHERE id=?', (json.dumps(result), analysis_id))
        return self.site_analysis(analysis_id)

    def site_analysis(self, analysis_id):
        with self.repository.connect() as db:
            row = db.execute('SELECT * FROM site_analysis WHERE id=?', (analysis_id,)).fetchone()
        if row is None:
            raise ResearchError('Website analysis not found.', status=404)
        result = json.loads(row['result_json'])
        ai = result.get('ai')
        if ai:
            ai['stale'] = ai['template_message'] != result['pitch_plan']['message']
        return {'id': row['id'], 'created_at': row['created_at'], 'input': json.loads(row['input_json'])} | result

    def site_analyses(self):
        with self.repository.connect() as db:
            rows = db.execute('SELECT id,created_at,input_json,result_json FROM site_analysis ORDER BY created_at DESC LIMIT 20').fetchall()
        items = []
        for row in rows:
            result = json.loads(row['result_json'])
            items.append({'id': row['id'], 'created_at': row['created_at'], 'url': result['url'], 'name': result['item']['name'],
                          'grade': (result.get('health') or {}).get('grade'), 'fit': result['pitch_plan']['fit'],
                          'offer': json.loads(row['input_json'])['offer']})
        return {'items': items}

    def delete_site_analysis(self, analysis_id):
        value = self.site_analysis(analysis_id)
        with self.repository.connect() as db:
            db.execute('DELETE FROM site_analysis WHERE id=?', (analysis_id,))
        return value

    def record_web_feedback(self, search_id, candidate_id, url, verdict):
        with self.repository.connect() as db:
            if verdict == 'clear':
                db.execute('DELETE FROM web_feedback WHERE search_id=? AND candidate_id=? AND url=?', (search_id, candidate_id, url))
            else:
                db.execute('INSERT OR REPLACE INTO web_feedback VALUES(?,?,?,?,?)', (search_id, candidate_id, url, verdict, now()))

    def offer_pack(self, search_id):
        with self.repository.connect() as db:
            row = db.execute('SELECT features_json FROM offer_pack WHERE search_id=?', (search_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_offer_pack(self, search_id, features):
        with self.repository.connect() as db:
            if features is None:
                db.execute('DELETE FROM offer_pack WHERE search_id=?', (search_id,))
            else:
                db.execute('INSERT OR REPLACE INTO offer_pack VALUES(?,?,?)', (search_id, json.dumps(features), now()))

    def record_enrichment(self, search_id, candidate_id, result):
        with self.repository.connect() as db:
            db.execute('INSERT OR REPLACE INTO prospect_enrichment VALUES(?,?,?,?)', (search_id, candidate_id, json.dumps(result), now()))

    def record_ai(self, search_id, candidate_id, result):
        # A new answer replaces the old one and its verdict (the verdict belonged to that answer).
        with self.repository.connect() as db:
            db.execute('INSERT OR REPLACE INTO prospect_ai VALUES(?,?,?,?,NULL,NULL,NULL)', (search_id, candidate_id, json.dumps(result), now()))

    def ai_verdict(self, search_id, candidate_id, verdict, note):
        with self.repository.connect() as db:
            changed = db.execute('UPDATE prospect_ai SET verdict=?,verdict_note=?,verdict_at=? WHERE search_id=? AND candidate_id=?',
                                 (verdict, note, now(), search_id, candidate_id)).rowcount
        if not changed:
            raise ResearchError('Run the AI analysis before giving a verdict.', status=404)

    def ai_verdicts(self):
        """Reviewed AI answers: the user-labelled data for future evaluation or training."""
        with self.repository.connect() as db:
            rows = db.execute('SELECT verdict,COUNT(*) FROM prospect_ai WHERE verdict IS NOT NULL GROUP BY verdict').fetchall()
            total = db.execute('SELECT COUNT(*) FROM prospect_ai').fetchone()[0]
        counts = {row[0]: row[1] for row in rows}
        return {'analysed': total, 'agree': counts.get('agree', 0), 'disagree': counts.get('disagree', 0)}

    def record_verification(self, search_id, candidate_id, probes):
        """Stores mailbox-check answers; the verification itself is recomputed from current evidence on every read."""
        with self.repository.connect() as db:
            row = db.execute('SELECT result_json FROM prospect_verification WHERE search_id=? AND candidate_id=?',
                             (search_id, candidate_id)).fetchone()
            kept = json.loads(row[0])['probes'] if row else {}
            db.execute('INSERT OR REPLACE INTO prospect_verification VALUES(?,?,?,?)',
                       (search_id, candidate_id, json.dumps({'probes': kept | probes}), now()))

    def record_market(self, search_id, result):
        with self.repository.connect() as db:
            db.execute('INSERT OR REPLACE INTO prospect_market VALUES(?,?,?)', (search_id, json.dumps(result), now()))

    def market(self, search_id):
        with self.repository.connect() as db:
            row = db.execute('SELECT result_json,created_at FROM prospect_market WHERE search_id=?', (search_id,)).fetchone()
        return json.loads(row[0]) | {'created_at': row[1]} if row else None

    def delete(self, search_id):
        with self.repository.connect() as db:
            db.execute('DELETE FROM prospect_search WHERE id=?', (search_id,))
        return {'deleted': True, 'research_preserved': True}
