"""Tests for AES-256-GCM field-level encryption."""

from unittest.mock import patch

import pytest
from cryptography.exceptions import InvalidTag

from app.services.encryption import decrypt, encrypt, generate_key_hex


class TestEncryptDecrypt:
    """Test the encrypt/decrypt round-trip."""

    def test_round_trip_basic(self) -> None:
        """Encrypting then decrypting returns the original text."""
        plaintext = "Metformin 500mg"
        encrypted = encrypt(plaintext)
        assert decrypt(encrypted) == plaintext

    def test_round_trip_chinese(self) -> None:
        """Round-trip works with Traditional Chinese characters."""
        plaintext = "降血糖藥 每天兩次"
        encrypted = encrypt(plaintext)
        assert decrypt(encrypted) == plaintext

    def test_round_trip_empty_string(self) -> None:
        """Empty string produces empty bytes and decrypts back."""
        assert encrypt("") == b""
        assert decrypt(b"") == ""

    def test_different_ciphertexts_each_call(self) -> None:
        """Each encryption produces a different ciphertext (unique nonce)."""
        plaintext = "Lisinopril 10mg"
        encrypted_1 = encrypt(plaintext)
        encrypted_2 = encrypt(plaintext)
        assert encrypted_1 != encrypted_2
        # But both decrypt to the same plaintext
        assert decrypt(encrypted_1) == plaintext
        assert decrypt(encrypted_2) == plaintext

    def test_ciphertext_is_longer_than_plaintext(self) -> None:
        """Ciphertext includes 12-byte nonce + 16-byte GCM tag overhead."""
        plaintext = "test"
        encrypted = encrypt(plaintext)
        # nonce (12) + plaintext (4) + GCM tag (16) = 32 bytes
        assert len(encrypted) == 12 + len(plaintext.encode("utf-8")) + 16

    def test_tampered_ciphertext_raises(self) -> None:
        """Modifying the ciphertext triggers InvalidTag (authentication failure)."""
        encrypted = encrypt("sensitive medication data")
        # Flip a byte in the ciphertext portion
        tampered = bytearray(encrypted)
        tampered[15] ^= 0xFF  # Modify a byte after the nonce
        with pytest.raises(InvalidTag):
            decrypt(bytes(tampered))

    def test_truncated_ciphertext_raises(self) -> None:
        """Truncated ciphertext raises an error."""
        encrypted = encrypt("some data")
        with pytest.raises((InvalidTag, ValueError)):
            decrypt(encrypted[:10])


class TestGenerateKeyHex:
    """Test key generation utility."""

    def test_generates_64_hex_chars(self) -> None:
        """Generated key is 64 hex characters (32 bytes)."""
        key = generate_key_hex()
        assert len(key) == 64
        # Verify it's valid hex
        bytes.fromhex(key)

    def test_generates_unique_keys(self) -> None:
        """Each call produces a different key."""
        key_1 = generate_key_hex()
        key_2 = generate_key_hex()
        assert key_1 != key_2


class TestProductionKeyRequirement:
    """Test that production requires a proper key."""

    def test_production_without_key_raises(self) -> None:
        """Production mode without AES_ENCRYPTION_KEY raises ValueError."""
        with (
            patch("app.services.encryption.settings") as mock_settings,
        ):
            mock_settings.AES_ENCRYPTION_KEY = ""
            mock_settings.is_production = True
            with pytest.raises(ValueError, match="must be set in production"):
                encrypt("test")

    def test_wrong_key_length_raises(self) -> None:
        """Key with wrong length raises ValueError."""
        with patch("app.services.encryption.settings") as mock_settings:
            mock_settings.AES_ENCRYPTION_KEY = "aabb"  # Only 2 bytes
            mock_settings.is_production = False
            with pytest.raises(ValueError, match="must be 32 bytes"):
                encrypt("test")


class TestSecurityProperties:
    """Security-focused tests."""

    def test_plaintext_not_in_ciphertext(self) -> None:
        """The plaintext string should not appear in the ciphertext bytes."""
        plaintext = "Warfarin 5mg daily"
        encrypted = encrypt(plaintext)
        assert plaintext.encode("utf-8") not in encrypted

    def test_injection_attempt_encrypts_safely(self) -> None:
        """SQL injection strings are encrypted like any other data."""
        injection = "'; DROP TABLE medications; --"
        encrypted = encrypt(injection)
        assert decrypt(encrypted) == injection
        assert injection.encode("utf-8") not in encrypted
