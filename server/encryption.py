from typing import Optional

from cryptography.fernet import Fernet

_fernet: Optional[Fernet] = None
_current_key: Optional[str] = None


def encrypt_string(secret: str, value: str) -> str:
    global _current_key, _fernet
    if _current_key != secret:
        _current_key = secret
        _fernet = Fernet(secret.encode())
    encrypted = _fernet.encrypt(value.encode())
    return encrypted.decode()


def decode_string(secret: str, value: str):
    global _current_key, _fernet
    if _current_key != secret:
        _current_key = secret
        _fernet = Fernet(secret.encode())
    decrypted = _fernet.decrypt(value.encode())
    return decrypted.decode()
