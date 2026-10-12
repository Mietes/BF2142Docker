"""Подключает дедик-сервер BF2142 к бэкенду:

1. патчит BF2142_w32ded.exe (адрес статистики и мастер-сервера);
2. ставит модули python/bf2/stats/selfhost*.py (итоги раунда, админ-команды, баны, кик за
   бездействие) и selfhost_config.py с адресом бэкенда и секретом для подписи запросов;
3. добавляет его запуск в python/bf2/__init__.py;
4. проверяет настройки сервера Remaster (Settings/selfhost.con и selfhost_maplist.con; если их нет —
   делает из стандартных ServerSettings.con/maplist.con): глобальные ранги и анлоки включены;
5. создаёт start_server.bat (Project Remaster v17 с этими настройками).

    .venv\\Scripts\\python.exe tools\\install_server.py [IP-бэкенда] [--http-port 80]
           [--server <папка сервера>]

Папка сервера по умолчанию — [paths] server из config.toml.

Повторный запуск безопасен (например, чтобы сменить IP). Оригиналы: *.orig.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bf2142srv import config  # noqa: E402

import patch_server  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
MOD = "Project_Remaster_v17"
SETTINGS = f"mods/{MOD}/Settings/selfhost.con"
MAPLIST = f"mods/{MOD}/Settings/selfhost_maplist.con"

MODULES = ("selfhost.py", "selfhost_admin.py")
ANCHOR = '\t\tbf2.stats.endofround.init()'
# Встроенный Python сервера урезан (нет полноценного os), поэтому traceback
# здесь использовать нельзя: он сам падает и роняет init_module целиком.
HOOK = (
    "\n\n\t# self-hosted backend: round stats -> rank progression\n"
    "\ttry:\n"
    "\t\timport bf2.stats.selfhost\n"
    "\t\tbf2.stats.selfhost.init()\n"
    "\texcept:\n"
    "\t\t_e = sys.exc_info()\n"
    '\t\tprint "Selfhost stats module failed to load: %s %s" % (_e[0], _e[1])\n'
    "\t\ttry:\n"
    '\t\t\t_f = open("selfhost_error.log", "a")\n'
    '\t\t\t_f.write("%s %s\\n" % (_e[0], _e[1]))\n'
    "\t\t\t_f.close()\n"
    "\t\texcept:\n"
    "\t\t\tpass"
)
START_BAT = f"""@echo off
rem Игровой сервер BF2142: Project Remaster v17, настройки {SETTINGS}, карты {MAPLIST}
cd /d "%~dp0"
start "" BF2142_w32ded.exe +modPath mods/{MOD} +config {SETTINGS} +mapList {MAPLIST}
"""


def backup(path: Path):
    orig = path.with_name(path.name + ".orig")
    if not orig.exists():
        shutil.copy2(path, orig)


def install_hook(init_py: Path):
    backup(init_py)
    text = init_py.with_name(init_py.name + ".orig").read_bytes().decode("latin-1")
    newline = "\r\n" if "\r\n" in text else "\n"
    anchor = ANCHOR.replace("\n", newline)
    if "bf2.stats.selfhost" in text or text.count(anchor) != 1:
        sys.exit(f"Не найдено место для вставки в {init_py} — файл не стандартный, отмена.")
    text = text.replace(anchor, anchor + HOOK.replace("\n", newline))
    init_py.write_bytes(text.encode("latin-1"))
    print(f"  {init_py.name}: добавлен запуск bf2.stats.selfhost")


def ensure_settings(srv: Path):
    """Свои файлы настроек сервера; при первом запуске — копии стандартных файлов Remaster."""
    for ours, stock in ((SETTINGS, f"mods/{MOD}/Settings/ServerSettings.con"),
                        (MAPLIST, f"mods/{MOD}/Settings/maplist.con")):
        if not (srv / ours).exists():
            shutil.copy2(srv / stock, srv / ours)
            print(f"  {ours}: создан из {Path(stock).name}")
    check_settings(srv / SETTINGS)


def check_settings(settings: Path):
    text = settings.read_text(encoding="latin-1")
    changed = text
    for key in ("sv.useGlobalRank", "sv.useGlobalUnlocks"):
        changed = re.sub(rf"^{re.escape(key)}\s+\S+", f"{key} 1", changed, flags=re.M | re.I)
        if not re.search(rf"^{re.escape(key)}\s", changed, flags=re.M | re.I):
            changed += f"\n{key} 1\n"
    if changed != text:
        backup(settings)
        settings.write_text(changed, encoding="latin-1")
        print(f"  {settings.name}: включены sv.useGlobalRank/sv.useGlobalUnlocks")
    else:
        print(f"  {settings.name}: sv.useGlobalRank/sv.useGlobalUnlocks уже включены")


def main():
    cfg = config.load()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host", nargs="?", default=cfg.public_host, help="IPv4 бэкенда, видимый с игрового сервера")
    ap.add_argument("--http-port", type=int, default=cfg.http_port)
    ap.add_argument("--server", type=Path, default=cfg.server_dir)
    args = ap.parse_args()
    srv = args.server

    print("1) exe сервера:")
    patch_server.patch(srv / "BF2142_w32ded.exe", args.host, args.http_port)

    print("2) модули статистики и администрирования:")
    stats_dir = srv / "python" / "bf2" / "stats"
    for name in MODULES:
        shutil.copy2(BACKEND_DIR / "gameserver" / name, stats_dir / name)
    # SECRET подписывает запросы к бэкенду: без него итоги раунда и админ-команды не примут.
    (stats_dir / "selfhost_config.py").write_text(
        f'BACKEND_HOST = "{args.host}"\nBACKEND_PORT = {args.http_port}\nSECRET = "{cfg.server_secret}"\n',
        encoding="ascii")
    print(f"  {', '.join(MODULES)} -> бэкенд {args.host}:{args.http_port}, секрет для подписи прописан")

    print("3) запуск модуля:")
    install_hook(srv / "python" / "bf2" / "__init__.py")

    print("4) настройки сервера:")
    ensure_settings(srv)

    print("5) start_server.bat:")
    (srv / "start_server.bat").write_text(START_BAT, encoding="cp866")
    print(f"  {srv / 'start_server.bat'}")
    print("\nГотово.")


if __name__ == "__main__":
    main()
