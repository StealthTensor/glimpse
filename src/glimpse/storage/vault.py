"""
Encrypted Biometric Vault storage module for Glimpse.
Secures 512-d feature templates using AES-256-GCM.
Never writes raw camera images to disk.
"""

from __future__ import annotations
import os
import json
import base64
import logging
from pathlib import Path
from typing import Dict, List, Optional
import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("glimpse.storage.vault")

class BiometricVault:
    """Manages encrypted biometric vector templates for local users."""

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir:
            self.vault_dir = Path(base_dir)
        else:
            # If running as root, use system /var/lib/glimpse; else user config
            if os.geteuid() == 0:
                self.vault_dir = Path("/var/lib/glimpse/vault")
            else:
                self.vault_dir = Path.home() / ".local" / "share" / "glimpse" / "vault"

        self.vault_dir.mkdir(parents=True, exist_ok=True)
        # Enforce secure directory permissions: 0700 (owner only)
        try:
            os.chmod(self.vault_dir, 0o700)
        except OSError:
            pass

        self.key_file = self.vault_dir / "vault.key"
        self._aesgcm = self._load_or_create_key()

    def _load_or_create_key(self) -> AESGCM:
        """Load 256-bit AES-GCM key or generate new one."""
        if self.key_file.exists():
            key = self.key_file.read_bytes()
        else:
            key = AESGCM.generate_key(bit_length=256)
            self.key_file.write_bytes(key)
            try:
                os.chmod(self.key_file, 0o600)
            except OSError:
                pass
            logger.info(f"Generated new AES-256 master key at {self.key_file}")

        return AESGCM(key)

    def _user_file(self, username: str) -> Path:
        # Sanitize username for safe filesystem path
        safe_user = "".join(c for c in username if c.isalnum() or c in ("-", "_"))
        return self.vault_dir / f"{safe_user}.enc"

    def save_templates(self, username: str, vectors: List[np.ndarray]) -> bool:
        """
        Encrypt and persist user templates to disk.
        Vectors: list of 1D numpy arrays.
        """
        user_file = self._user_file(username)
        raw_data = {
            "username": username,
            "count": len(vectors),
            "templates": [v.astype(np.float32).tolist() for v in vectors]
        }
        json_bytes = json.dumps(raw_data).encode("utf-8")

        # 12-byte nonce for AES-GCM
        nonce = os.urandom(12)
        encrypted_data = self._aesgcm.encrypt(nonce, json_bytes, None)

        # Store as: [12 bytes nonce] + [ciphertext + tag]
        payload = nonce + encrypted_data
        user_file.write_bytes(payload)
        try:
            os.chmod(user_file, 0o600)
        except OSError:
            pass

        logger.info(f"Securely saved {len(vectors)} biometric templates for user '{username}' to {user_file}")
        return True

    def load_templates(self, username: str) -> List[np.ndarray]:
        """
        Decrypt and return user's enrolled biometric vector templates.
        Checks system vault, and falls back to user home vault if running privileged.
        """
        user_file = self._user_file(username)
        aesgcm = self._aesgcm

        # Fallback to user home vault if running as root and not found in system vault
        if not user_file.exists() and os.geteuid() == 0:
            import pwd
            try:
                pw = pwd.getpwnam(username)
                safe_user = "".join(c for c in username if c.isalnum() or c in ("-", "_"))
                fallback_file = Path(pw.pw_dir) / ".local" / "share" / "glimpse" / "vault" / f"{safe_user}.enc"
                fallback_key = Path(pw.pw_dir) / ".local" / "share" / "glimpse" / "vault" / "vault.key"
                if fallback_file.exists() and fallback_key.exists():
                    user_file = fallback_file
                    aesgcm = AESGCM(fallback_key.read_bytes())
            except Exception as e:
                logger.debug(f"User vault fallback lookup failed for '{username}': {e}")

        if not user_file.exists():
            logger.debug(f"No biometric enrollment found for user '{username}' at {user_file}")
            return []

        payload = user_file.read_bytes()
        if len(payload) < 28: # 12 nonce + 16 min tag
            logger.error(f"Corrupted vault file for user '{username}'")
            return []

        nonce = payload[:12]
        ciphertext = payload[12:]

        try:
            decrypted = aesgcm.decrypt(nonce, ciphertext, None)
            data = json.loads(decrypted.decode("utf-8"))
            vectors = [np.array(v, dtype=np.float32) for v in data.get("templates", [])]
            return vectors
        except Exception as e:
            logger.error(f"Failed to decrypt biometric templates for user '{username}': {e}")
            return []

    def delete_user(self, username: str) -> bool:
        """Purge enrolled templates for a user."""
        user_file = self._user_file(username)
        if user_file.exists():
            user_file.unlink()
            logger.info(f"Purged biometric enrollment for user '{username}'")
            return True
        return False
