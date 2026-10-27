"""Visible links are discovery candidates, never attributed business facts."""
import hashlib
from urllib.parse import urljoin, urlsplit

from backend.adapters.fetch import Page, validate_url
from backend.domain.errors import ResearchError
from backend.domain.extract import VisiblePage


def discover_links(page: Page, limit: int) -> dict:
    if len(page.html) > 3_000_000:
        raise ResearchError("Source HTML exceeds the discovery size limit.")
    parser = VisiblePage()
    parser.feed(page.html)
    source_host = urlsplit(page.url).hostname
    candidates, seen = [], set()
    counts = {"visible_links": len(parser.links), "same_host": 0, "invalid": 0, "duplicate": 0, "over_limit": 0}
    for href, label in parser.links:
        try:
            url = validate_url(urljoin(page.url, href))
        except ResearchError:
            counts["invalid"] += 1
            continue
        if urlsplit(url).hostname == source_host:
            counts["same_host"] += 1
            continue
        if url in seen:
            counts["duplicate"] += 1
            continue
        seen.add(url)
        if len(candidates) >= limit:
            counts["over_limit"] += 1
            continue
        if len(url) > 2048 or len(href) > 2048:
            counts["invalid"] += 1
            continue
        candidates.append({"url": url, "label": label[:250], "anchor_text": label[:400], "source_href": href,
                           "source_url": page.url, "source_sha256": hashlib.sha256(page.body).hexdigest()})
    return {"candidates": candidates, "counts": counts, "source_url": page.url,
            "source_sha256": hashlib.sha256(page.body).hexdigest()}
