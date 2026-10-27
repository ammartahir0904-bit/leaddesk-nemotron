#!/usr/bin/env python3
"""Generate a visibly fictional quality report in disposable storage."""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.evaluation.quality_demo import build_quality_demo
from backend.storage.repository import Repository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Write the fictional report JSON here instead of stdout.')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='leaddesk-quality-demo-') as folder:
        report = build_quality_demo(Repository(Path(folder) / 'demo.sqlite3'))
    body = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(body)
        print('Wrote six fictional cases; real quality/release readiness remains unestablished.')
    else:
        print(body, end='')


if __name__ == '__main__':
    main()
