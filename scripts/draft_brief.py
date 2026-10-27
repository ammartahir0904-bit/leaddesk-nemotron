"""Draft from a JSON offer file; local inference requires explicit model selection."""
import argparse
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError

from backend.adapters.briefs import model_draft
from backend.adapters.local_model import LocalModelError, OllamaAdapter
from backend.domain.briefs import OfferInput, rules_draft
from backend.domain.errors import ResearchError
from backend.settings import ROOT
from backend.storage.briefs import BriefRepository
from backend.storage.repository import Repository, request_hash


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="UTF-8 JSON file containing OfferInput fields.")
    parser.add_argument("--model", help="Exact installed Ollama model name; enables local CPU inference.")
    parser.add_argument("--digest", help="Required exact 64-character installed-model digest.")
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--save", action="store_true", help="Save as a new editable brief in the local workspace.")
    args = parser.parse_args()
    if bool(args.model) != bool(args.digest):
        parser.error("--model and --digest must be supplied together.")
    data_dir = Path(os.environ.get("LEADDESK_DATA_DIR", ROOT / ".local"))
    try:
        with args.input.open("rb") as source:
            raw = source.read(16001)
        if len(raw) > 16000:
            raise ValueError("Offer input is too large (maximum 16 KB).")
        inputs = OfferInput.model_validate_json(raw)
        if args.model:
            adapter = OllamaAdapter(args.model, args.digest, data_dir, port=args.port, max_output_tokens=512)
            try:
                adapter.inspect_model()
                draft = model_draft(inputs, adapter, args.digest)
            finally:
                adapter.close()
        else:
            draft = rules_draft(inputs)
        if args.save:
            digest = request_hash({"input": inputs.model_dump(), "generation": draft["generation"]})
            result = BriefRepository(Repository(data_dir / "leaddesk.sqlite3")).create(draft, str(uuid4()), digest)
        else:
            result = draft
    except (OSError, ValueError, ResearchError, LocalModelError) as error:
        # Do not echo offer file contents in a validation traceback.
        message = "Offer input does not match the brief schema." if isinstance(error, ValidationError) else str(error)
        parser.exit(2, f"Brief not saved: {message}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
