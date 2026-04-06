"""Voice service — Google Cloud STT v2 (Chirp 3) + Google Cloud TTS (Chirp 3 HD).

STT: Transcribes Mandarin audio from LINE voice messages.
TTS: Generates warm zh-TW audio for medication explanations.

Uses existing GOOGLE_CLOUD_PROJECT and GOOGLE_APPLICATION_CREDENTIALS from .env.
"""

import logging
import subprocess

from google.cloud.speech_v2 import SpeechAsyncClient
from google.cloud.speech_v2.types import cloud_speech
from google.cloud.texttospeech_v1 import TextToSpeechAsyncClient
from google.cloud.texttospeech_v1.types import (
    AudioConfig,
    AudioEncoding,
    SynthesisInput,
    VoiceSelectionParams,
)

from app.config import settings

logger = logging.getLogger(__name__)

# Singleton clients — initialised once
_stt_client: SpeechAsyncClient | None = None
_tts_client: TextToSpeechAsyncClient | None = None


def _get_stt_client() -> SpeechAsyncClient:
    """Get or create the STT async client singleton."""
    global _stt_client
    if _stt_client is None:
        _stt_client = SpeechAsyncClient()
    return _stt_client


def _get_tts_client() -> TextToSpeechAsyncClient:
    """Get or create the TTS async client singleton."""
    global _tts_client
    if _tts_client is None:
        _tts_client = TextToSpeechAsyncClient()
    return _tts_client


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
    """Transcribe audio bytes to Traditional Chinese text using Chirp 3.

    Args:
        audio_bytes: Raw audio bytes (M4A from LINE or WAV).
        convert_from_m4a: If True, convert from M4A to WAV first.

    Returns:
        Transcribed text string.

    Raises:
        Exception: If transcription fails.
    """
    if convert_from_m4a:
        try:
            audio_bytes = convert_audio_to_wav(audio_bytes)
        except RuntimeError:
            logger.warning("Audio conversion failed, trying raw audio with auto-detect")
            # Fall through to try auto-detect with raw audio

    client = _get_stt_client()

    config = cloud_speech.RecognitionConfig(
        auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
        language_codes=["cmn-Hant-TW"],
        model="chirp_3",
    )

    request = cloud_speech.RecognizeRequest(
        recognizer=f"projects/{settings.GOOGLE_CLOUD_PROJECT}/locations/global/recognizers/_",
        config=config,
        content=audio_bytes,
    )

    response = await client.recognize(request=request)

    return "".join(r.alternatives[0].transcript for r in response.results if r.alternatives)


async def synthesise_speech(text: str) -> bytes:
    """Convert text to speech in Traditional Chinese using Chirp 3 HD.

    Uses a warm zh-TW voice with slightly slower pacing for elderly users.

    Args:
        text: Text to synthesise in Traditional Chinese.

    Returns:
        Audio bytes in MP3 format (LINE-compatible).
    """
    client = _get_tts_client()

    # Use SSML for pacing control — slightly slower for elderly users
    ssml = f'<speak><prosody rate="slow">{text}</prosody></speak>'

    synthesis_input = SynthesisInput(ssml=ssml)

    voice = VoiceSelectionParams(
        language_code="cmn-TW",
        name="cmn-TW-Standard-A",  # Standard voice; upgrade to Chirp 3 HD when available in region
    )

    audio_config = AudioConfig(
        audio_encoding=AudioEncoding.MP3,
        speaking_rate=0.9,  # Slightly slower
        pitch=0.0,
    )

    response = await client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )

    return response.audio_content
