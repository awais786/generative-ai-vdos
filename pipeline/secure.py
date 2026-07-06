import os
from functools import lru_cache

from cryptography.fernet import Fernet, MultiFernet


@lru_cache(maxsize=1)
def get_fernet() -> MultiFernet | Fernet:
    keys = os.environ.get("FIELD_ENCRYPTION_KEY", "")
    parts = [k.strip() for k in keys.split(",") if k.strip()]
    if not parts:
        raise RuntimeError(
            "FIELD_ENCRYPTION_KEY is not set. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    if len(parts) == 1:
        return Fernet(parts[0].encode())
    return MultiFernet([Fernet(k.encode()) for k in parts])


def encrypt_string(plaintext: str) -> bytes:
    return get_fernet().encrypt(plaintext.encode())


class SecureString:
    __slots__ = ("_enc", "api_url")

    def __init__(self, encrypted_bytes: bytes, api_url: str | None = None):
        self._enc = encrypted_bytes
        self.api_url = api_url

    def decrypt(self) -> str:
        return get_fernet().decrypt(self._enc).decode()

    def __str__(self):
        return "••••••••"

    def __repr__(self):
        return "SecureString(••••)"

    def __len__(self):
        raise TypeError("SecureString does not expose length")

    def __eq__(self, other):
        if isinstance(other, str):
            raise TypeError("Cannot compare SecureString with plaintext")
        return isinstance(other, SecureString) and self._enc == other._enc

    def __hash__(self):
        return hash(self._enc)

    def __bool__(self):
        return bool(self._enc)

    def __reduce__(self):
        raise TypeError("SecureString cannot be pickled")

    def __reduce_ex__(self, protocol):
        raise TypeError("SecureString cannot be pickled")
