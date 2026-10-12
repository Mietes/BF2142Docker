"""Расшифровка параметра auth= в запросах статистики (*.aspx).

Токен — один блок AES-128-ECB с фиксированным ключом из клиента EA,
закодированный в base64 с заменой "+/=" на "[]_".
Внутри (little-endian): время (u32), срок жизни (u32), pid (u32),
флаг «запрос от сервера» (u16), контрольная сумма (u16).
"""

import base64
import struct
import time
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KEY = bytes.fromhex("4CBB56AA780000C365FFEF4423122C2C")
_TO_STD = str.maketrans("[]_", "+/=")
_FROM_STD = str.maketrans("+/=", "[]_")


@dataclass
class AuthToken:
    timestamp: int
    lifetime: int
    pid: int
    is_server: bool
    crc: int


def _cipher():
    return Cipher(algorithms.AES(KEY), modes.ECB())


def decode(token: str) -> AuthToken | None:
    try:
        raw = base64.b64decode(token.translate(_TO_STD))
        if len(raw) != 16:
            return None
        dec = _cipher().decryptor()
        plain = dec.update(raw) + dec.finalize()
    except ValueError:
        return None
    ts, lifetime, pid, server, crc = struct.unpack("<IIIHH", plain)
    return AuthToken(ts, lifetime, pid, server == 1, crc)


def encode(pid: int, is_server: bool = False, lifetime: int = 120) -> str:
    """Собрать токен (нужно только для самотеста — игра делает это сама)."""
    plain = struct.pack("<IIIHH", int(time.time()), lifetime, pid, 1 if is_server else 0, 0)
    enc = _cipher().encryptor()
    raw = enc.update(plain) + enc.finalize()
    return base64.b64encode(raw).decode().translate(_FROM_STD)
