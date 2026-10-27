"""Explicit, read-only probes for the model advisor: NVIDIA GPUs and local Ollama.

Fixed commands and loopback-only HTTP. Nothing is installed or downloaded.
"""
import shutil
import subprocess

import httpx

GIB = 1024 ** 3


def nvidia_gpus(run=subprocess.run):
    if not shutil.which('nvidia-smi'):
        return []
    try:
        output = run(['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader,nounits'],
                     capture_output=True, text=True, timeout=5, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    gpus = []
    for line in output.strip().splitlines()[:8]:
        parts = [p.strip() for p in line.split(',')]
        if len(parts) == 3 and parts[1].isdigit():
            gpus.append({'name': parts[0][:120], 'vram_bytes': int(parts[1]) * 1024 * 1024, 'driver': parts[2][:40], 'source': 'nvidia-smi'})
    return gpus


def ollama_models(transport=None):
    present = shutil.which('ollama') is not None
    try:
        with httpx.Client(base_url='http://127.0.0.1:11434', trust_env=False, follow_redirects=False,
                          timeout=httpx.Timeout(2), transport=transport) as client:
            response = client.get('/api/tags')
            response.raise_for_status()
            models = response.json().get('models', [])
        running = True
    except (httpx.HTTPError, ValueError, AttributeError):
        models, running = [], False
    installed = [{'name': str(m.get('name', ''))[:200], 'size_bytes': m.get('size') if isinstance(m.get('size'), int) else None,
                  'digest': str(m.get('digest') or '')[:64], 'remote': bool(m.get('remote_host') or m.get('remote_model'))}
                 for m in models if isinstance(m, dict)][:100]
    return {'installed': present or running, 'running': running, 'models': installed}


def probe():
    return {'gpus': nvidia_gpus(), 'ollama': ollama_models()}
