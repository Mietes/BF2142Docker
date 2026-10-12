"""Собирает комплект для игроков: dist\\BF2142_Selfhost_Kit\\ и такой же .zip.

    .venv\\Scripts\\python.exe tools\\build_kit.py [--address IP[:порт]]

--address сразу впишет адрес сервера в server.txt комплекта; без него игрок впишет адрес сам
(или установщик спросит). Перед сборкой должен быть установлен патч Штаба (build_hq_patch.py):
комплект берёт из игры его архивы и исправленную локализацию. Секрет сервера, база и настройки
бэкенда в комплект не попадают.
"""

import argparse
import hashlib
import re
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bf2142srv import config  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
GAME = config.load().game_dir  # [paths] game в config.toml
REMASTER = GAME / "mods" / "Project_Remaster_v17"
KIT_SRC = BACKEND / "kit"
DIST = BACKEND / "dist"
NAME = "BF2142_Selfhost_Kit"
ZIPS = ("Menu_selfhost_hq_server.zip", "Menu_selfhost_hq_client.zip")
ADDRESS_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?")


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--address", default="", help="адрес сервера для server.txt: IP или IP:порт")
    args = ap.parse_args()
    if args.address and not ADDRESS_RE.fullmatch(args.address):
        sys.exit(f"Неверный адрес {args.address!r}: нужен IPv4 или IPv4:порт")

    strings = REMASTER / "Localization" / "strings.csv"
    original = REMASTER / "Localization" / "strings.csv.selfhost_orig"
    missing = [p for p in [original, *(REMASTER / "Objects" / z for z in ZIPS)] if not p.exists()]
    if missing:
        sys.exit("Патч Штаба не установлен (нет " + ", ".join(p.name for p in missing) + "). "
                 "Сначала: .venv\\Scripts\\python.exe tools\\build_hq_patch.py")

    out = DIST / NAME
    if out.exists():
        shutil.rmtree(out)
    files = out / "files"
    files.mkdir(parents=True)

    for name in ("INSTALL.bat", "UNINSTALL.bat"):
        shutil.copy2(KIT_SRC / name, out / name)
    shutil.copy2(KIT_SRC / "README_PLAYERS.txt", out / "README.txt")
    server_txt = (KIT_SRC / "server.txt").read_text(encoding="utf-8")
    if args.address:
        server_txt = re.sub(r"(?m)^address =.*$", f"address = {args.address}", server_txt)
    (out / "server.txt").write_text(server_txt, encoding="utf-8")

    shutil.copy2(KIT_SRC / "install.ps1", files / "install.ps1")
    shutil.copy2(KIT_SRC / "launch_bf2142.ps1", files / "launch_bf2142.ps1")
    for name in ZIPS:
        shutil.copy2(REMASTER / "Objects" / name, files / name)
    shutil.copy2(strings, files / "strings.csv")
    # Установщик сверяет версию Remaster игрока с той, под которую собран патч.
    (files / "remaster.md5").write_text(
        f"menu_server={md5(REMASTER / 'Objects' / 'Menu_server.zip')}\n"
        f"strings_original={md5(original)}\n"
        f"strings_patched={md5(strings)}\n", encoding="ascii")

    archive = DIST / f"{NAME}.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                zf.write(path, Path(NAME) / path.relative_to(out))

    print(f"Комплект: {out}")
    for path in sorted(out.rglob("*")):
        if path.is_file():
            print(f"  {path.relative_to(out)}  ({path.stat().st_size // 1024} КБ)")
    print(f"Архив: {archive} ({archive.stat().st_size // 1024} КБ)")
    print(f"Адрес в server.txt: {args.address or '(пусто — игрок впишет или установщик спросит)'}")


if __name__ == "__main__":
    main()
