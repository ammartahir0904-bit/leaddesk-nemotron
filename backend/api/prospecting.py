"""Product-led discovery: profile the user's offer, search OSM, check candidate websites."""
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.adapters.fetch import CrossHostRedirect, validate_url
from backend.adapters.osm import search_area
from backend.domain.contact_analysis import analyse_contacts, contact_points
from backend.domain.ai_analysis import (apply_verification, evidence_pack, ground, market_prompt, market_stats, parse as parse_ai,
                                        parse_market, prompt as ai_prompt, verify_prompt)
from backend.domain.identity import TRUSTED, cross_check
from backend.domain.offer_fit import FEATURE, check_polish, offer_fit, pitch, polish_prompt, polish_record, require_plan
from backend.domain.site_reader import advice
from backend.domain.contact_review import value_key
from backend.domain.lead_quality import report as quality_report
from backend.domain.rule_proposals import proposals as rule_proposals
from backend.domain.site_reader import read_site
from backend.domain.enrichment import classify, enrich, fallback_queries, queries, read_result_pages
from backend.domain.search_context import build as search_context
from backend.domain.places import from_overture, merge, opportunity
from backend.domain.verification import verify
from backend.domain.errors import ResearchError
from backend.domain.extract import EMAIL
from backend.domain.prospecting import (CATALOGUE, CATEGORIES, CURATED, MAX_CATEGORIES, OfferProfileInput, ProspectSearchInput,
                                        keyword_hits, nominatim_filters, overpass_query, own_website, profile_offer, rank,
                                        search_categories)
from backend.storage.repository import now, request_hash, uid


def analyse_all(candidates, country, mx):
    # Warm the MX cache in parallel; one DNS query per distinct email domain.
    domains = {e.rsplit('@', 1)[1].casefold() for c in candidates for e in (c['email'] or '').replace(';', ',').split(',') if '@' in e}
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(mx, sorted(domains)[:100]))
    for item in candidates:
        item['contact_analysis'] = analyse_contacts(item['email'], item['phone'], item['website'], country, mx)
        points, reasons = contact_points(item['contact_analysis'])
        item['priority_points'] += points
        item['priority_reasons'] += reasons
    candidates.sort(key=lambda item: (-(item.get('opportunity') or {}).get('score', 0), -item['priority_points'],
                                      item['name'].casefold(), item['id']))
    return candidates


class EnrichAll(BaseModel):
    model_config = ConfigDict(extra='forbid')
    limit: int = Field(default=10, ge=1, le=20)


class AnalyseAll(BaseModel):
    model_config = ConfigDict(extra='forbid')
    limit: int = Field(default=5, ge=1, le=10)


class ResearchAll(BaseModel):
    model_config = ConfigDict(extra='forbid')
    limit: int = Field(default=3, ge=1, le=10)
    include_ai: bool = True
    # Opening websites in Chrome on this computer loads their scripts and third-party files: explicit opt-in per request.
    render: bool = Field(default=False, strict=True)


class VerifyInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    # Asking a business's mail server about a mailbox contacts that server (no email is sent): explicit opt-in.
    check_mailboxes: bool = Field(default=False, strict=True)
    read_website: bool = True


class VerifyAll(VerifyInput):
    limit: int = Field(default=10, ge=1, le=20)


class CompareInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    limit: int = Field(default=3, ge=0, le=5)
    render: bool = Field(default=False, strict=True)


class OfferPackInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    # The features the user delivers; None restores the defaults for their offer.
    features: list[str] | None = Field(default=None, max_length=40)


class ContactCorrectionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['phone', 'email']
    value: str = Field(min_length=3, max_length=254)
    # wrong: hide it (with why); correct: approve it; added: a contact you know; clear: undo your correction.
    verdict: Literal['wrong', 'correct', 'added', 'clear']
    reason: Literal['not_theirs', 'disconnected', 'fake', 'temporary', 'confirmed', 'added'] = 'confirmed'


class FeatureOverrideInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    feature: str = Field(min_length=2, max_length=40)
    state: Literal['has', 'missing', 'clear']
    note: str = Field(default='', max_length=300)


class MessageReviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['approved', 'edited', 'rejected', 'clear']
    problem: Literal['wrong_fact', 'wrong_business', 'too_generic', 'tone'] | None = None
    text: str | None = Field(default=None, max_length=2000)


class RuleInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['block_email_domain', 'distrust_source_host', 'detector_off']
    value: str = Field(min_length=2, max_length=200)


class RuleStatusInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['active', 'off']


class SiteAnalysisInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(min_length=4, max_length=2048)
    offer: str = Field(min_length=3, max_length=2000)
    location: str = Field(default='', max_length=200)
    render: bool = Field(default=False, strict=True)


# schema.org types a site declares about itself -> the business type used for the feature checklist.
SCHEMA_TYPES = {'Restaurant': 'restaurant', 'FastFoodRestaurant': 'fast_food', 'CafeOrCoffeeShop': 'cafe', 'Bakery': 'bakery',
                'BarOrPub': 'bar', 'FoodEstablishment': 'restaurant', 'Dentist': 'dentist', 'MedicalClinic': 'clinic', 'Physician': 'clinic',
                'Pharmacy': 'pharmacy', 'RealEstateAgent': 'real_estate', 'HairSalon': 'beauty', 'BeautySalon': 'beauty', 'DaySpa': 'beauty',
                'NailSalon': 'beauty', 'HealthClub': 'fitness', 'ExerciseGym': 'fitness', 'Hotel': 'hotel', 'LodgingBusiness': 'hotel',
                'TravelAgency': 'travel', 'LegalService': 'lawyer', 'Attorney': 'lawyer', 'AccountingService': 'accountant',
                'School': 'education', 'EducationalOrganization': 'education', 'AutoRepair': 'car_services', 'ClothingStore': 'clothes',
                'Florist': 'florist', 'FurnitureStore': 'furniture', 'JewelryStore': 'jewelry', 'Electrician': 'trades', 'Plumber': 'trades',
                'HVACBusiness': 'trades', 'GeneralContractor': 'builder', 'InsuranceAgency': 'insurance'}


class VerdictInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    verdict: Literal['agree', 'disagree']
    note: str = Field(default='', max_length=500)


class CheckInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str | None = Field(default=None, max_length=2048)
    # True when the user typed this website for the business ("Add website"); otherwise only a website found for it.
    user_supplied: bool = False
    render: bool = Field(default=False, strict=True)


class WebFeedbackInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(min_length=8, max_length=2048)
    verdict: Literal['yes', 'no', 'clear']


def prospecting_router(prospects, osm, fetcher, research_website, authenticate, mx, web, ai=None, get_research=None, overture=None,
                       smtp=None, renderer=None):
    router = APIRouter(prefix='/v1/prospecting', dependencies=[Depends(authenticate)])
    busy = threading.Lock()

    def render_with(requested):
        """Chrome on this computer, only when the request asked for it and Chrome is installed."""
        if not requested or renderer is None or not renderer.status()['installed']:
            return None
        return lambda url, phone=False, screenshots=False: renderer.render(url, phone=phone, screenshots=screenshots)

    @router.get('/browser/status')
    def browser_status():
        return renderer.status() if renderer else {'installed': False, 'path': None, 'message': 'Chrome rendering is not configured.'}

    @router.get('/screens/{screen_id}')
    def screen(screen_id: str):
        """Temporary screenshot (kept 24 hours)."""
        path = renderer.screen_path(screen_id) if renderer else None
        if path is None:
            raise ResearchError('This screenshot has expired (kept 24 hours) or does not exist. Check the website again to take a new one.', status=404)
        return FileResponse(path, media_type='image/jpeg')

    def key_required(key):
        if not key or len(key) > 100:
            raise ResearchError('An Idempotency-Key of at most 100 characters is required.')

    @router.get('/categories')
    def categories():
        return {'items': [{'id': key, 'label': label, 'group': group, 'source': 'curated' if key in CURATED else 'osm_preset',
                           'osm_tags': [' + '.join(f'{k}={v}' for k, v in f.items()) for f in filters]}
                          for key, (label, group, filters) in CATEGORIES.items()],
                'max_selected': MAX_CATEGORIES, 'catalogue': {k: CATALOGUE[k] for k in ('source', 'licence', 'built', 'languages')}}

    @router.get('/categories/search')
    def category_search(q: str = Query(min_length=1, max_length=60)):
        return {'items': search_categories(q)}

    @router.post('/profile')
    def profile(payload: OfferProfileInput):
        page = fetcher(validate_url(payload.website)) if payload.website else None
        return profile_offer(payload.offer, page)

    @router.post('/searches')
    def search(payload: ProspectSearchInput, idempotency_key: str = Header(default='')):
        key_required(idempotency_key)
        cached, digest = prospects.replay(idempotency_key, payload)
        if cached:
            return cached
        if not busy.acquire(blocking=False):
            raise ResearchError('Another OpenStreetMap search is running. Retry shortly.', retryable=True, status=429)
        try:
            place = prospects.cached_place(payload.location)
            if place is None:
                place = osm.geocode(payload.location)
                prospects.cache_place(payload.location, place)
            area = search_area(place)
            query = overpass_query(area, payload.categories, payload.name_keyword, payload.limit)
            retrieved = now()
            kind = profile_offer(payload.offer)['offer_kind']
            notes, server, osm_items, counts = [], 'none', [], {}

            def search_osm():
                try:
                    return osm.overpass(query), None
                except ResearchError as failure:
                    if not failure.retryable:
                        raise
                    return (osm.nominatim_places(place, nominatim_filters(payload.categories), payload.name_keyword, payload.limit),
                            'nominatim (fallback: Overpass busy)'), 'busy'

            def search_overture():
                if overture is None:
                    raise ResearchError('Overture Maps is not available in this installation.', status=503)
                south, north, west, east = place['boundingbox'] or [place['lat']] * 2 + [place['lon']] * 2
                return overture.area(south, north, west, east)

            # Both public sources run at the same time; Overture failing is fatal only when it was the sole source.
            with ThreadPoolExecutor(max_workers=2) as pool:
                osm_job = pool.submit(search_osm)
                overture_job = pool.submit(search_overture) if payload.use_overture else None
                try:
                    (elements, server), busy_note = osm_job.result()
                    if busy_note:
                        notes.append('Overpass was busy, so OpenStreetMap results came from Nominatim search: at most 40 per business type, '
                                     'ordered by relevance rather than completeness.')
                    osm_items, counts = rank(elements, kind, payload.categories, 300, retrieved)
                except ResearchError as failure:
                    if not payload.use_overture:
                        raise
                    notes.append(f'OpenStreetMap could not be searched ({failure}). Results come from Overture Maps only.')
                overture_result = overture_job.result() if overture_job else None
            sources = {'openstreetmap': {'server': server, 'businesses': len(osm_items)}}
            items = [dict(item, sources=['OpenStreetMap'], field_sources={}) for item in osm_items]
            if overture_result:
                rows, meta = overture_result
                found, overture_counts = from_overture(rows, meta['release'], payload.categories, payload.name_keyword)
                items, merge_counts = merge(osm_items, found)
                counts = counts | overture_counts | merge_counts
                sources['overture'] = meta | {'businesses': len(found)}
                notes.append(f"Overture Maps release {meta['release']} ({'from the local cache' if meta['cached'] else 'downloaded'} "
                             f"in {meta['seconds']} s): {len(found)} matching businesses in a "
                             f"{meta['box']['north'] - meta['box']['south']:.2f}° × {meta['box']['east'] - meta['box']['west']:.2f}° box. "
                             'Overture combines Meta, Microsoft, Foursquare and other sources; details may be outdated.')
                if meta['truncated']:
                    notes.append('The area is very dense; only the first 60,000 places were read. Use a smaller area.')
            for item in items:
                item['opportunity'] = opportunity(item, kind)
            items.sort(key=lambda c: (-c['opportunity']['score'], -c['priority_points'], c['name'].casefold(), c['id']))
            counts = counts | {'kept': min(len(items), payload.limit), 'over_limit': max(0, len(items) - payload.limit)}
            counts.setdefault('returned_elements', 0)
            counts.setdefault('unnamed_skipped', 0)
            candidates = analyse_all(items[:payload.limit], place.get('country_code'), mx)
            result = {'place': place, 'search_area': {'mode': area[0], 'radius_m': area[3] if area[0] == 'around' else None},
                      'offer_kind': kind, 'candidates': candidates, 'counts': counts, 'retrieved_at': retrieved,
                      'query': query, 'overpass_server': server, 'sources': sources,
                      'method': 'osm_overture_v2' if payload.use_overture else 'osm_overpass_v1',
                      'coverage': ['Map data is collected by volunteers and companies. Some real businesses are missing, and '
                                   'websites, phones and emails may be absent or outdated.',
                                   'The opportunity score is transparent points from public data, not a probability of buying.',
                                   'Need and budget are not established until you check the business and talk to them.', *notes]}
            return prospects.save(idempotency_key, digest, payload, result)
        finally:
            busy.release()

    @router.get('/searches')
    def searches(offset: int = Query(default=0, ge=0, le=100000)):
        return prospects.recent(offset)

    @router.get('/searches/{search_id}')
    def get(search_id: str):
        return prospects.get(search_id)

    @router.delete('/searches/{search_id}')
    def delete(search_id: str):
        if renderer:
            try:
                search = prospects.get(search_id)
                renderer.delete_screens([v for c in search['candidates'] for k, v in
                                         (((c.get('check') or {}).get('site') or {}).get('layout') or {}).get('screens', {}).items()
                                         if k in {'desktop', 'phone'} and v])
            except ResearchError:
                pass
        return prospects.delete(search_id)

    class ProviderInput(BaseModel):
        model_config = ConfigDict(extra='forbid')
        provider: Literal['searxng', 'tavily']

    @router.post('/web-search/provider')
    def web_provider(payload: ProviderInput):
        """Turn Tavily on (explicit opt-in: queries go to Tavily) or back to local SearXNG."""
        if not hasattr(web, 'choose'):
            raise ResearchError('This search engine cannot be switched.', status=409)
        return web.choose(payload.provider)

    @router.get('/web-search/status')
    def web_status():
        return web.status()

    def enrich_one(search, item):
        found, seen = [], set()
        context = search_context(item, search['input']['location'], search['place'])
        listed = own_website(item)
        asked = queries(item['name'], search['input']['location'], context['category_word'], context['city'],
                        urlsplit(listed).hostname.removeprefix('www.') if listed else None)
        failures, blocked, engines = [], {}, {}

        def run(batch):
            for query in batch:
                try:
                    rows = web.search(query, limit=10)
                except ResearchError as error:
                    if not found and query == asked[-1]:
                        raise
                    failures.append({'query': query, 'message': str(error)})
                    continue
                for engine, reason in getattr(web, 'last_unresponsive', []):
                    blocked[engine] = reason
                for row in rows:
                    engines[row.get('engine') or 'unknown'] = engines.get(row.get('engine') or 'unknown', 0) + 1
                    if row['url'] not in seen:
                        seen.add(row['url'])
                        found.append(row)

        run(asked)
        if not found and blocked:
            # Every engine refused: saving "nothing found" would be wrong. Nothing is saved; the user retries later.
            raise ResearchError('The search engines are blocking automated searches right now (' +
                                '; '.join(f'{e}: {r}' for e, r in sorted(blocked.items())) + '). Nothing was saved; retry in about an hour.',
                                retryable=True, status=429)
        value = enrich(item['name'], item['website'], found, context)
        known_social = {p['platform'] for p in value['social_pages']} | {s['platform'] for s in item.get('site_socials') or []}
        if not {'Instagram', 'Facebook'} & known_social:
            # No profile yet: search without the city and by likely handles (the same context and handle checks apply).
            extra = fallback_queries(item['name'], context)
            asked += extra
            run(extra)
            value = enrich(item['name'], item['website'], found, context)
        result = read_result_pages(item['name'], value, lambda url: fetcher(validate_url(url)))
        result['engine_report'] = {'results_by_engine': engines, 'blocked': [{'engine': e, 'reason': r} for e, r in sorted(blocked.items())],
                                   'complete': not blocked}
        if blocked:
            result['notes'].insert(0, 'Some search engines were blocking automated searches (' + ', '.join(sorted(blocked)) +
                                   '), so results may be incomplete. "Not found" here does not mean they have none; search again later.')
        result['context'] = {k: context[k] for k in ('city', 'category_word', 'location_labels', 'category_labels', 'region')}
        if failures:
            result['query_failures'] = failures
        country = search['place'].get('country_code')
        for contact in result['contacts']:
            contact['analysis'] = analyse_contacts(contact['value'] if contact['type'] == 'email' else None,
                                                   contact['value'] if contact['type'] == 'phone' else None,
                                                   item['website'] or (result['website_candidates'][0]['url'] if result['website_candidates'] else None),
                                                   country, mx)['items'][0]
        result['queries'] = asked
        prospects.record_enrichment(search['id'], item['id'], result)
        return result

    @router.post('/searches/{search_id}/candidates/{kind}/{ident}/web-feedback')
    def web_feedback(search_id: str, kind: str, ident: str, payload: WebFeedbackInput):
        """"Is this them?": confirm or reject a page found online. Applies to this business at once; 'clear' undoes it."""
        search, item = prospects.candidate(search_id, f'{kind}/{ident}')
        known = {r['url'] for r in (item['enrichment'] or {}).get('results', [])} | {s['url'] for s in item.get('site_socials') or []}
        if payload.url not in known:
            raise ResearchError('That page was not found for this business.', status=404)
        prospects.record_web_feedback(search_id, item['id'], payload.url, payload.verdict)
        prospects.page_answer(item['business_key'], payload.url, payload.verdict)  # also in future searches of this business
        return prospects.candidate(search_id, item['id'])[1]

    @router.post('/searches/{search_id}/candidates/{kind}/{ident}/enrich')
    def enrich_candidate(search_id: str, kind: str, ident: str):
        search, item = prospects.candidate(search_id, f'{kind}/{ident}')
        return enrich_one(search, item)

    @router.post('/searches/{search_id}/enrich')
    def enrich_top(search_id: str, payload: EnrichAll):
        # Sequential and bounded: at most 20 businesses, two queries each.
        search = prospects.get(search_id)
        todo = [c for c in search['candidates'] if not c['enrichment']][:payload.limit]
        done = 0
        for item in todo:
            enrich_one(search, item)
            done += 1
        return {'enriched': done, 'remaining': max(0, len([c for c in search['candidates'] if not c['enrichment']]) - done)}

    def analyse_one(search, item):
        """Rules first: LeadDesk writes the message from its checks; the local model may only reword it (checked, else kept)."""
        plan = item['pitch_plan']
        require_plan(plan)
        if ai is None:
            raise ResearchError('Choose an installed Ollama model in "AI models and hardware" first.', status=409)
        offer = search['input']['offer']
        run = ai.run(polish_prompt(item, offer, plan), max_tokens=300)
        message, problems = check_polish(run['text'], item, offer, plan)
        if message is None and any('format' in p for p in problems):
            # Small local models sometimes break the format; one retry.
            run = ai.run(polish_prompt(item, offer, plan) + '\nReturn only valid JSON: {"message": "..."}', max_tokens=300)
            message, problems = check_polish(run['text'], item, offer, plan)
        result = polish_record(run, plan, message, problems)
        prospects.record_ai(search['id'], item['id'], result)
        return result

    @router.post('/searches/{search_id}/candidates/{kind}/{ident}/analyse')
    def analyse_candidate(search_id: str, kind: str, ident: str):
        search, item = prospects.candidate(search_id, f'{kind}/{ident}')
        return analyse_one(search, item)

    @router.post('/searches/{search_id}/analyse')
    def analyse_top(search_id: str, payload: AnalyseAll):
        search = prospects.get(search_id)
        # Only businesses with a message to reword, and not already reworded with the current method.
        todo = [c for c in search['candidates'] if (c['ai'] or {}).get('method') != 'ollama_pitch_polish_v1'
                and c['pitch_plan']['opening']][:payload.limit]
        done, failed = 0, []
        for item in todo:
            try:
                analyse_one(search, item)
                done += 1
            except ResearchError as error:
                if not error.retryable:
                    raise
                failed.append({'name': item['name'], 'message': str(error)})
        return {'analysed': done, 'failed': failed}

    @router.post('/site-analyses')
    def site_analysis(payload: SiteAnalysisInput, idempotency_key: str = Header(default='')):
        """Analyse any business website the user enters: layout, features vs. their offer, contacts and a rules-first pitch."""
        key_required(idempotency_key)
        replay = prospects.site_analysis_replay(idempotency_key, request_hash({'operation': 'site_analysis', 'input': payload.model_dump()}))
        if replay:
            return replay
        url = payload.url.strip()
        url = validate_url(url if '://' in url else 'https://' + url)
        if classify(url)[0] != 'website':
            raise ResearchError('That is a social, directory or link page, not a business website. LeadDesk links those but does not read them.', status=409)
        try:
            page, record, site, profile, hits = read_website(url, payload.offer, payload.location, f'site-{idempotency_key}', payload.render)
        except ResearchError as error:
            why = advice(str(error))
            raise ResearchError(f"{why['reason']} {why['next_step']} ({error})", retryable=error.retryable, status=error.status) from None
        site.pop('address_text')
        item = standalone_item(site, page.url, payload.offer)
        item['check'] = {'site': site, 'identity': None}
        fit = offer_fit(item, payload.offer, profile['offer_kind'], 'ok')
        plan = pitch(item, payload.offer, fit, payload.location, 'ok')
        analysed = [analyse_contacts(c['value'] if c['type'] == 'email' else None, c['value'] if c['type'] in {'phone', 'whatsapp'} else None,
                                     page.url, None, mx)['items'][0] | {'page_url': c['page_url'], 'page_kind': c['page_kind']}
                    for c in site['contacts'][:20] if c['type'] in {'email', 'phone', 'whatsapp'}]
        item.pop('check')
        result = {'url': page.url, 'requested_url': url, 'item': item, 'site': site, 'health': site['health'], 'offer_fit': fit,
                  'pitch_plan': plan, 'contact_analysis': analysed, 'research_id': record['id'], 'offer_keywords_found': hits,
                  'offer_kind': profile['offer_kind'], 'method': 'site_analysis_v1'}
        return prospects.save_site_analysis(idempotency_key, request_hash({'operation': 'site_analysis', 'input': payload.model_dump()}),
                                            payload.model_dump(), result)

    @router.get('/site-analyses')
    def site_analyses():
        return prospects.site_analyses()

    @router.get('/site-analyses/{analysis_id}')
    def get_site_analysis(analysis_id: str):
        return prospects.site_analysis(analysis_id)

    @router.delete('/site-analyses/{analysis_id}')
    def delete_site_analysis(analysis_id: str):
        value = prospects.delete_site_analysis(analysis_id)
        if renderer:
            renderer.delete_screens([v for k, v in ((value.get('site') or {}).get('layout') or {}).get('screens', {}).items()
                                     if k in {'desktop', 'phone'} and v])
        return {'deleted': True, 'research_preserved': True}

    @router.post('/site-analyses/{analysis_id}/polish')
    def polish_site_analysis(analysis_id: str):
        """The local model may reword the message; LeadDesk checks every word and keeps its own wording otherwise."""
        value = prospects.site_analysis(analysis_id)
        plan, item, offer = value['pitch_plan'], value['item'], value['input']['offer']
        require_plan(plan)
        if ai is None:
            raise ResearchError('Choose an installed Ollama model in "AI models and hardware" first.', status=409)
        run = ai.run(polish_prompt(item, offer, plan), max_tokens=300)
        message, problems = check_polish(run['text'], item, offer, plan)
        if message is None and any('format' in p for p in problems):
            run = ai.run(polish_prompt(item, offer, plan) + '\nReturn only valid JSON: {"message": "..."}', max_tokens=300)
            message, problems = check_polish(run['text'], item, offer, plan)
        stored = {k: v for k, v in value.items() if k not in {'id', 'created_at', 'input'}}
        return prospects.update_site_analysis(analysis_id, stored | {'ai': polish_record(run, plan, message, problems)})

    @router.post('/searches/{search_id}/candidates/{kind}/{ident}/contact-correction')
    def contact_correction(search_id: str, kind: str, ident: str, payload: ContactCorrectionInput):
        """Mark a contact wrong (with why), confirm it, or add the right one. Applies to this business in every search."""
        search, item = prospects.candidate(search_id, f'{kind}/{ident}')
        country = search['place'].get('country_code')
        value = payload.value.strip()
        if payload.verdict == 'added':
            valid = value_key('phone', value, country).startswith('+') if payload.type == 'phone' else bool(EMAIL.fullmatch(value))
            if not valid:
                raise ResearchError('That does not look like a valid ' + ('phone number for this country.' if payload.type == 'phone' else 'email address.'), status=422)
        elif payload.verdict != 'clear':
            known = {(c['type'], c['key']) for c in item['contact_review']['contacts']}
            if (payload.type, value_key(payload.type, value, country)) not in known:
                raise ResearchError('That contact is not listed for this business.', status=404)
        if payload.verdict == 'wrong' and payload.reason in {'confirmed', 'added'}:
            raise ResearchError('Say why it is wrong: not theirs, disconnected, fake or temporary.', status=422)
        hosts = next((c['source_hosts'] for c in item['contact_review']['contacts']
                      if c['type'] == payload.type and c['key'] == value_key(payload.type, value, country)), [])
        reason = {'correct': 'confirmed', 'added': 'added'}.get(payload.verdict, payload.reason)
        prospects.correct_contact(search_id, item, payload.type, value, payload.verdict, reason, country, hosts)
        return prospects.candidate(search_id, item['id'])[1]

    @router.post('/searches/{search_id}/candidates/{kind}/{ident}/feature-override')
    def feature_override(search_id: str, kind: str, ident: str, payload: FeatureOverrideInput):
        """"Actually they have it / don't": replaces what LeadDesk detected for this business; the pitch is rebuilt at once."""
        search, item = prospects.candidate(search_id, f'{kind}/{ident}')
        row = next((f for f in item['offer_fit']['features'] if f['id'] == payload.feature), None)
        if row is None:
            raise ResearchError('That feature is not in this comparison.', status=404)
        prospects.override_feature(item['business_key'], payload.feature, payload.state, payload.note.strip(),
                                   item['offer_fit']['trade'], row['detected_state'])
        return prospects.candidate(search_id, item['id'])[1]

    @router.post('/searches/{search_id}/candidates/{kind}/{ident}/message-review')
    def message_review(search_id: str, kind: str, ident: str, payload: MessageReviewInput):
        """Approve the message, save your edited version, or reject it with what was wrong."""
        search, item = prospects.candidate(search_id, f'{kind}/{ident}')
        plan = item['pitch_plan']
        if payload.action == 'edited' and not (payload.text or '').strip():
            raise ResearchError('Write the message you want to use.', status=422)
        if payload.action == 'rejected' and not payload.problem:
            raise ResearchError('Say what was wrong so LeadDesk can count it.', status=422)
        ai = item.get('ai') or {}
        ai_used = ai.get('method') == 'ollama_pitch_polish_v1' and ai.get('accepted') and not ai.get('stale')
        prospects.review_message(search_id, item['id'], payload.action, payload.problem,
                                 (payload.text or '').strip() or None, plan['message'], ai_used)
        return prospects.candidate(search_id, item['id'])[1]

    @router.get('/quality-report')
    def quality():
        return quality_report(prospects.all_searches(), prospects.corrections())

    @router.get('/rules')
    def rules():
        corrections = prospects.corrections()
        items = [i for s in prospects.all_searches() for i in s['candidates']]
        active = {(r['kind'], r['value']) for r in corrections['rules'] if r['status'] == 'active'}
        return {'rules': corrections['rules']} | rule_proposals(corrections, items, active)

    @router.post('/rules')
    def approve_rule(payload: RuleInput):
        """Approve one current proposal. Only proposals LeadDesk made from your corrections can be approved."""
        corrections = prospects.corrections()
        items = [i for s in prospects.all_searches() for i in s['candidates']]
        active = {(r['kind'], r['value']) for r in corrections['rules'] if r['status'] == 'active'}
        found = next((p for p in rule_proposals(corrections, items, active)['proposals']
                      if p['kind'] == payload.kind and p['value'] == payload.value), None)
        if found is None:
            raise ResearchError('That rule is not a current proposal. Rules come from 3 or more of your corrections.', status=409)
        prospects.save_rule(found['kind'], found['value'], found['description'], found['evidence'], found['preview'])
        return rules()

    @router.post('/rules/{rule_id}')
    def rule_status(rule_id: str, payload: RuleStatusInput):
        prospects.set_rule(rule_id, payload.status)
        return rules()

    @router.post('/searches/{search_id}/offer-pack')
    def offer_pack(search_id: str, payload: OfferPackInput):
        """Which features the user delivers in this search; the comparison and pitch follow at once."""
        prospects.get(search_id)
        if payload.features is not None:
            unknown = sorted(set(payload.features) - set(FEATURE))
            if unknown:
                raise ResearchError(f"Unknown features: {', '.join(unknown)}.", status=422)
        prospects.save_offer_pack(search_id, sorted(set(payload.features)) if payload.features is not None else None)
        return prospects.get(search_id)

    @router.post('/searches/{search_id}/candidates/{kind}/{ident}/ai-verdict')
    def verdict(search_id: str, kind: str, ident: str, payload: VerdictInput):
        prospects.ai_verdict(search_id, f'{kind}/{ident}', payload.verdict, payload.note)
        return prospects.ai_verdicts()

    def load_home(url):
        """Fetch a website's home page: HTTPS first, one recorded hop for a forwarding address. Raises ResearchError."""
        page, https_note, started, redirected = None, None, time.monotonic(), None
        if url.startswith('http://'):
            try:
                page = fetcher(validate_url('https://' + url[7:]))
            except ResearchError:
                https_note = 'The HTTPS address could not be loaded, so the site was read over plain HTTP.'
        try:
            if page is None:
                started = time.monotonic()
                page = fetcher(validate_url(url))
        except CrossHostRedirect as error:
            # brand.com -> www.brand.com or brand.pk: follow this one hop for the business's own address and record it.
            # The new site is fetched with its own robots policy, and the identity cross-check still compares it.
            redirected = {'from': url, 'to': error.location}
            started = time.monotonic()
            page = fetcher(validate_url(error.location))
        except ResearchError as error:
            parts = urlsplit(url)
            if 'redirects to another host' not in str(error) or (parts.hostname or '').startswith('www.'):
                raise
            # example.com -> www.example.com is the same site; read the www address directly.
            started = time.monotonic()
            page = fetcher(validate_url(urlunsplit(('https', 'www.' + parts.netloc, parts.path, parts.query, ''))))
        return page, round(time.monotonic() - started, 2), https_note, redirected  # seconds include the robots.txt request

    def read_website(url, offer, location, key, render):
        """Load and read a website deeply (home, Contact/About/offer/reviews/gallery/team pages, structured data, layout)."""
        page, home_seconds, https_note, redirected = load_home(url)
        record = research_website(page.url, offer, location, key, page)
        profile = profile_offer(offer)
        site = read_site(page, lambda link: fetcher(validate_url(link)), offer, profile['offer_kind'], int(now()[:4]),
                         requested_url=url, location=location, home_seconds=home_seconds, render=render_with(render))
        if https_note:
            site['notes'].append(https_note)
        if redirected:
            site['notes'].append(f"{redirected['from']} forwards to {redirected['to']}; that site was read. Check the identity cross-check.")
            site['cross_host_redirect'] = redirected
        discard = site['reading'].pop('discard_screens', [])
        if discard and renderer:
            renderer.delete_screens(discard)  # screenshots of a bot-check page show nothing about the site
        texts = [record.get('canonical_name') or ''] + [e['excerpt'] for e in record['evidence']] + [e['text'] for e in site['excerpts']]
        return page, record, site, profile, keyword_hits(profile['keywords'], texts)

    def unreachable(error):
        return error.status in {502, 504} or re.match(r'The website returned HTTP (404|410|5\d\d)', str(error))

    def standalone_item(site, url, offer):
        """A business record built only from what its own website says, for a URL the user typed."""
        names = site['names']
        title = re.split(r' \| | - | – |: ', names['title'] or '')[0].strip()
        name = (names['structured'] or [None])[0] or names['site_name'] or names['heading'] or title or urlsplit(url).hostname
        types = [t for s in site['structured'] for t in s['types']]
        category = next((SCHEMA_TYPES[t] for t in types if t in SCHEMA_TYPES), None)
        how = f"schema.org type {next(t for t in types if t in SCHEMA_TYPES)}" if category else None
        if category is None:
            suggested = profile_offer(offer)['suggested_categories']
            category = suggested[0] if suggested else None
            how = 'suggested from your product' if category else 'unknown'
        label = CATEGORIES[category][0] if category in CATEGORIES else 'Named business'
        phones = [c['value'] for c in site['contacts'] if c['type'] in {'phone', 'whatsapp'}]
        emails = [c['value'] for c in site['contacts'] if c['type'] == 'email']
        return {'id': 'site/' + (urlsplit(url).hostname or 'site'), 'name': name[:200], 'category': category, 'category_label': label,
                'category_source': how, 'address': None, 'phone': phones[0] if phones else None, 'email': emails[0] if emails else None,
                'website': url, 'website_is_social': False, 'socials': site['social_links'][:10],
                'evidence': {'source': 'Their website', 'url': url}}

    def check_one(search, item, url, key, source=None, render=False):
        """Read the website deeply, then cross-check identity with the map entry.

        source: 'user_supplied' (typed with "Add website"), 'found_online' or None for the listed website."""
        try:
            page, record, site, profile, hits = read_website(url, search['input']['offer'], search['input']['location'], key, render)
        except ResearchError as error:
            if not unreachable(error):
                raise
            # A listed website that does not load is itself a finding (it may be down or expired).
            result = {'contacts_found': 0, 'contact_analysis': [], 'site': None, 'identity': None, 'offer_keywords_found': [],
                      'website_url': url, 'website_source': source or ('listed' if url == own_website(item) else 'found_online'),
                      'unreachable': {'url': url, 'message': str(error), 'retryable': error.retryable},
                      'relevance_note': 'Their listed website could not be loaded. It may be down, expired or temporarily unavailable; retry later to confirm.'}
            prospects.record_check(search['id'], item['id'], '', result)  # no research record: nothing was read
            return {'research': None, 'check': result | {'research_id': None}}
        identity = cross_check(item | {'website': own_website(item)}, site, item['enrichment'], search['input']['location'])
        site.pop('address_text')
        country = search['place'].get('country_code')
        analysed = [analyse_contacts(c['value'] if c['type'] == 'email' else None, c['value'] if c['type'] in {'phone', 'whatsapp'} else None,
                                     page.url, country, mx)['items'][0] | {'page_url': c['page_url'], 'page_kind': c['page_kind']}
                    for c in site['contacts'][:20] if c['type'] in {'email', 'phone', 'whatsapp'}]
        pages = len([p for p in site['pages'] if p['status'] == 'read'])
        result = {'website_url': url, 'website_source': source or ('listed' if url == own_website(item) else 'found_online'),
                  'contacts_found': len(site['contacts']), 'contact_analysis': analysed, 'offer_keywords_checked': profile['keywords'],
                  'offer_keywords_found': hits, 'site': site, 'identity': identity, 'health': site['health'],
                  'relevance_note': (f'The {pages} pages read mention your offer terms: ' + ', '.join(hits) + '. They may already have or sell something similar, or need it; review the evidence.')
                  if hits else f'No offer terms found on the {pages} pages read. That does not prove they lack it.'}
        prospects.record_check(search['id'], item['id'], record['id'], result)
        return {'research': record, 'check': result | {'research_id': record['id']}}

    def verify_one(search, item, payload):
        """Read their website if needed (confirms contacts shown there), then optionally ask mail servers about each email."""
        steps = []
        url = own_website(item)
        if payload.read_website and url and not item['check']:
            try:
                check_one(search, item, url, f'verify-{uid()}')
                steps.append({'step': 'read_website', 'status': 'done'})
            except ResearchError as error:
                steps.append({'step': 'read_website', 'status': 'failed', 'message': str(error)})
            search, item = prospects.candidate(search['id'], item['id'])
        probes = {}
        if payload.check_mailboxes:
            if smtp is None:
                raise ResearchError('Mailbox checks are not available in this installation.', status=503)
            current = verify(item, search['place'].get('country_code'))
            for contact in [c for c in current['contacts'] if c['type'] == 'email'][:5]:
                probes[contact['value'].casefold()] = smtp.check(contact['value'])
            steps.append({'step': 'mailbox_check', 'status': 'done', 'checked': len(probes)})
        prospects.record_verification(search['id'], item['id'], probes)
        search, item = prospects.candidate(search['id'], item['id'])
        return {'verification': item['verification'], 'steps': steps}

    @router.post('/searches/{search_id}/candidates/{kind}/{ident}/verify')
    def verify_candidate(search_id: str, kind: str, ident: str, payload: VerifyInput | None = None):
        search, item = prospects.candidate(search_id, f'{kind}/{ident}')
        return verify_one(search, item, payload or VerifyInput())

    @router.post('/searches/{search_id}/verify')
    def verify_top(search_id: str, payload: VerifyAll):
        search = prospects.get(search_id)
        todo = [c for c in search['candidates'] if not c['verification']][:payload.limit]
        for item in todo:
            verify_one(search, item, payload)
        left = len([c for c in prospects.get(search_id)['candidates'] if not c['verification']])
        return {'verified': len(todo), 'remaining': left}

    @router.post('/searches/{search_id}/candidates/{kind}/{ident}/compare')
    def compare_candidate(search_id: str, kind: str, ident: str, payload: CompareInput | None = None):
        """Read the websites of the nearest competitors (bounded) so the comparison rests on what their sites show."""
        payload = payload or CompareInput()
        search, item = prospects.candidate(search_id, f'{kind}/{ident}')
        if item['competitors'] is None:
            return {'competitors': None, 'steps': [], 'message': 'No business of the same type within 3 km in this search.'}
        steps = []
        todo = ([item['id']] if own_website(item) and not item['check'] else []) + item['competitors']['unchecked_websites'][:payload.limit]
        for other_id in todo:
            _, other = prospects.candidate(search_id, other_id)
            try:
                done = check_one(search, other, own_website(other), f'compare-{uid()}', render=payload.render)['check']
                down = done.get('unreachable')
                steps.append({'id': other_id, 'name': other['name'], 'status': 'unreachable' if down else 'read'}
                             | ({'message': down['message']} if down else {}))
            except ResearchError as error:
                steps.append({'id': other_id, 'name': other['name'], 'status': 'failed', 'message': str(error)})
        search, item = prospects.candidate(search_id, f'{kind}/{ident}')
        return {'competitors': item['competitors'], 'steps': steps}

    @router.post('/searches/{search_id}/candidates/{kind}/{ident}/check')
    def check(search_id: str, kind: str, ident: str, payload: CheckInput | None = None, idempotency_key: str = Header(default='')):
        key_required(idempotency_key)
        search, item = prospects.candidate(search_id, f'{kind}/{ident}')
        url = own_website(item)
        if payload and payload.url and payload.user_supplied:
            # The user typed this website for the business. It is read like any other; the identity cross-check
            # still compares it with the map entry and shows any mismatch.
            if classify(payload.url)[0] != 'website':
                raise ResearchError('That is a social, directory or link page, not their own website. LeadDesk links those but does not read them.', status=409)
            url = validate_url(payload.url if '://' in payload.url else 'https://' + payload.url)
        elif payload and payload.url:
            # Otherwise only a website already found for this business, never an arbitrary URL.
            allowed = {w['url'] for w in (item['enrichment'] or {}).get('website_candidates', [])}
            if payload.url not in allowed:
                raise ResearchError('Choose a website found for this business, or enter it with "Add website".', status=409)
            url = payload.url
        if not url:
            listed = ' The listed address is a social or directory page, which LeadDesk links but does not read.' if item['website'] else ''
            raise ResearchError('No own website is listed for this business.' + listed + ' Use "Find online" to search for one.', status=409)
        return check_one(search, item, url, idempotency_key, 'user_supplied' if payload and payload.user_supplied else None,
                         render=bool(payload and payload.render))

    @router.post('/searches/{search_id}/research')
    def research_top(search_id: str, payload: ResearchAll):
        """Fixed research sequence per business: find online -> read website -> AI analysis. Each step is a typed tool."""
        search = prospects.get(search_id)
        web_ready = bool(web.status().get('json_enabled'))
        ai_state = ai.status() if payload.include_ai and ai is not None else None
        ai_ready = bool(ai_state and ai_state['ready'])
        warnings = []
        if not web_ready:
            warnings.append('Find online was skipped. Start the local search engine with scripts/searxng.sh start, then refresh.')
        if payload.include_ai and not ai_ready:
            warnings.append((ai_state or {}).get('problem') or 'AI analysis was skipped. Choose an installed model in "AI models and hardware".')
        todo = [c for c in search['candidates'] if not c['check'] or (ai_ready and not c['ai'])][:payload.limit]
        report = []
        for first in todo:
            steps = []

            def step(name, action):
                try:
                    action()
                    steps.append({'step': name, 'status': 'done'})
                except ResearchError as error:
                    steps.append({'step': name, 'status': 'failed', 'message': str(error)})

            search, item = prospects.candidate(search_id, first['id'])
            if item['enrichment'] is None:
                if web_ready:
                    step('find_online', lambda: enrich_one(search, item))
                    search, item = prospects.candidate(search_id, item['id'])
                else:
                    steps.append({'step': 'find_online', 'status': 'skipped', 'message': 'Local web search is not running.'})
            # Automation only uses a found website whose name fully matches; partial matches need your click.
            url = own_website(item) or next((w['url'] for w in (item['enrichment'] or {}).get('website_candidates', [])
                                           if w['name_match'] == 'strong'), None)
            if item['check']:
                steps.append({'step': 'read_website', 'status': 'skipped', 'message': 'Already checked.'})
            elif url:
                step('read_website', lambda: check_one(search, item, url, uid(), render=payload.render))
                search, item = prospects.candidate(search_id, item['id'])
            else:
                steps.append({'step': 'read_website', 'status': 'skipped', 'message': 'No website listed or found with a fully matching name.'})
            if ai_ready and not item['ai'] and item['pitch_plan']['opening']:
                step('ai_analysis', lambda: analyse_one(search, item))
            elif payload.include_ai and not ai_ready and not item['ai']:
                steps.append({'step': 'ai_analysis', 'status': 'skipped', 'message': warnings[-1]})
            report.append({'id': item['id'], 'name': item['name'], 'steps': steps})
        return {'researched': len(report), 'items': report, 'web_search': web_ready, 'ai': ai_ready, 'warnings': warnings}

    @router.get('/searches/{search_id}/market')
    def market(search_id: str):
        return {'stats': market_stats(prospects.get(search_id)), 'ai': prospects.market(search_id)}

    @router.post('/searches/{search_id}/market')
    def market_ai(search_id: str):
        search = prospects.get(search_id)
        stats = market_stats(search)
        if not stats['items'] and not stats['needs']:
            raise ResearchError('Find online, check websites or run AI analysis for some businesses first.', status=409)
        if ai is None:
            raise ResearchError('Choose an installed Ollama model in "AI models and hardware" first.', status=409)
        text = market_prompt(search['input']['offer'], search['input']['location'], stats)
        run = ai.run(text, max_tokens=900)
        try:
            parsed = parse_market(run['text'], stats)
        except ResearchError:
            run = ai.run(text + '\nReturn only valid JSON with exactly the requested keys.', max_tokens=900)
            parsed = parse_market(run['text'], stats)
        result = parsed | {'stats': stats, 'model': run['model'], 'model_digest': run['model_digest'], 'seconds': run['seconds'],
                           'status': 'proposal', 'method': 'ollama_market_problems_v1'}
        prospects.record_market(search_id, result)
        return prospects.market(search_id)

    return router
