"""Refresh the local list of disposable (temporary) email domains used by the contact review.

Source: github.com/disposable-email-domains/disposable-email-domains (CC0 1.0). Run by hand; LeadDesk never fetches it at
runtime. Only lines that are plain domain names are kept. The header records the source URL, date, entry count and the
SHA-256 of the downloaded file.

Usage: .venv/bin/python scripts/update_disposable_domains.py
"""
import datetime
import hashlib
import re
import sys
import urllib.request
from pathlib import Path

SOURCE = 'https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/main/disposable_email_blocklist.conf'
TARGET = Path(__file__).resolve().parents[1] / 'backend' / 'domain' / 'data' / 'disposable_domains.txt'
DOMAIN = re.compile(r'^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$')


def main():
    with urllib.request.urlopen(SOURCE, timeout=60) as response:
        body = response.read(20_000_000)
    domains = sorted({line.strip().casefold() for line in body.decode('utf-8', 'replace').splitlines()
                      if DOMAIN.match(line.strip().casefold())})
    if len(domains) < 1000:
        sys.exit(f'Only {len(domains)} domains found; refusing to replace the list.')
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    header = [f'# source: {SOURCE}', '# licence: CC0 1.0', f'# retrieved: {datetime.date.today().isoformat()}',
              f'# source_sha256: {hashlib.sha256(body).hexdigest()}', f'# entries: {len(domains)}']
    TARGET.write_text('\n'.join(header + domains) + '\n', encoding='utf-8')
    print(f'Wrote {len(domains)} domains to {TARGET}')


if __name__ == '__main__':
    main()
