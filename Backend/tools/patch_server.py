"""Перенаправляет дедик-сервер BF2142 1.51 на твой бэкенд: статистика/анлоки игроков и
регистрация сервера в списке (мастер-сервер).

    .venv\\Scripts\\python.exe tools\\patch_server.py [адрес-бэкенда] [--http-port 80]
           [--exe <сервер>\\BF2142_w32ded.exe | <сервер>/bin/amd-64/bf2142]

Windows-сервер (BF2142_w32ded.exe): адрес — IPv4, папка по умолчанию — [paths] server из config.toml.
Linux-сервер (ELF bin/amd-64/bf2142): адрес — IPv4 или имя хоста (в Docker — «backend»): строки GameSpy
ищутся по содержимому.

Перед первой правкой сохраняется копия *.orig; патч всегда накладывается на неё, поэтому его можно
повторять с другим адресом.
"""

import argparse
import hashlib
import ipaddress
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bf2142srv import config  # noqa: E402

ORIGINAL_MD5 = "2380c7bc967f96aff1fbf83ce1b9390d"  # BF2142_w32ded.exe 1.51 (Windows)
# bin/amd-64/bf2142 и bin/ia-32/bf2142 из bf2142-linuxded-1.10.112.0 (1.51)
LINUX_MD5 = {"ce720cbf34cf11460a69eaaae50dc917": "amd-64", "9e9368e3ee5ffc0a533048685456cb8c": "ia-32"}
LINUX_STRINGS = {  # строка в бинарнике -> что писать
    "http://stella.prod.gamespy.com/": "url",
    "stella.prod.gamespy.com": "host",
    "%s.master.gamespy.com": "host",
    "%s.available.gamespy.com": "host",
    "gamestats.gamespy.com": "host",
}
HOSTNAME_RE = re.compile(r"[a-z0-9]([a-z0-9-]{0,62})(\.[a-z0-9]([a-z0-9-]{0,62}))*")


def check_host(host: str, allow_name: bool):
    try:
        ipaddress.IPv4Address(host)
        return
    except ValueError:
        pass
    if not allow_name or not HOSTNAME_RE.fullmatch(host):
        sys.exit(f"Неверный адрес бэкенда {host!r}: нужен IPv4" + (" или имя хоста" if allow_name else ""))


def patch_linux(binary: Path, host: str, http_port: int):
    """Linux-сервер: каждая строка GameSpy встречается в .rodata ровно один раз — заменяем по содержимому."""
    check_host(host, allow_name=True)
    backup = binary.with_name(binary.name + ".orig")
    if not backup.exists():
        shutil.copy2(binary, backup)
        print(f"Копия оригинала: {backup}")
    data = bytearray(backup.read_bytes())
    arch = LINUX_MD5.get(hashlib.md5(data).hexdigest())
    if arch is None:
        sys.exit(f"{backup.name} не совпадает с Linux-сервером BF2142 1.51 (1.10.112.0) — отмена.")
    url = f"http://{host}/" if http_port == 80 else f"http://{host}:{http_port}/"
    for old, kind in LINUX_STRINGS.items():
        needle = b"\0" + old.encode() + b"\0"
        found = [m.start() + 1 for m in re.finditer(re.escape(needle), bytes(data))]
        if len(found) != 1:
            sys.exit(f"Строка {old!r} найдена {len(found)} раз(а), ожидалась одна — отмена.")
        new = url if kind == "url" else host
        if len(new) > len(old):
            sys.exit(f"Не помещается: {new!r} вместо {old!r}")
        off = found[0]
        data[off:off + len(old) + 1] = new.encode().ljust(len(old) + 1, b"\0")
        print(f"  0x{off:06X}: {old} -> {new}")
    if binary.read_bytes() == data:
        print(f"Уже пропатчен на этот адрес: {binary} ({arch})")
        return
    binary.write_bytes(data)
    binary.chmod(0o755)
    print(f"Пропатчен: {binary} ({arch})")

# смещение -> (исходная строка, что писать: "url" или "host")
SLOTS = {
    0x3CE610: ("http://stella.prod.gamespy.com/", "url"),
    0x4059C8: ("%s.master.gamespy.com", "host"),
    0x405A60: ("%s.available.gamespy.com", "host"),
    0x43AD30: ("gamestats.gamespy.com", "host"),
}


def patch(exe: Path, host: str, http_port: int):
    with exe.open("rb") as f:
        if f.read(4) == b"\x7fELF":
            return patch_linux(exe, host, http_port)
    check_host(host, allow_name=False)
    backup = exe.with_name(exe.name + ".orig")
    if not backup.exists():
        shutil.copy2(exe, backup)
        print(f"Копия оригинала: {backup}")
    data = bytearray(backup.read_bytes())
    if hashlib.md5(data).hexdigest() != ORIGINAL_MD5:
        sys.exit(f"{backup.name} не совпадает с оригинальным BF2142_w32ded.exe 1.51 — отмена.")

    for off, (old, kind) in SLOTS.items():
        assert data[off:off + len(old) + 1] == old.encode() + b"\0"
        if kind == "url":
            new = f"http://{host}/" if http_port == 80 else f"http://{host}:{http_port}/"
        else:
            new = host
        if len(new) > len(old):
            sys.exit(f"Не помещается: {new!r}")
        data[off:off + len(old) + 1] = new.encode().ljust(len(old) + 1, b"\0")
        print(f"  0x{off:06X}: {old} -> {new}")

    # 4 ГБ памяти вместо 2 (флаг Large Address Aware) — на случай больших карт Remaster с ботами.
    pe = int.from_bytes(data[0x3C:0x40], "little")
    flags = int.from_bytes(data[pe + 22:pe + 24], "little") | 0x0020
    data[pe + 22:pe + 24] = flags.to_bytes(2, "little")
    print("  Large Address Aware: включён")

    if exe.read_bytes() == data:
        print(f"Уже пропатчен на этот адрес: {exe}")
        return
    exe.write_bytes(data)
    print(f"Пропатчен: {exe}")


def main():
    cfg = config.load()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host", nargs="?", default=cfg.public_host,
                    help="адрес бэкенда: IPv4 (для Linux-сервера — и имя хоста); по умолчанию public_host из config.toml")
    ap.add_argument("--http-port", type=int, default=cfg.http_port)
    ap.add_argument("--exe", type=Path, default=cfg.server_dir / "BF2142_w32ded.exe")
    args = ap.parse_args()
    patch(args.exe, args.host, args.http_port)


if __name__ == "__main__":
    main()
