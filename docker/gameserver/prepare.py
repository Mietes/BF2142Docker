"""Готовит файлы игрового сервера при сборке Docker-образа.

1. Адреса GameSpy в бинарнике -> «backend» (имя контейнера бэкенда в сети docker compose): статистика игроков,
   регистрация в списке серверов. Внутренний адрес не зависит от IP хоста, поэтому патч делается один раз здесь.
2. Наши модули selfhost.py (итоги раунда) и selfhost_admin.py (админ-команды, баны, кик за бездействие) и их
   запуск из python/bf2/__init__.py — как install_server.py на Windows.
3. Настройки и список карт по умолчанию (их можно заменить файлами в папке config — см. entrypoint.sh).
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, "/build/Backend")
sys.path.insert(0, "/build/Backend/tools")
import install_server  # noqa: E402
import patch_server  # noqa: E402

SRV = Path("/srv/bf2142")
MOD = SRV / "mods" / "project_remaster_v17"
HERE = Path(__file__).resolve().parent

if not (SRV / "bin" / "amd-64" / "bf2142").exists() or not MOD.exists():
    sys.exit("В server-files нет Linux-сервера или Remaster — собери их: tools/build_server_files.py (см. DEPLOY.md)")

print("1) адреса GameSpy -> backend")
patch_server.patch_linux(SRV / "bin" / "amd-64" / "bf2142", "backend", 80)
(SRV / "bin" / "amd-64" / "bf2142.orig").unlink()

print("2) модули статистики и администрирования")
stats = SRV / "python" / "bf2" / "stats"
for name in install_server.MODULES:
    shutil.copy2(Path("/build/Backend/gameserver") / name, stats / name)
install_server.install_hook(SRV / "python" / "bf2" / "__init__.py")

print("3) настройки по умолчанию")
shutil.copy2(HERE / "serversettings.con", MOD / "settings" / "selfhost.con")
shutil.copy2(HERE / "maplist.con", MOD / "settings" / "selfhost_maplist.con")
install_server.check_settings(MOD / "settings" / "selfhost.con")

for p in [SRV / "start.sh", *(SRV / "bin" / "amd-64").iterdir()]:
    p.chmod(0o755)
print("готово")
