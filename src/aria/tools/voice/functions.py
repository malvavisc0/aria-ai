"""`ax voice` family — in-process audio → text via the running whisper server.

No shell subprocess for the STT call: the whisper.cpp server is already up in
the web UI process. ``.wav`` files are read raw (whisper.cpp resamples
internally); any other format is converted in-memory to 16 kHz mono s16le WAV
with ffmpeg. Transcripts over ``_PERSIST_THRESHOLD`` chars are persisted to
``workspace/transcripts/``; the agent reads them via ``read_file``.
"""

import asyncio
import shutil
import subprocess
import uuid
from pathlib import Path

from aria.config.folders import Workspace
from aria.server.voice import get_whisper_manager, strip_non_speech_tags
from aria.tools import Reason, err, ok
from aria.tools.decorators import log_tool_call

_TOOL = "voice"
_PERSIST_THRESHOLD = 2000  # chars
_STT_TIMEOUT_S = 300.0  # ~5 min of CPU audio on large-v3-turbo


def _resolve_audio_path(file: str) -> Path:
    """Return the absolute file path for *file*; raise ValueError otherwise."""
    p = Path(file)
    if not p.is_absolute():
        raise ValueError(f"Path must be absolute: {file}")
    p = p.resolve()
    if p.is_dir():
        raise ValueError(f"Path is a directory, not a file: {file}")
    if not p.exists():
        raise ValueError(f"File not found: {file}")
    return p


def _to_wav(fp: Path) -> bytes:
    """Convert *fp* in-memory to 16 kHz mono s16le WAV via ffmpeg."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(fp),
            "-f",
            "wav",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-acodec",
            "pcm_s16le",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        tail = result.stderr.decode("utf-8", errors="replace")[-500:]
        raise ValueError(f"ffmpeg conversion failed: {tail}")
    return result.stdout


def _transcript_dir() -> Path:
    d = Workspace.path / "transcripts"
    d.mkdir(parents=True, exist_ok=True)
    return d


@log_tool_call
async def transcribe(reason: Reason, file: str) -> str:
    """Transcribe a local audio file to text via the in-process whisper server.

    Requires the web UI to be running (the whisper server starts with it).
    ``.wav`` files are read directly; other formats are converted in-memory
    via ffmpeg. Short transcripts return ``text`` inline; long ones (>2000
    chars) are persisted to ``workspace/transcripts/`` and returned as a
    file path.

    Args:
        reason: Why you are transcribing this file.
        file: Absolute path to the audio file.

    Returns:
        JSON with {"text", "chars"} for short transcripts, {"text": "",
        "note"} when no speech is detected, or {"file_path", "chars", "note"}
        when persisted — read the file with read_file (offset/length).
    """
    whisper = get_whisper_manager()
    if whisper is None:
        return err(
            tool=_TOOL,
            reason=reason,
            code="stt_unavailable",
            message=(
                "The whisper server is not running in this process "
                "(voice disabled or web UI not started)."
            ),
            how_to_fix=(
                "Run 'aria voice status' via shell to check the setup, then "
                "start the web UI, which launches the whisper server."
            ),
        )
    try:
        fp = _resolve_audio_path(file)
    except ValueError as exc:
        return err(tool=_TOOL, reason=reason, code="path_error", message=str(exc))

    if fp.suffix.lower() == ".wav":
        try:
            wav = await asyncio.to_thread(fp.read_bytes)
        except OSError as exc:
            return err(tool=_TOOL, reason=reason, code="path_error", message=str(exc))
    else:
        if shutil.which("ffmpeg") is None:
            return err(
                tool=_TOOL,
                reason=reason,
                code="ffmpeg_missing",
                message="ffmpeg is required to convert non-WAV audio files.",
                how_to_fix="Install ffmpeg (e.g. 'apt install ffmpeg').",
            )
        try:
            wav = await asyncio.to_thread(_to_wav, fp)
        except ValueError as exc:
            return err(
                tool=_TOOL, reason=reason, code="conversion_failed", message=str(exc)
            )

    text = strip_non_speech_tags(await whisper.transcribe(wav, timeout=_STT_TIMEOUT_S))
    if not text:
        return ok(
            tool=_TOOL, reason=reason, data={"text": "", "note": "no speech detected"}
        )
    if len(text) <= _PERSIST_THRESHOLD:
        return ok(tool=_TOOL, reason=reason, data={"text": text, "chars": len(text)})

    dest = _transcript_dir() / f"{fp.stem}_{uuid.uuid4().hex[:8]}.txt"
    dest.write_text(text, encoding="utf-8")
    return ok(
        tool=_TOOL,
        reason=reason,
        data={
            "file_path": str(dest),
            "chars": len(text),
            "note": "persisted — read with read_file (offset/length)",
        },
    )
