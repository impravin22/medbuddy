"""Tests for voice service — Google Cloud STT v2 + TTS."""

# Check if ffmpeg is available
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.voice_service import convert_audio_to_wav, synthesise_speech, transcribe_audio

_has_ffmpeg = shutil.which("ffmpeg") is not None


class TestConvertAudioToWav:
    """Test audio format conversion."""

    @pytest.mark.skipif(not _has_ffmpeg, reason="ffmpeg not installed")
    def test_valid_wav_passthrough(self) -> None:
        """WAV content can be processed (ffmpeg handles it)."""
        # Create a minimal WAV header (44 bytes) + 1 second of silence
        wav_header = (
            b"RIFF"
            + (36 + 16000 * 2).to_bytes(4, "little")
            + b"WAVE"
            + b"fmt "
            + (16).to_bytes(4, "little")
            + (1).to_bytes(2, "little")  # PCM
            + (1).to_bytes(2, "little")  # mono
            + (16000).to_bytes(4, "little")  # sample rate
            + (32000).to_bytes(4, "little")  # byte rate
            + (2).to_bytes(2, "little")  # block align
            + (16).to_bytes(2, "little")  # bits per sample
            + b"data"
            + (16000 * 2).to_bytes(4, "little")
        )
        wav_data = wav_header + b"\x00" * (16000 * 2)

        result = convert_audio_to_wav(wav_data)
        # Should produce valid WAV output
        assert result[:4] == b"RIFF"

    @pytest.mark.skipif(not _has_ffmpeg, reason="ffmpeg not installed")
    def test_invalid_audio_raises(self) -> None:
        """Invalid audio data raises RuntimeError."""
        with pytest.raises(RuntimeError, match="Audio conversion failed"):
            convert_audio_to_wav(b"not-audio-data")


class TestTranscribeAudio:
    """Test STT transcription."""

    @pytest.mark.asyncio
    async def test_transcribes_audio_bytes(self) -> None:
        """Transcribes audio bytes and returns text."""
        mock_result = MagicMock()
        mock_alternative = MagicMock()
        mock_alternative.transcript = "我要問藥的問題"
        mock_result.alternatives = [mock_alternative]

        mock_response = MagicMock()
        mock_response.results = [mock_result]

        with (
            patch("app.services.voice_service._get_stt_client") as mock_client_fn,
            patch(
                "app.services.voice_service.convert_audio_to_wav",
                return_value=b"wav-bytes",
            ),
        ):
            mock_client = AsyncMock()
            mock_client.recognize = AsyncMock(return_value=mock_response)
            mock_client_fn.return_value = mock_client

            result = await transcribe_audio(b"audio-bytes")
            assert result == "我要問藥的問題"

    @pytest.mark.asyncio
    async def test_empty_results_returns_empty_string(self) -> None:
        """No transcription results returns empty string."""
        mock_response = MagicMock()
        mock_response.results = []

        with (
            patch("app.services.voice_service._get_stt_client") as mock_client_fn,
            patch(
                "app.services.voice_service.convert_audio_to_wav",
                return_value=b"wav-bytes",
            ),
        ):
            mock_client = AsyncMock()
            mock_client.recognize = AsyncMock(return_value=mock_response)
            mock_client_fn.return_value = mock_client

            result = await transcribe_audio(b"audio-bytes")
            assert result == ""


class TestSynthesiseSpeech:
    """Test TTS synthesis."""

    @pytest.mark.asyncio
    async def test_generates_audio_bytes(self) -> None:
        """Generates MP3 audio bytes from text."""
        mock_response = MagicMock()
        mock_response.audio_content = b"fake-mp3-audio"

        with patch("app.services.voice_service._get_tts_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.synthesize_speech = AsyncMock(return_value=mock_response)
            mock_client_fn.return_value = mock_client

            result = await synthesise_speech("您好，這是測試。")
            assert result == b"fake-mp3-audio"
            mock_client.synthesize_speech.assert_called_once()
