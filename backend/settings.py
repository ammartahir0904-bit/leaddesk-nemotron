import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from backend.domain.voice import SpeechConfig

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    token: str
    web_dir: Path = ROOT / "apps/web/dist"
    speech: SpeechConfig = field(default_factory=SpeechConfig)
    # User-run SearXNG instance for web enrichment; loopback only.
    searxng_url: str = 'http://127.0.0.1:8888'
    # Optional services, used only when the key is set AND the user turns them on in the app.
    nebius_api_key: str = field(default='', repr=False)
    tavily_api_key: str = field(default='', repr=False)
    # Public demo (LEADDESK_DEMO=1): fictional data, network actions off, AI rewording capped. public_host: the demo's address.
    demo: bool = False
    public_host: str = ''
    demo_ai_per_hour: int = 30
    demo_model: str = ''

    @classmethod
    def load(cls):
        folder = Path(os.environ.get("LEADDESK_DATA_DIR", ROOT / ".local"))
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        token_path = folder / "access-token"
        try:
            with open(token_path, "x", opener=lambda p, f: os.open(p, f, 0o600)) as file:
                file.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass
        token = token_path.read_text().strip()
        if len(token) < 32:
            raise RuntimeError("Invalid local access token; restore or remove .local/access-token")
        cli, model = os.environ.get("LEADDESK_WHISPER_CLI"), os.environ.get("LEADDESK_WHISPER_MODEL")
        speech = SpeechConfig(Path(cli) if cli else None, Path(model) if model else None,
                              os.environ.get("LEADDESK_WHISPER_SHA256", ""))
        return cls(folder, token, speech=speech, searxng_url=os.environ.get('LEADDESK_SEARXNG_URL', 'http://127.0.0.1:8888'),
                   nebius_api_key=os.environ.get('NEBIUS_API_KEY', ''), tavily_api_key=os.environ.get('TAVILY_API_KEY', ''),
                   demo=os.environ.get('LEADDESK_DEMO') == '1', public_host=os.environ.get('LEADDESK_PUBLIC_HOST', '').strip(),
                   demo_ai_per_hour=int(os.environ.get('LEADDESK_DEMO_AI_PER_HOUR', '30')),
                   demo_model=os.environ.get('LEADDESK_DEMO_MODEL', '').strip())
