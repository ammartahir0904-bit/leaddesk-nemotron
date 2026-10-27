"""Website health report card from fixture pages; no network."""
import unittest

from backend.adapters.fetch import Page
from backend.domain.errors import ResearchError
from backend.domain.site_reader import read_site

OLD = ('<html><head><title>Home</title><meta name="generator" content="WordPress 4.9.8">'
       '<script src="http://old.example/js/jquery-1.12.4.min.js"></script></head><body>'
       '<table><tr><td><font>Welcome to Fictional Realty</font></td></tr></table><table></table><table></table><table></table>'
       '<img src="a.jpg"><img src="b.jpg"><img src="c.jpg"><p>© 2015 Fictional Realty</p></body></html>')
GOOD = ('<!DOCTYPE html><html><head><title>Fictional Realty | Homes in Lahore</title>'
        '<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="description" content="Buy and rent homes">'
        '<script type="application/ld+json">{"@type": "RealEstateAgent", "name": "Fictional Realty", "telephone": "+92 42 1234 5678"}</script>'
        '</head><body><h1>Fictional Realty</h1><p>Call +92 42 1234 5678</p><a href="/contact">Contact us</a><p>© 2026 Fictional Realty</p></body></html>')
CONTACT = ('<!DOCTYPE html><html><head><title>Contact</title></head><body><form><input type="email"><textarea></textarea></form>'
           '<p>hello@fictional-realty.example</p></body></html>')


def no_fetch(url):
    raise ResearchError('not found', status=404)


class HealthTests(unittest.TestCase):
    def test_old_insecure_site_gets_low_grade_with_reasons(self):
        site = read_site(Page('http://fictional-realty.example/', OLD.encode(), OLD), no_fetch, 'websites', 'web_presence', 2026,
                         home_seconds=3.4)
        report = site['health']
        checks = [i['check'] for i in report['issues']]
        for wanted in ('no_https', 'not_mobile', 'stale_copyright', 'old_wordpress', 'old_jquery', 'quirks_mode', 'legacy_markup',
                       'slow_response', 'placeholder_title', 'no_description', 'no_phone', 'no_contact_page', 'no_email', 'images_no_alt'):
            self.assertIn(wanted, checks)
        self.assertEqual(report['grade'], 'F')
        # Category caps: freshness issues add up to more than 25 but cost at most 25.
        freshness = next(c for c in report['categories'] if c['id'] == 'freshness')
        self.assertEqual((freshness['lost'], freshness['max']), (25, 25))
        self.assertEqual(report['score'], 100 - sum(c['lost'] for c in report['categories']))
        stale = next(i for i in report['issues'] if i['check'] == 'stale_copyright')
        self.assertEqual((stale['points'], stale['plain']), (10, 'it still says © 2015, so it looks unmaintained'))
        self.assertIn('2015', stale['evidence']['text'])
        self.assertEqual(report['issues'][0]['check'], 'no_https')  # biggest problem first

    def test_good_site_scores_well_and_unmeasured_costs_nothing(self):
        def fetch(url):
            if url.endswith('/contact'):
                return Page(url, CONTACT.encode(), CONTACT)
            raise ResearchError('not found', status=404)
        site = read_site(Page('https://fictional-realty.example/', GOOD.encode(), GOOD), fetch, 'websites', 'web_presence', 2026)
        report = site['health']
        self.assertEqual(report['issues'], [])
        self.assertEqual((report['score'], report['grade']), (100, 'A'))
        self.assertEqual(report['unmeasured'], ['response time', 'phone layout'])


if __name__ == '__main__':
    unittest.main()
