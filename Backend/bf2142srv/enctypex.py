"""GameSpy enctypeX — шифр ответа мастер-сервера со списком серверов.

Порт алгоритма из enctypex_decoder (Luigi Auriemma, GPL-2), в виде,
нужном серверу: шифрование ответа и (для самотеста) расшифровка.
"""

import os


def _func5(key: bytearray, cnt: int, ident: bytes, state: list) -> int:
    if not cnt:
        return 0
    mask = 1
    while mask < cnt:
        mask = (mask << 1) + 1
    i = 0
    while True:
        state[0] = key[state[0] & 0xFF] + ident[state[1]]
        state[1] += 1
        if state[1] >= len(ident):
            state[1] = 0
            state[0] += len(ident)
        tmp = state[0] & mask
        i += 1
        if i > 11:
            tmp %= cnt
        if tmp <= cnt:
            return tmp


def _func4(ident: bytes) -> bytearray:
    key = bytearray(range(256)) + bytearray(5)
    state = [0, 0]  # n1, n2
    for i in range(255, -1, -1):
        t1 = _func5(key, i, ident, state) & 0xFF
        key[i], key[t1] = key[t1], key[i]
    key[256], key[257], key[258], key[259] = key[1], key[3], key[5], key[7]
    key[260] = key[state[0] & 0xFF]
    return key


def _step(k: bytearray, d: int, encrypt: bool) -> int:
    a = k[256]
    b = k[257]
    c = k[a]
    k[256] = (a + 1) & 0xFF
    k[257] = (b + c) & 0xFF
    a = k[260]
    b = k[k[257]]
    c = k[a]
    k[a] = b
    a = k[k[259]]
    k[k[257]] = a
    a = k[k[256]]
    k[k[259]] = a
    k[k[256]] = c
    b = (k[258] + k[c]) & 0xFF
    k[258] = b
    a = b
    c = k[k[259]]
    b = k[k[257]]
    a = k[a]
    c = (c + b) & 0xFF
    b = k[k[260]]
    c = (c + b) & 0xFF
    b = k[c]
    c = k[k[256]]
    a = (a + c) & 0xFF
    c = k[b]
    b = k[a]
    if encrypt:
        c ^= b ^ d
        k[260] = c
        k[259] = d
    else:
        k[260] = d
        c ^= b ^ d
        k[259] = c
    return c


class EnctypeX:
    """Состояние потокового шифра для одного соединения с клиентом."""

    def __init__(self, gamekey: bytes, validate: bytes, server_challenge: bytes):
        v = bytearray(validate[:8].ljust(8, b"\0"))
        for i, ch in enumerate(server_challenge):
            v[(gamekey[i % len(gamekey)] * i) & 7] ^= v[i & 7] ^ ch
        self.key = _func4(bytes(v))

    def encrypt(self, data: bytes) -> bytes:
        return bytes(_step(self.key, d, True) for d in data)

    def decrypt(self, data: bytes) -> bytes:
        return bytes(_step(self.key, d, False) for d in data)


def make_header() -> tuple[bytes, bytes]:
    """Незашифрованный заголовок ответа: случайный блок + challenge сервера (14 байт)."""
    random_part = os.urandom(7)
    challenge = os.urandom(14)
    header = bytes([7 ^ 0xEC]) + random_part + bytes([14 ^ 0xEA]) + challenge
    return header, challenge


def split_header(data: bytes) -> tuple[bytes, bytes]:
    """Для клиента/самотеста: (challenge сервера, зашифрованная часть)."""
    a = (data[0] ^ 0xEC) + 2
    b = data[a - 1] ^ 0xEA
    return data[a:a + b], data[a + b:]
