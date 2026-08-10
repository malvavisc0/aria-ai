"""YouTube-specific functionality for transcript extraction.

This module contains YouTube-related helper functions.
"""

import re

from loguru import logger
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)

from aria.tools import (
    Reason,
    get_function_name,
    tool_error_response,
    tool_success_response,
)
from aria.tools.decorators import log_tool_call
from aria.tools.search._download_internals import (
    _save_content_to_file,
    _validate_url,
)
from aria.tools.search.constants import DOWNLOADS_DIR

# Split the joined transcript into paragraphs roughly every N sentences so
# the output is readable prose, not 500+ caption-fragment lines.
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")
_PARAGRAPH_SENTENCES = 3


def _format_transcript_text(snippets: list) -> str:
    """Join caption snippets into readable paragraphed prose.

    YouTube splits captions into ~3-second fragments, so the library's
    ``TextFormatter`` (one newline per snippet) yields hundreds of
    mid-sentence line breaks. Instead, join snippet text with spaces,
    collapse whitespace, and break into paragraphs at sentence boundaries.
    """
    joined = " ".join(s.text for s in snippets)
    joined = re.sub(r"\s+", " ", joined).strip()
    sentences = _SENTENCE_END_RE.split(joined)
    paragraphs: list[str] = []
    for i in range(0, len(sentences), _PARAGRAPH_SENTENCES):
        paragraphs.append(" ".join(sentences[i : i + _PARAGRAPH_SENTENCES]).strip())
    return "\n\n".join(paragraphs)


def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from URL.

    Args:
        url: YouTube URL

    Returns:
        Video ID or None if not found
    """
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", url)
    if match:
        return match.group(1)
    return None


def _get_youtube_transcript(
    video_id: str, languages: list[str] | None = None
) -> tuple[str, list, float]:
    """Fetch and format YouTube transcript.

    Args:
        video_id: YouTube video ID
        languages: Ordered list of language codes to try (e.g. ["de", "en"]).
            Defaults to ["en"] when not provided.

    Returns:
        Tuple of (transcript_text, snippets, estimated_duration)

    Raises:
        NoTranscriptFound: If no transcripts are available
        TranscriptsDisabled: If transcripts are disabled
    """
    api = YouTubeTranscriptApi()
    transcript = api.fetch(video_id, languages=languages or ["en"])

    transcript_text = _format_transcript_text(transcript.snippets)

    return (
        transcript_text,
        transcript.snippets,
        sum(snippet.duration for snippet in transcript.snippets),
    )


@log_tool_call
def get_youtube_video_transcription(
    reason: Reason,
    url: str,
    languages: list[str] | None = None,
) -> str:
    """Download and save a YouTube video's captions/transcript to disk.

    When to use:
        - Use this when the user wants the transcript/subtitles of a
          YouTube video.
        - Use this to extract spoken content from videos for analysis
          or summarization.
        - Do NOT use this to download the video itself — only captions
          are extracted.

    Why:
        Persistence-first design: writes the transcript to disk and
        returns file metadata. Use `read_file` to read the saved
        transcript afterward.

    Args:
        reason: Required. Brief explanation of why you are downloading this transcript.
        url: YouTube video URL.
        languages: Ordered list of language codes to try, e.g.
            ["de", "en"] to prefer German and fall back to English.
            Defaults to ["en"] when not provided.

    Returns:
        JSON with file_path and metadata (video_id,
        transcript_segments, estimated_duration).

    Important:
        - Only works for videos that have captions/subtitles available.
        - The transcript is saved to disk, not returned inline.
        - Use `read_file` on the returned file_path to get the content.
    """
    from aria.tools.search.download import URLDownloadError

    try:
        validated_url = _validate_url(url)
    except URLDownloadError as exc:
        logger.error(f"Invalid URL for YouTube transcription: {exc}")
        return tool_error_response(get_function_name(), reason, exc)

    video_id = _extract_video_id(validated_url)
    if not video_id:
        error_msg = "Could not extract YouTube video ID from URL"
        logger.error(error_msg)
        return tool_error_response(get_function_name(), reason, RuntimeError(error_msg))

    logger.debug(f"Extracted video ID: {video_id} from {validated_url}")

    try:
        transcript_text, snippets, duration = _get_youtube_transcript(
            video_id, languages=languages
        )

        file_path, metadata = _save_content_to_file(
            transcript_text,
            validated_url,
            "text/plain",
            "text",
            original_filename=f"{video_id}_transcript.txt",
            download_path=str(DOWNLOADS_DIR),
        )

        metadata["video_id"] = video_id
        metadata["transcript_segments"] = len(snippets)
        metadata["estimated_duration"] = duration

        return tool_success_response(
            get_function_name(),
            reason,
            {"file_path": file_path, "metadata": metadata},
        )

    except NoTranscriptFound:
        error_msg = (
            f"No transcripts found for video {video_id}. Video may lack captions."
        )
        logger.warning(error_msg)
        return tool_error_response(get_function_name(), reason, RuntimeError(error_msg))
    except TranscriptsDisabled:
        error_msg = f"Transcripts disabled for video {video_id} by uploader."
        logger.warning(error_msg)
        return tool_error_response(get_function_name(), reason, RuntimeError(error_msg))
    except Exception as exc:
        error_msg = f"Failed to get YouTube transcription from {url}: {exc}"
        logger.error(error_msg)
        return tool_error_response(get_function_name(), reason, RuntimeError(error_msg))
