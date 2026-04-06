"""AES-256 field-level encryption for sensitive health data.

Encrypts medication names, dosages, conversation content, and other
PII before persistence to PostgreSQL. Decrypts on read.

Uses AES-GCM (authenticated encryption) via the cryptography library.
"""

import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

# 96-bit nonce for AES-GCM (NIST recommendation)
_NONCE_LENGTH = 12


def _get_key() -> bytes:
    """Get the AES-256 encryption key from settings.

    Returns:
        32-byte key for AES-256.

    Raises:
        ValueError: If the key is not configured or has wrong length.
    """
    hex_key = settings.AES_ENCRYPTION_KEY
    if not hex_key:
        # In development, generate a deterministic key from a fixed seed
        # In production, this MUST be set via environment variable
        if settings.is_production:
            msg = "AES_ENCRYPTION_KEY must be set in production"
            raise ValueError(msg)
        # Development fallback — NOT for production use
        return b"medbuddy-dev-key-not-for-prod!!!"  # exactly 32 bytes

    key_bytes = bytes.fromhex(hex_key)
    if len(key_bytes) != 32:
        msg = f"AES_ENCRYPTION_KEY must be 32 bytes (64 hex chars), got {len(key_bytes)}"
        raise ValueError(msg)
    return key_bytes


def encrypt(plaintext: str) -> bytes:
    """Encrypt a string using AES-256-GCM.

    Args:
        plaintext: The string to encrypt.

    Returns:
        Bytes containing nonce + ciphertext + tag (concatenated).
    """
    if not plaintext:
        return b""

    key = _get_key()
    nonce = secrets.token_bytes(_NONCE_LENGTH)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)

    # nonce (12 bytes) + ciphertext + GCM tag (16 bytes, appended by AESGCM)
    return nonce + ciphertext


def decrypt(encrypted_data: bytes) -> str:
    """Decrypt AES-256-GCM encrypted data.

    Args:
        encrypted_data: Bytes containing nonce + ciphertext + tag.

    Returns:
        The decrypted string.

    Raises:
        cryptography.exceptions.InvalidTag: If data has been tampered with.
    """
    if not encrypted_data:
        return ""

    key = _get_key()
    nonce = encrypted_data[:_NONCE_LENGTH]
    ciphertext = encrypted_data[_NONCE_LENGTH:]
    aesgcm = AESGCM(key)
    plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)

    return plaintext_bytes.decode("utf-8")


def generate_key_hex() -> str:
    """Generate a random AES-256 key as a hex string.

    Use this to generate a key for the AES_ENCRYPTION_KEY setting:
        python -c "from app.services.encryption import generate_key_hex; print(generate_key_hex())"
    """
    return os.urandom(32).hex()
