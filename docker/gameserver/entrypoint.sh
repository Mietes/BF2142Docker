#!/bin/bash
# Запуск игрового сервера BF2142 (Linux 1.51 + Project Remaster v17) в контейнере.
#   BF2142_SERVER_SECRET — общий секрет с бэкендом (подпись итогов раунда и админ-команд), обязателен.
#   /config/serversettings.con, /config/maplist.con — свои настройки и карты (если есть — заменяют встроенные).
#   /logs/selfhost.log — журнал модуля статистики и админки.
set -euo pipefail
cd /srv/bf2142

if [ -z "${BF2142_SERVER_SECRET:-}" ]; then
    echo "Не задан BF2142_SERVER_SECRET (тот же, что у бэкенда) — см. .env.example" >&2
    exit 1
fi

cat > python/bf2/stats/selfhost_config.py <<EOF
BACKEND_HOST = "${BF2142_BACKEND_HOST:-backend}"
BACKEND_PORT = ${BF2142_BACKEND_PORT:-80}
SECRET = "${BF2142_SERVER_SECRET}"
EOF

SETTINGS=mods/project_remaster_v17/settings
[ -f /config/serversettings.con ] && cp /config/serversettings.con "$SETTINGS/selfhost.con"
[ -f /config/maplist.con ] && cp /config/maplist.con "$SETTINGS/selfhost_maplist.con"

mkdir -p /logs
ln -sf /logs/selfhost.log selfhost.log

exec ./start.sh +modPath mods/project_remaster_v17 \
    +config "$SETTINGS/selfhost.con" +mapList "$SETTINGS/selfhost_maplist.con"
