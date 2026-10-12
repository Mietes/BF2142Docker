"""Собирает файлы игрового сервера для Docker: Linux-сервер BF2142 1.51 + серверная часть Project Remaster v17.

    .venv\\Scripts\\python.exe tools\\build_server_files.py --linuxded bf2142-linuxded-1.10.112.0-installer.sh
           [--remaster <сервер>\\mods\\Project_Remaster_v17] [--out ..\\server-files] [--tar ..\\bf2142-server-files.tar.gz]

--linuxded — установщик Linux-сервера (.sh от DICE; .rar с ним внутри распакуй заранее). Скрипт его не запускает:
полезная нагрузка вырезается из файла, её MD5 сверяется с записанной в заголовке, потом проверяется MD5 самого
бинарника. --remaster — серверная копия мода (по умолчанию из [paths] server).

Linux-сервер ищет файлы только в нижнем регистре, поэтому имена в моде переводятся в нижний регистр
(кроме .py — как lowercaseDir.py от DICE). Наши файлы (selfhost*.py, патч адресов, настройки) сюда не входят —
их добавляет Dockerfile игрового сервера. В архив идёт только 64-битная сборка (bin/amd-64).
"""

import argparse
import hashlib
import io
import re
import shutil
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bf2142srv import config  # noqa: E402

import patch_server  # noqa: E402

MOD = "Project_Remaster_v17"
# Лишнее из пакета DICE: 32-битная сборка, PunkBuster (мёртв), документация.
SKIP_TOP = {"bin/ia-32", "pb_ia-32", "pb_amd-64", "readmes", "license.sh"}
# Лишнее из серверной копии мода: журналы и наши локальные настройки Windows-сервера.
SKIP_MOD = {"logs", "settings/selfhost.con", "settings/selfhost_maplist.con"}


def read_makeself(installer: Path) -> bytes:
    """Полезная нагрузка makeself-установщика (tar.gz) без запуска скрипта, с проверкой MD5 из заголовка."""
    data = installer.read_bytes()
    head = data[:16384].decode("latin-1", "replace")
    m_size = re.search(r'filesizes="(\d+)"', head)
    m_md5 = re.search(r'MD5="([0-9a-f]{32})"', head)
    m_label = re.search(r'label="([^"]*)"', head)
    if not (m_size and m_md5):
        sys.exit(f"{installer.name}: это не makeself-установщик Linux-сервера")
    payload = data[-int(m_size.group(1)):]
    if hashlib.md5(payload).hexdigest() != m_md5.group(1):
        sys.exit(f"{installer.name}: MD5 нагрузки не совпадает с заголовком — файл повреждён")
    print(f"установщик: {m_label.group(1) if m_label else installer.name}, нагрузка цела (MD5 {m_md5.group(1)})")
    return payload


def lower_path(rel: str) -> str:
    parts = rel.split("/")
    return "/".join(p if (i == len(parts) - 1 and p.endswith(".py")) else p.lower() for i, p in enumerate(parts))


def main():
    cfg = config.load()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--linuxded", type=Path, required=True, help="bf2142-linuxded-1.10.112.0-installer.sh")
    ap.add_argument("--remaster", type=Path, default=cfg.server_dir / "mods" / MOD)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[2] / "server-files")
    ap.add_argument("--tar", type=Path, default=None, help="ещё и упаковать в .tar.gz для передачи")
    args = ap.parse_args()
    if not (args.remaster / "ServerArchives.con").exists():
        sys.exit(f"Не похоже на серверную копию Remaster: {args.remaster}")
    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)

    files = 0
    with tarfile.open(fileobj=io.BytesIO(read_makeself(args.linuxded)), mode="r:gz") as tf:
        for member in tf.getmembers():
            rel = member.name.lstrip("./")
            if not rel or any(rel == s or rel.startswith(s + "/") for s in SKIP_TOP):
                continue
            if member.isdir():
                (args.out / rel).mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target = args.out / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tf.extractfile(member).read())
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
                files += 1
    binary = args.out / "bin" / "amd-64" / "bf2142"
    if hashlib.md5(binary.read_bytes()).hexdigest() not in patch_server.LINUX_MD5:
        sys.exit("bin/amd-64/bf2142 не совпадает с Linux-сервером 1.51 — отмена.")
    print(f"Linux-сервер: {files} файлов")

    mod_out = args.out / "mods" / MOD.lower()
    mod_files = 0
    for src in sorted(args.remaster.rglob("*")):
        rel = src.relative_to(args.remaster).as_posix()
        low = lower_path(rel)
        if any(low == s or low.startswith(s + "/") for s in SKIP_MOD):
            continue
        dst = mod_out / low
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            mod_files += 1
    print(f"Remaster: {mod_files} файлов -> mods/{MOD.lower()}")

    total = sum(p.stat().st_size for p in args.out.rglob("*") if p.is_file())
    print(f"готово: {args.out} ({total / 2**20:.0f} МБ)")
    if args.tar:
        with tarfile.open(args.tar, "w:gz", compresslevel=6) as tf:
            tf.add(args.out, arcname="server-files")
        digest = hashlib.sha256(args.tar.read_bytes()).hexdigest()
        print(f"архив: {args.tar} ({args.tar.stat().st_size / 2**20:.0f} МБ), SHA256 {digest}")


if __name__ == "__main__":
    main()
