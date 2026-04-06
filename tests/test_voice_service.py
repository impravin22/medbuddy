"""Tests for voice service — Gemini multimodal STT + edge-tts TTS."""

import shutil
from unittest.mock import MagicMock, patch

import pytest

from app.services.voice_service import convert_audio_to_wav, synthesise_speech, transcribe_audio

_has_ffmpeg = shutil.which("ffmpeg") is not None


class TestConvertAudioToWav:
    """Test audio format conversion."""

    @pytest.mark.skipif(not _has_ffmpeg, reason="ffmpeg not installed")
    def test_valid_wav_passthrough(self) -> None:
        """WAV content can be processed (ffmpeg handles it)."""
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
        assert result[:4] == b"RIFF"

    @pytest.mark.skipif(not _has_ffmpeg, reason="ffmpeg not installed")
    def test_invalid_audio_raises(self) -> None:
        """Invalid audio data raises RuntimeError."""
        with pytest.raises(RuntimeError, match="Audio conversion failed"):
            convert_audio_to_wav(b"not-audio-data")


class TestTranscribeAudio:
    """Test Gemini multimodal STT transcription."""

    @pytest.mark.asyncio
    async def test_transcribes_audio_bytes(self) -> None:
        """Transcribes audio bytes via Gemini and returns text."""
        mock_response = MagicMock()
        mock_response.text = "我要問藥的問題"

        mock_client = MagicMock()
        mock_client.models.generate_content = MagicMock(return_value=mock_response)

        with (
            patch("app.services.voice_service._get_genai_client", return_value=mock_client),
            patch("app.services.voice_service.convert_audio_to_wav", return_value=b"wav-bytes"),
        ):
            result = await transcribe_audio(b"audio-bytes")
            assert result == "我要問藥的問題"
            mock_client.models.generate_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_string(self) -> None:
        """Empty Gemini response returns empty string."""
        mock_response = MagicMock()
        mock_response.text = ""

        mock_client = MagicMock()
        mock_client.models.generate_content = MagicMock(return_value=mock_response)

        with (
            patch("app.services.voice_service._get_genai_client", return_value=mock_client),
            patch("app.services.voice_service.convert_audio_to_wav", return_value=b"wav-bytes"),
        ):
            result = await transcribe_audio(b"audio-bytes")
            assert result == ""


class TestSynthesiseSpeech:
    """Test edge-tts synthesis."""

    @pytest.mark.asyncio
    async def test_generates_audio_bytes(self) -> None:
        """Generates MP3 audio bytes from text using edge-tts."""
        result = await synthesise_speech("測試")
        assert len(result) > 0
        # MP3 files start with ID3 tag or 0xFF sync byte
        assert result[:3] == b"ID3" or result[0] == 0xFF
