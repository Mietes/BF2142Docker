# Игровой сервер BF2142 1.51 (Linux, 64 бита) + Project Remaster v17 + наши модули статистики и админки.
# Контекст сборки — корень репозитория; файлы сервера (папка server-files) в git не входят — см. DEPLOY.md.

# --- подготовка: адреса GameSpy -> контейнер бэкенда, наши Python-модули, настройки ---
FROM python:3.14-slim AS build
COPY Backend/bf2142srv /build/Backend/bf2142srv
COPY Backend/tools/patch_server.py Backend/tools/install_server.py /build/Backend/tools/
COPY Backend/gameserver /build/Backend/gameserver
COPY docker/gameserver /build/docker
COPY server-files /srv/bf2142
RUN python /build/docker/prepare.py

# --- запуск ---
FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends libncurses5 libstdc++6 zlib1g \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /srv/bf2142 /srv/bf2142
COPY docker/gameserver/entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh
WORKDIR /srv/bf2142
# 17567 — игра, 29900 — запросы к серверу (пинг, игроки в списке серверов).
EXPOSE 17567/udp 29900/udp
VOLUME ["/logs"]
ENTRYPOINT ["/entrypoint.sh"]
