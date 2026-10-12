"""Собирает установщик игры для игроков (Inno Setup): setup.exe + setup-1.bin, setup-2.bin ...

    .venv\\Scripts\\python.exe tools\\build_release.py [--address IP[:порт]] [--version 1.0] [--out ПАПКА]

Берёт игру из [paths] game (config.toml) — она уже должна быть с патчем Штаба (build_hq_patch.py).
Сценарий установщика — installer\\bf2142.iss. --address впишет адрес сервера в мастер заранее (игрок
сможет его поменять). По умолчанию результат — папка «BF2142 Build» рядом с папкой игры.
Нужен Inno Setup 6 (ISCC.exe). Секрет сервера, база и config.toml в установщик не попадают.
"""

import argparse
import hashlib
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bf2142srv import config  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
INSTALLER = BACKEND / "installer"
ISCC_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
]
ADDRESS_RE = re.compile(r"(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?::(\d{1,5}))?")
RT_ICON, RT_GROUP_ICON = 3, 14


def extract_icon(exe: Path, out: Path):
    """Первая группа иконок из ресурсов exe -> .ico (для значка setup.exe)."""
    d = exe.read_bytes()
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    optsz = struct.unpack_from("<H", d, pe + 20)[0]
    opt = pe + 24
    rsrc_rva = struct.unpack_from("<I", d, opt + 96 + 8 * 2)[0]
    secs = [struct.unpack_from("<IIII", d, opt + optsz + 40 * i + 8) for i in range(nsec)]

    def r2o(rva):
        for vs, va, rs, raw in secs:
            if va <= rva < va + max(vs, rs):
                return raw + rva - va
        raise ValueError(f"RVA {rva:#x} вне секций")

    base = r2o(rsrc_rva)

    def entries(off):
        named, ids = struct.unpack_from("<HH", d, off + 12)
        for i in range(named + ids):
            name, target = struct.unpack_from("<II", d, off + 16 + 8 * i)
            yield name, target

    def leaf(target):
        """Спуск по подкаталогам до первого листа: (данные)."""
        while target & 0x80000000:
            target = next(entries(base + (target & 0x7FFFFFFF)))[1]
        rva, size = struct.unpack_from("<II", d, base + target)
        return d[r2o(rva):r2o(rva) + size]

    by_type = {name: target for name, target in entries(base)}
    icons = {name: leaf(t) for name, t in entries(base + (by_type[RT_ICON] & 0x7FFFFFFF))}
    group = leaf(next(entries(base + (by_type[RT_GROUP_ICON] & 0x7FFFFFFF)))[1])
    count = struct.unpack_from("<H", group, 4)[0]
    header, images, offset = struct.pack("<HHH", 0, 1, count), b"", 6 + 16 * count
    for i in range(count):
        w, h, colors, res, planes, bpp, size, icon_id = struct.unpack_from("<BBBBHHIH", group, 6 + 14 * i)
        data = icons[icon_id]
        header += struct.pack("<BBBBHHII", w, h, colors, res, planes, bpp, len(data), offset)
        images += data
        offset += len(data)
    out.write_bytes(header + images)


def check_game(game: Path):
    remaster = game / "mods" / "Project_Remaster_v17"
    need = [game / "BF2142.exe", remaster / "Objects" / "Menu_selfhost_hq_client.zip",
            remaster / "Objects" / "Menu_selfhost_hq_server.zip", remaster / "Localization" / "strings.csv.selfhost_orig"]
    missing = [str(p) for p in need if not p.exists()]
    if missing:
        sys.exit("Папка игры не готова (нет " + ", ".join(missing) + "). Нужен патч Штаба: tools\\build_hq_patch.py")
    if (game / "BF2142.exe").read_bytes()[0x45FE8D:0x45FE92] != bytes.fromhex("B815000000"):
        sys.exit("BF2142.exe не тот (ожидался 1.51 со снятой проверкой SSL).")
    for con in ("ServerArchives.con", "ClientArchives.con"):
        if "Menu_selfhost_hq_" not in (remaster / con).read_text(encoding="latin-1"):
            sys.exit(f"Патч Штаба не подключён в {con}. Запусти tools\\build_hq_patch.py")


def main():
    cfg = config.load()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--address", default="", help="адрес сервера для мастера: IP или IP:порт")
    ap.add_argument("--version", default="1.0", help="версия сборки (видна в «Приложениях»)")
    ap.add_argument("--out", type=Path, default=cfg.game_dir.parent / "BF2142 Build")
    args = ap.parse_args()
    m = ADDRESS_RE.fullmatch(args.address) if args.address else None
    if args.address and (not m or any(int(x) > 255 for x in m.groups()[:4])):
        sys.exit(f"Неверный адрес {args.address!r}: нужен IPv4 или IPv4:порт")
    iscc = next((p for p in ISCC_CANDIDATES if p.exists()), None)
    if iscc is None:
        sys.exit("Не найден Inno Setup 6 (ISCC.exe).")

    game = cfg.game_dir
    check_game(game)
    icon = INSTALLER / "bf2142.ico"
    if not icon.exists():
        extract_icon(game / "BF2142.exe", icon)
        print(f"иконка: {icon}")
    args.out.mkdir(parents=True, exist_ok=True)
    for old in list(args.out.glob("setup.exe")) + list(args.out.glob("setup-*.bin")):
        old.unlink()

    cmd = [str(iscc), "/Qp", f"/DGameDir={game}", f"/DOutDir={args.out}", f"/DServerAddress={args.address}",
           f"/DAppVersion={args.version}", str(INSTALLER / "bf2142.iss")]
    print("Сборка установщика (несколько минут: ~5 ГБ данных)...")
    result = subprocess.run(cmd, cwd=INSTALLER)
    if result.returncode != 0:
        sys.exit(f"ISCC завершился с кодом {result.returncode}")

    files = sorted(args.out.glob("setup*"))
    total = sum(p.stat().st_size for p in files)
    lines = []
    for p in files:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                h.update(chunk)
        lines.append(f"{h.hexdigest()}  {p.name}")
        print(f"  {p.name:14} {p.stat().st_size / 2**20:9.1f} МБ")
    (args.out / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="ascii")
    print(f"Готово: {args.out} — {len(files)} файл(ов), {total / 2**30:.2f} ГБ; контрольные суммы в SHA256SUMS.txt")
    print(f"Адрес в мастере: {args.address or '(пусто — игрок впишет сам)'}")


if __name__ == "__main__":
    main()
