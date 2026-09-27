"""
Passphrase encryption for instance exports, in the standard age v1 format
(https://age-encryption.org/v1): an scrypt recipient stanza plus a
ChaCha20-Poly1305 STREAM payload.

Using age rather than a home-grown format means an export can always be opened
without Nebula Commander (`age -d export.ncexport.age`), which matters for data
portability. Only the pieces of the spec needed for a single scrypt recipient
are implemented, on top of the `cryptography` package.
"""
import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

INTRO = b"age-encryption.org/v1"
SCRYPT_LABEL = b"age-encryption.org/v1/scrypt"
CHUNK = 64 * 1024
# 2^16 * r=8 * 128 bytes = 64 MiB of scrypt memory: slow enough to resist guessing, small
# enough for a memory-limited container. The age CLI decrypts anything up to 2^22.
DEFAULT_LOG_N = 16
MAX_LOG_N = 22
MIN_PASSPHRASE_LENGTH = 12


class ExportDecryptError(Exception):
    """Wrong passphrase, or the file is damaged or not an export."""


def _b64(data: bytes) -> bytes:
    return base64.b64encode(data).rstrip(b"=")


def _unb64(data: bytes) -> bytes:
    if data.endswith(b"=") or b"\n" in data or b"\r" in data:
        raise ExportDecryptError("invalid encoding")
    return base64.b64decode(data + b"=" * (-len(data) % 4), validate=True)


def _hkdf(ikm: bytes, salt: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(ikm)


def _scrypt_key(passphrase: str, salt: bytes, log_n: int) -> bytes:
    return Scrypt(salt=SCRYPT_LABEL + salt, length=32, n=2**log_n, r=8, p=1).derive(
        passphrase.encode("utf-8")
    )


def _chunk_nonce(counter: int, last: bool) -> bytes:
    return counter.to_bytes(11, "big") + (b"\x01" if last else b"\x00")


def encrypt(plaintext: bytes, passphrase: str, log_n: int = DEFAULT_LOG_N) -> bytes:
    """Encrypt plaintext to an age file protected by passphrase."""
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise ValueError(f"Passphrase must be at least {MIN_PASSPHRASE_LENGTH} characters")
    file_key = os.urandom(16)
    salt = os.urandom(16)
    wrap_key = _scrypt_key(passphrase, salt, log_n)
    body = ChaCha20Poly1305(wrap_key).encrypt(b"\x00" * 12, file_key, None)

    header = INTRO + b"\n"
    header += b"-> scrypt " + _b64(salt) + b" " + str(log_n).encode() + b"\n"
    header += _b64(body) + b"\n"  # 32 bytes -> 43 chars: always a single short line
    header += b"---"
    mac = hmac.new(_hkdf(file_key, b"", b"header"), header, hashlib.sha256).digest()
    header += b" " + _b64(mac) + b"\n"

    nonce = os.urandom(16)
    aead = ChaCha20Poly1305(_hkdf(file_key, nonce, b"payload"))
    out = [header, nonce]
    chunks = [plaintext[i : i + CHUNK] for i in range(0, len(plaintext), CHUNK)] or [b""]
    for i, chunk in enumerate(chunks):
        out.append(aead.encrypt(_chunk_nonce(i, i == len(chunks) - 1), chunk, None))
    return b"".join(out)


def decrypt(data: bytes, passphrase: str) -> bytes:
    """Decrypt an age file encrypted with a single scrypt (passphrase) recipient."""
    try:
        return _decrypt(data, passphrase)
    except ExportDecryptError:
        raise
    except (InvalidTag, ValueError, IndexError) as e:
        raise ExportDecryptError("wrong passphrase or damaged file") from e


def _decrypt(data: bytes, passphrase: str) -> bytes:
    lines = []
    pos = 0
    while True:  # header lines up to and including the "--- MAC" line
        end = data.find(b"\n", pos)
        if end < 0 or len(lines) > 64:
            raise ExportDecryptError("not an age file")
        line = data[pos:end]
        lines.append(line)
        pos = end + 1
        if line.startswith(b"---"):
            break
    if lines[0] != INTRO:
        raise ExportDecryptError("not an age v1 file")
    stanza = lines[1].split(b" ")
    if stanza[:2] != [b"->", b"scrypt"] or len(stanza) != 4:
        raise ExportDecryptError("this file is not passphrase-encrypted")
    body_lines = lines[2:-1]
    if len(body_lines) != 1 or len(lines) != 4:
        raise ExportDecryptError("unexpected header")
    salt = _unb64(stanza[2])
    if len(salt) != 16 or not stanza[3].isdigit():
        raise ExportDecryptError("invalid scrypt stanza")
    log_n = int(stanza[3])
    if not 1 <= log_n <= MAX_LOG_N:
        raise ExportDecryptError("scrypt work factor out of range")

    wrap_key = _scrypt_key(passphrase, salt, log_n)
    try:
        file_key = ChaCha20Poly1305(wrap_key).decrypt(b"\x00" * 12, _unb64(body_lines[0]), None)
    except InvalidTag as e:
        raise ExportDecryptError("wrong passphrase") from e

    mac_line = lines[-1]
    if not mac_line.startswith(b"--- "):
        raise ExportDecryptError("invalid header MAC line")
    header = b"\n".join(lines[:-1]) + b"\n---"
    expected = hmac.new(_hkdf(file_key, b"", b"header"), header, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _unb64(mac_line[4:])):
        raise ExportDecryptError("header authentication failed")

    nonce, payload = data[pos : pos + 16], data[pos + 16 :]
    if len(nonce) != 16:
        raise ExportDecryptError("truncated file")
    aead = ChaCha20Poly1305(_hkdf(file_key, nonce, b"payload"))
    size = CHUNK + 16
    out = []
    count = max(1, -(-len(payload) // size))
    for i in range(count):
        chunk = payload[i * size : (i + 1) * size]
        last = i == count - 1
        if not last and len(chunk) != size:
            raise ExportDecryptError("truncated file")
        out.append(aead.decrypt(_chunk_nonce(i, last), chunk, None))
    return b"".join(out)
