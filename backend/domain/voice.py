"""Bounded audio and deterministic, reviewable voice commands."""
import io
import hashlib
import json
import re
import struct
import wave
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.errors import ResearchError
from backend.domain.files import FileSearch, MemoryInput

MAX_AUDIO_BYTES = 1_000_000
MAX_SECONDS = 30
SAMPLE_RATE = 16000


@dataclass(frozen=True)
class SpeechConfig:
    cli: Path | None = None
    model: Path | None = None
    sha256: str = ""


def validate_audio(body):
    if len(body) > MAX_AUDIO_BYTES:
        raise ResearchError("Recording exceeds the 1 MB upload limit.", status=413)
    try:
        with wave.open(io.BytesIO(body), "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, SAMPLE_RATE, "NONE"):
                raise ValueError()
            frames = audio.getnframes()
            if not SAMPLE_RATE // 5 <= frames <= SAMPLE_RATE * MAX_SECONDS:
                raise ValueError()
            pcm = audio.readframes(frames)
            if len(pcm) != frames * 2:
                raise ValueError()
    except (wave.Error, EOFError, ValueError, struct.error):
        raise ResearchError("Use a complete mono 16-bit PCM WAV at 16 kHz, between 0.2 and 30 seconds.") from None
    # Near-silence abstains before inference; this is not speech detection or an
    # accuracy guarantee. All model output must still be reviewed.
    mean_square = sum(value * value for (value,) in struct.iter_unpack("<h", pcm)) / frames
    return {"seconds": frames / SAMPLE_RATE, "silent": mean_square < 16 ** 2}


class VoiceCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    transcript: str = Field(min_length=1, max_length=1000)
    root_id: str | None = Field(default=None, min_length=1, max_length=100)
    scope: str | None = Field(default=None, min_length=1, max_length=120)


class ReviewedCommand(VoiceCommand):
    expected_plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def prepare_command(payload):
    text = payload.transcript
    file_match = re.fullmatch(r"(?:find files?|search files(?: for)?)\s+(.+)", text, re.I | re.S)
    memory_match = re.fullmatch(r"search memor(?:y|ies)(?: for)?\s+(.+)", text, re.I | re.S)
    remember_match = re.fullmatch(r"remember\s+(.+)", text, re.I | re.S)
    if file_match:
        if not payload.root_id:
            raise ResearchError("Choose an approved folder before preparing a file search.")
        query = file_match[1].strip()
        if not query or len(query) > 200:
            raise ResearchError("File search needs between 1 and 200 query characters.")
        validated = FileSearch(root_id=payload.root_id, query=query)
        operation = {"kind": "search_files", "root_id": validated.root_id, "query": validated.query}
        risk, summary = "read_only", f"Search the selected approved folder for: {validated.query}"
    elif memory_match:
        if not payload.scope:
            raise ResearchError("Enter a memory scope before preparing a memory search.")
        query = memory_match[1].strip()
        if not query or len(query) > 200:
            raise ResearchError("Memory search needs between 1 and 200 query characters.")
        operation = {"kind": "search_memories", "scope": payload.scope, "query": query}
        risk, summary = "read_only", f"Search notes in {payload.scope} for: {query}"
    elif remember_match:
        if not payload.scope:
            raise ResearchError("Enter a memory scope before preparing a note.")
        if not remember_match[1].strip():
            raise ResearchError("A remembered note cannot be empty.")
        note = MemoryInput(scope=payload.scope, kind="project_context", content=remember_match[1].strip(), source="User-reviewed voice or typed command")
        operation = {"kind": "remember", "note": note.model_dump(mode="json")}
        risk, summary = "writes_memory", f"Save this user-authored note in {payload.scope}: {note.content}"
    else:
        raise ResearchError("Supported commands: 'find files <keywords>', 'search memory <keywords>', or 'remember <note>'. Edit the transcript to choose one.")
    plan = {"transcript": text, "operation": operation, "risk": risk, "summary": summary}
    return plan | {"plan_hash": hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()}
