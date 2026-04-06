"""Voice service — Gemini multimodal STT + edge-tts for TTS.

STT: Gemini 2.5 Flash transcribes Mandarin audio natively (multimodal input).
TTS: edge-tts with zh-TW-HsiaoChenNeural voice (free, no API key required).

No GCP Speech/TTS APIs needed — works with just a Gemini API key.
"""

import logging
import subprocess
import tempfile

import edge_tts
from google import genai
from google.genai.types import Part

from app.config import settings

logger = logging.getLogger(__name__)

# Singleton Gemini client
_genai_client: genai.Client | None = None

# edge-tts voice for Traditional Chinese (warm female voice)
_TTS_VOICE = "zh-TW-HsiaoChenNeural"


def _get_genai_client() -> genai.Client:
    """Get or create the Gemini client singleton."""
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    return _genai_client


def convert_audio_to_wav(audio_bytes: bytes) -> bytes:
    """Convert audio bytes (m4a/aac from LINE) to 16kHz mono WAV.

    Args:
        audio_bytes: Raw audio bytes from LINE CDN.

    Returns:
        WAV audio bytes (LINEAR16, 16kHz, mono).

    Raises:
        RuntimeError: If ffmpeg conversion fails.
    """
    result = subprocess.run(
        [
            "ffmpeg",
            "-i",
            "pipe:0",
            "-f",
            "wav",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            "pipe:1",
        ],
        input=audio_bytes,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        error_msg = result.stderr.decode("utf-8", errors="replace")
        msg = f"Audio conversion failed: {error_msg}"
        raise RuntimeError(msg)
    return result.stdout


async def transcribe_audio(audio_bytes: bytes, convert_from_m4a: bool = True) -> str:
    """Transcribe audio bytes to Traditional Chinese text using Gemini multimodal.

    Gemini 2.5 Flash handles audio input natively — no separate STT API needed.

    Args:
        audio_bytes: Raw audio bytes (M4A from LINE or WAV).
        convert_from_m4a: If True, convert from M4A to WAV first for better accuracy.

    Returns:
        Transcribed text string.
    """
    # Convert to WAV for consistent audio format
    if convert_from_m4a:
        try:
            audio_bytes = convert_audio_to_wav(audio_bytes)
            mime_type = "audio/wav"
        except RuntimeError:
            logger.warning("Audio conversion failed, sending raw audio to Gemini")
            mime_type = "audio/m4a"
    else:
        mime_type = "audio/wav"

    client = _get_genai_client()

    audio_part = Part.from_bytes(data=audio_bytes, mime_type=mime_type)

    response = client.models.generate_content(
        model=settings.GOOGLE_AI_FAST_MODEL,
        contents=[
            audio_part,
            (
                "Transcribe this audio exactly. "
                "Output only the transcription in Traditional Chinese (繁體中文). "
                "Do not add any explanation, translation, or punctuation that is not spoken. "
                "If the audio contains English words (like drug names), keep them as-is."
            ),
        ],
    )

    transcript = response.text.strip() if response.text else ""
    logger.info("Gemini STT transcription: %s", transcript[:50])
    return transcript


async def synthesise_speech(text: str) -> bytes:
    """Convert text to speech in Traditional Chinese using edge-tts.

    Uses zh-TW-HsiaoChenNeural — a warm, natural female voice.
    Free, no API key required.

    Args:
        text: Text to synthesise in Traditional Chinese.

    Returns:
        Audio bytes in MP3 format (LINE-compatible).
    """
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    communicate = edge_tts.Communicate(text, _TTS_VOICE, rate="-10%")
    await communicate.save(tmp_path)

    with open(tmp_path, "rb") as f:
        audio_bytes = f.read()

    import os

    os.unlink(tmp_path)

    logger.info("edge-tts generated %d bytes for: %s", len(audio_bytes), text[:30])
    return audio_bytes
