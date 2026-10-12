"""Делает копию BF2142.exe (1.51, уже без проверки SSL-сертификата), которая
ходит за логином, статистикой и списком серверов на твой бэкенд.

    .venv\\Scripts\\python.exe tools\\patch_client.py [IP-бэкенда] [--http-port 80]
           [--exe <игра>\\BF2142.exe] [--out <игра>\\BF2142_selfhost.exe]

Папка игры по умолчанию — [paths] game из config.toml. Оригинальный exe не изменяется.
"""

import argparse
import hashlib
import ipaddress
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bf2142srv import config  # noqa: E402

# Смещения строк в BF2142.exe 1.51 и сколько символов там безопасно писать
# (длина исходной строки ванильного exe).
SLOTS = {
    0x5639A4: 31,  # http://stella.prod.gamespy.com/   — статистика
    0x5639C4: 23,  # stella.prod.gamespy.com
    0x563CC4: 0,   # URL новостей — не длиннее текущей строки
    0x59E6E8: 24,  # %s.available.gamespy.com         — проверка доступности
    0x59E938: 37,  # http://motd.gamespy.com/motd/motd.asp
    0x59F608: 19,  # %s.ms%d.gamespy.com              — список серверов
    0x6067A0: 63,  # gamestats.gamespy.com
    0x607180: 63,  # gpcm.gamespy.com (по нему же резолвится FESL)
    0x6071C0: 63,  # gpsp.gamespy.com
}
# Проверка «есть ли интернет» (код по VA 0x488062): gethostbyname(<этот домен>) и gethostbyname("ea.com").
# Сборка вписала сюда свой домен вместо EA — возвращаем "ea.com", чтобы игра не спрашивала DNS о чужом
# сервере и не зависела от того, жив ли он.
DNS_CHECK_OFFSET = 0x524824
DNS_CHECK_HOST = "ea.com"
SSL_CHECK_OFFSET = 0x45FE8D
SSL_CHECK_PATCHED = bytes.fromhex("B815000000")
IMAGE_FILE_LARGE_ADDRESS_AWARE = 0x0020


def set_large_address_aware(data: bytearray):
    """32-битной игре без этого флага доступно лишь 2 ГБ памяти — Remaster с HD-текстурами
    в них не помещается и падает в RendDX9.dll при загрузке карты. С флагом — 4 ГБ."""
    pe = int.from_bytes(data[0x3C:0x40], "little")
    pos = pe + 22  # IMAGE_FILE_HEADER.Characteristics
    flags = int.from_bytes(data[pos:pos + 2], "little") | IMAGE_FILE_LARGE_ADDRESS_AWARE
    data[pos:pos + 2] = flags.to_bytes(2, "little")


def read_cstr(data: bytes, off: int) -> bytes:
    return data[off:data.index(b"\0", off)]


def main():
    cfg = config.load()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host", nargs="?", default=cfg.public_host, help="IPv4 бэкенда (по умолчанию public_host из config.toml)")
    ap.add_argument("--http-port", type=int, default=cfg.http_port)
    ap.add_argument("--exe", type=Path, default=cfg.game_dir / "BF2142.exe")
    ap.add_argument("--out", type=Path, default=cfg.game_dir / "BF2142_selfhost.exe")
    args = ap.parse_args()

    ipaddress.IPv4Address(args.host)  # только IPv4: влезает во все слоты
    data = bytearray(args.exe.read_bytes())

    if data[SSL_CHECK_OFFSET:SSL_CHECK_OFFSET + 5] != SSL_CHECK_PATCHED:
        sys.exit("В этом exe не снята проверка SSL-сертификата (ожидался exe 1.51 из репака). Отмена.")
    old_host = read_cstr(data, 0x607180).decode("ascii")
    if not old_host or "%" in old_host:
        sys.exit(f"Неожиданное содержимое слота GPCM: {old_host!r}. Отмена.")

    host_port = args.host if args.http_port == 80 else f"{args.host}:{args.http_port}"
    for off, cap in SLOTS.items():
        old = read_cstr(data, off).decode("ascii")
        if old_host not in old:
            sys.exit(f"Слот 0x{off:X} содержит {old!r}, а не {old_host!r}. Это другой exe — отмена.")
        new = old.replace(old_host, host_port if old.startswith("http://") else args.host)
        end = off + len(old)
        while data[end] == 0:
            end += 1
        limit = min(max(cap, len(old)), end - off - 1)  # не залезать за нулевой хвост строки
        if len(new) > limit:
            new = old.replace(old_host, args.host)  # новости без порта — не критично
        if len(new) > limit:
            sys.exit(f"Не помещается в слот 0x{off:X}: {new!r}")
        data[off:off + limit + 1] = new.encode("ascii").ljust(limit + 1, b"\0")
        print(f"  0x{off:06X}: -> {new}")

    dns = read_cstr(data, DNS_CHECK_OFFSET).decode("ascii")
    if dns != DNS_CHECK_HOST:
        if not dns or not old_host.endswith(dns) or len(dns) < len(DNS_CHECK_HOST):
            sys.exit(f"Неожиданная строка проверки интернета по 0x{DNS_CHECK_OFFSET:X}: {dns!r}. Это другой exe — отмена.")
        data[DNS_CHECK_OFFSET:DNS_CHECK_OFFSET + len(dns) + 1] = DNS_CHECK_HOST.encode("ascii").ljust(len(dns) + 1, b"\0")
    print(f"  0x{DNS_CHECK_OFFSET:06X}: проверка интернета -> {DNS_CHECK_HOST}")

    set_large_address_aware(data)
    print("  Large Address Aware: включён (4 ГБ памяти вместо 2)")

    args.out.write_bytes(data)
    print(f"\nГотово: {args.out}\nMD5: {hashlib.md5(data).hexdigest()}")


if __name__ == "__main__":
    main()
