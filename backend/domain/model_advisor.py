"""Hardware-aware local model recommendations. Estimates only; benchmark before trusting.

Sizes are approximate for Ollama's default 4-bit tags. Nothing is downloaded or
installed by LeadDesk; the user runs the shown commands themselves.
"""
GIB = 1024 ** 3

# id, ollama tag, approx download GiB, approx memory needed GiB (weights + context), role, use in LeadDesk
CATALOGUE = [
    {'tag': 'nomic-embed-text', 'family': 'embedding', 'download_gib': 0.3, 'memory_gib': 0.6,
     'role': 'Embedding model: turns text into vectors so businesses can be matched to your product by meaning, not exact words.',
     'leaddesk_use': 'Planned: semantic matching of business websites to your product. Small and fast, even without a GPU.'},
    {'tag': 'qwen2.5:1.5b', 'family': 'general', 'download_gib': 1.0, 'memory_gib': 2.0,
     'role': 'Tiny general model for short extraction and yes/no classification.',
     'leaddesk_use': 'Planned: quick need/fit labels from saved website evidence on weak laptops. Expect more mistakes.'},
    {'tag': 'llama3.2:3b', 'family': 'general', 'download_gib': 2.0, 'memory_gib': 3.5,
     'role': 'Small general model. Usable on CPU-only laptops with 8 GB RAM, slowly.',
     'leaddesk_use': 'Planned: need/fit summaries and draft outreach text, reviewed by you.'},
    {'tag': 'qwen2.5:7b', 'family': 'general', 'download_gib': 4.7, 'memory_gib': 7.0,
     'role': 'Mid-size model with good structured (JSON) output and multilingual text, including Urdu.',
     'leaddesk_use': 'Recommended main model: business need analysis, product briefs, outreach drafts.'},
    {'tag': 'llama3.1:8b', 'family': 'general', 'download_gib': 4.9, 'memory_gib': 7.5,
     'role': 'Mid-size general model, strong English writing.',
     'leaddesk_use': 'Alternative main model for English outreach drafts and summaries.'},
    {'tag': 'qwen2.5:14b', 'family': 'general', 'download_gib': 9.0, 'memory_gib': 12.0,
     'role': 'Larger model: better reasoning over long website text.',
     'leaddesk_use': 'Best quality for need analysis when a 12 GB+ GPU or 24 GB+ RAM is available.'},
    {'tag': 'qwen2.5:32b', 'family': 'general', 'download_gib': 20.0, 'memory_gib': 24.0,
     'role': 'Large model for high-end GPUs (24 GB) or 48 GB+ RAM.',
     'leaddesk_use': 'Highest local quality; slow on CPU.'},
]


def budgets(profile, gpus):
    memory = profile['memory']
    total = memory.get('total_bytes') or 0
    available = memory.get('effective_available_bytes') or memory.get('available_bytes') or 0
    # Leave room for the OS, browser and LeadDesk itself.
    ram = max(0, total - 3 * GIB)
    vram = max((g.get('vram_bytes') or 0 for g in gpus), default=0)
    return ram, available, vram


def recommend(profile, gpus, installed, ollama_present):
    ram, available, vram = budgets(profile, gpus)
    accelerated = vram >= 4 * GIB
    budget = vram if accelerated else ram
    disk_free = (profile.get('disk') or {}).get('free_bytes')
    names = {m['name'] for m in installed}
    rows = []
    for model in CATALOGUE:
        need = model['memory_gib'] * GIB
        if accelerated and need <= vram:
            fit, speed = 'fits_gpu', 'Fast: fits fully in GPU memory.'
        elif need <= ram:
            fit = 'fits_cpu'
            speed = 'Usable on CPU.' if model['memory_gib'] <= 2 else 'Runs on CPU, slowly (often a few words per second on a laptop).'
            if accelerated:
                speed = 'Too big for the GPU; runs partly or fully on CPU, slower.'
        else:
            fit, speed = 'too_big', 'Not recommended: needs more memory than this computer has.'
        if disk_free is not None and model['download_gib'] * GIB > disk_free:
            fit, speed = 'no_disk', 'Not enough free disk space to download.'
        installed_now = any(n == model['tag'] or n.startswith(model['tag'] + '-') or n == model['tag'] + ':latest' for n in names)
        rows.append(model | {'fit': fit, 'speed': speed, 'installed': installed_now, 'install_command': f"ollama pull {model['tag']}"})
    general = [r for r in rows if r['family'] == 'general' and r['fit'] in {'fits_gpu', 'fits_cpu'}]
    # Prefer the largest model that runs on the GPU; on CPU prefer at most ~7 GB for usable speed.
    preferred = ([r for r in general if r['fit'] == 'fits_gpu'] or [r for r in general if r['memory_gib'] <= 7.5] or general)
    main = max(preferred, key=lambda r: r['memory_gib'], default=None)
    embed = next((r for r in rows if r['family'] == 'embedding' and r['fit'] != 'too_big'), None)
    if accelerated:
        tier = f'GPU computer ({vram / GIB:.0f} GB GPU memory)'
    elif ram >= 12 * GIB:
        tier = 'Strong CPU-only computer'
    elif ram >= 3 * GIB:
        tier = 'Light laptop (CPU only)'
    else:
        tier = 'Very limited memory'
    picks = [r['tag'] for r in (main, embed) if r]
    for row in rows:
        row['recommended'] = row['tag'] in picks
    steps = []
    if not ollama_present:
        steps.append('Install Ollama from https://ollama.com/download (free). LeadDesk never installs it for you.')
    steps += [f"Run: ollama pull {tag}" for tag in picks if not next(r for r in rows if r['tag'] == tag)['installed']]
    if not steps:
        steps.append('Recommended models are installed. Run a local model benchmark before relying on them.')
    notes = ['Sizes and speeds are estimates for default 4-bit models; measure with a benchmark on this computer.',
             'No model is downloaded or enabled automatically. Model output stays a proposal until you review it.']
    if not accelerated and ram < 12 * GIB:
        notes.append('For faster AI analysis, run LeadDesk on a computer with an NVIDIA GPU (8 GB+ VRAM) or 16 GB+ RAM. The advisor will re-check there.')
    if available and main and main['memory_gib'] * GIB > available:
        notes.append(f"Only {available / GIB:.1f} GB RAM is free right now. Close other apps before running {main['tag']}.")
    return {'tier': tier, 'budget_bytes': budget, 'ram_budget_bytes': ram, 'vram_bytes': vram or None,
            'main_model': main['tag'] if main else None, 'embedding_model': embed['tag'] if embed else None,
            'models': rows, 'next_steps': steps, 'notes': notes}
