"""Explicit offline whisper.cpp invocation. No shell or download fallback."""
import hashlib
import os
import re
import signal
import stat
import subprocess
import tempfile
import time
from pathlib import Path

from backend.adapters.hardware import GIB, profile_hardware
from backend.domain.errors import ResearchError

MAX_MODEL_BYTES = 512 * 1024 * 1024
MAX_TRANSCRIPT_BYTES = 16000
TIMEOUT = 90


class SpeechCancelled(Exception):
    pass


class WhisperAdapter:
    def __init__(self, config, data_dir):
        self.config, self.data_dir = config, data_dir

    def status(self):
        config = self.config
        configured = bool(config.cli and config.model and re.fullmatch(r"[a-f0-9]{64}", config.sha256))
        ready = False
        if configured:
            try:
                ready = (config.cli.is_absolute() and config.model.is_absolute()
                         and stat.S_ISREG(config.cli.stat().st_mode) and os.access(config.cli, os.X_OK)
                         and stat.S_ISREG(config.model.stat().st_mode) and 0 < config.model.stat().st_size <= MAX_MODEL_BYTES)
            except (OSError, ValueError):
                pass
        return {"available": bool(ready), "engine": "whisper.cpp", "model_sha256": config.sha256 if configured else None,
                "reason": "Configured local files found; digest and memory are checked before inference." if ready else
                "Configure an installed whisper-cli, a local model up to 512 MiB and its SHA-256. Typed commands remain available.",
                "max_seconds": 30, "languages": ["auto", "en", "ur"], "cloud_enabled": False}

    def verify_model(self, cancelled):
        if not self.status()["available"]:
            raise ResearchError("Local speech recognition is unavailable. Check the configured whisper.cpp files.", status=503)
        digest = hashlib.sha256()
        consumed, started = 0, time.monotonic()
        with self.config.model.open("rb") as model:
            before = os.fstat(model.fileno())
            while chunk := model.read(1024 * 1024):
                consumed += len(chunk)
                if cancelled.is_set():
                    raise SpeechCancelled()
                if consumed > MAX_MODEL_BYTES or time.monotonic() - started > 15:
                    raise ResearchError("Speech model verification exceeded its size or time budget.")
                digest.update(chunk)
            after = os.fstat(model.fileno())
        signature = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if signature(before) != signature(after) or digest.hexdigest() != self.config.sha256:
            raise ResearchError("The selected speech model changed or its SHA-256 does not match.", status=409)
        return signature(after)

    @staticmethod
    def stop(process):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
            except ProcessLookupError:
                pass

    def transcribe(self, body, language, cancelled):
        signature = self.verify_model(cancelled)
        available = profile_hardware(self.data_dir)["memory"]["effective_available_bytes"]
        if available is None or available < 3 * GIB:
            raise ResearchError("Speech recognition needs at least 3 GiB available RAM. Free memory or use typed commands.", status=429)
        if cancelled.is_set():
            raise SpeechCancelled()
        with tempfile.TemporaryDirectory(prefix="leaddesk-audio-") as folder:
            root = Path(folder)
            audio_path, output = root / "input.wav", root / "transcript"
            audio_path.write_bytes(body)
            command = [str(self.config.cli), "--model", str(self.config.model), "--file", str(audio_path),
                       "--language", language, "--threads", "2", "--processors", "1", "--no-gpu", "--no-prints",
                       "--no-timestamps", "--output-txt", "--output-file", str(output)]
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       cwd=root, start_new_session=True,
                                       env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "OMP_NUM_THREADS": "2"})
            started = time.monotonic()
            try:
                while process.poll() is None:
                    if cancelled.wait(.05):
                        raise SpeechCancelled()
                    if time.monotonic() - started > TIMEOUT:
                        raise ResearchError("Local transcription exceeded 90 seconds. Try a shorter recording or type the command.", status=504)
                if cancelled.is_set():
                    raise SpeechCancelled()
                if process.returncode != 0:
                    raise ResearchError("The local speech runtime failed. Check CLI/model compatibility; typed commands remain available.", status=503)
                current = self.config.model.stat()
                if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns) != signature:
                    raise ResearchError("Speech model changed during inference. The transcript was discarded.", status=409)
                path = output.with_suffix(".txt")
                with path.open("rb") as file:
                    transcript = file.read(MAX_TRANSCRIPT_BYTES + 1)
                if len(transcript) > MAX_TRANSCRIPT_BYTES:
                    raise ResearchError("The speech runtime returned too much text. The result was discarded.")
                text = transcript.decode("utf-8").strip()
                if len(text) > 1000 or "\x00" in text:
                    raise ResearchError("The transcript exceeds the review limit or contains invalid text.")
                return text
            finally:
                self.stop(process)
