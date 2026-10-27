#!/usr/bin/env python3
"""Run from the explicitly paired PC; never starts networking or installs models."""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from backend.workflows.pc_client import PCWorkerClient, WorkerProtocolError, read_credential


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--coordinator', required=True, help='http://127.0.0.1:PORT through your SSH tunnel')
    parser.add_argument('--credential-file', required=True, type=Path)
    parser.add_argument('--once', action='store_true', help='Poll once and exit; otherwise reconnect until Ctrl+C')
    args = parser.parse_args()
    client = None
    try:
        client = PCWorkerClient(args.coordinator, read_credential(args.credential_file))
        failures = 0
        while True:
            try:
                state = client.run_once()
                failures = 0
                print(f'PC benchmark worker: {state}.', flush=True)
            except httpx.TransportError:
                failures = min(failures + 1, 5)
                print('Coordinator disconnected. Retaining any pending result and retrying.', flush=True)
                if args.once:
                    return 1
            if args.once:
                return 0
            time.sleep(min(30, 2 ** failures) if failures else 5)
    except KeyboardInterrupt:
        return 0
    except WorkerProtocolError as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        if client:
            client.close()


if __name__ == '__main__':
    raise SystemExit(main())
