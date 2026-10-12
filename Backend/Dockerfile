# Бэкенд BF2142: вход (FESL), профиль (GPCM), статистика/звания/анлоки (HTTP), список серверов, веб-админка.
FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bf2142srv ./bf2142srv
COPY tools/accounts.py tools/selftest.py ./tools/

# Изменяемые данные (база, журнал, ключи FESL, снимки раундов) — в томе /data.
# Настройки — переменными окружения BF2142_* (см. .env.example) и, по желанию, файлом /data/config.toml.
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    BF2142_DATA_DIR=/data \
    BF2142_CONFIG=/data/config.toml \
    BF2142_BIND=0.0.0.0 \
    BF2142_ADMIN_WEB_BIND=0.0.0.0 \
    BF2142_LAN_ADDRESSES=false
VOLUME ["/data"]

# 18300 FESL, 29900 GPCM, 80 статистика, 28910 список серверов, 8142 админка (tcp); 27900 мастер-сервер (udp).
EXPOSE 18300/tcp 29900/tcp 80/tcp 28910/tcp 8142/tcp 27900/udp
CMD ["python", "-m", "bf2142srv"]
