# Развёртывание на Linux-сервере (Docker)

## Что нужно

- Linux **x86_64** (`uname -m` → `x86_64`; на ARM игровой сервер 2006 года не запустится).
- Docker Engine с плагином compose (`docker compose version`).
- ~2 ГБ на диске, ~1 ГБ RAM.
- Архив файлов сервера `bf2142-server-files.tar.gz` (~550 МБ) — его даёт администратор проекта
  (в git не лежит: это файлы EA и Project Remaster).

## Установка

```bash
git clone <адрес репозитория> bf2142 && cd bf2142
tar -xzf /путь/к/bf2142-server-files.tar.gz      # появится папка server-files/
cp .env.example .env && nano .env                # заполнить, см. ниже
docker compose up -d --build                     # первая сборка — несколько минут
```

В `.env`:

| Переменная | Что вписать |
|---|---|
| `BF2142_PUBLIC_HOST` | внешний IP сервера — его же игроки вписывают в установщик игры |
| `BF2142_SERVER_SECRET` | случайная строка: `openssl rand -hex 24` |
| `BF2142_ADMINS` | солдаты-админы через запятую (команды `!kick`/`!ban` в чате) |
| `BF2142_STATS_PORT` | 80; если занят — например 8080, тогда игроки вписывают адрес как `IP:8080` |

## Порты (открыть в файрволе)

| Порт | Для чего |
|---|---|
| TCP 18300, 29900, 28910 и `BF2142_STATS_PORT` (80) | вход, профиль, список серверов, звания/Штаб |
| UDP 27900 | мастер-сервер (регистрация серверов) |
| UDP 17567, 29900 | сама игра и запросы к серверу |

Пример для ufw: `ufw allow 18300,29900,28910,80/tcp && ufw allow 27900,17567,29900/udp`.
TCP 8142 (админка) открывать **не нужно** — она доступна только с самого сервера.

## Проверка

```bash
docker compose ps                                            # оба контейнера running
docker compose logs backend | tail                           # «бэкенд запущен», «новый сервер …»
docker compose exec backend python tools/selftest.py backend 80   # «ИТОГ: всё работает»
cat logs/selfhost.log                                        # «stats module ready», «round started»
```

## Управление

- **Админка** (игроки, звания, анлоки, награды, баны, пароли) — через ssh-туннель с любого ПК:
  `ssh -N -L 9142:127.0.0.1:8142 user@сервер`, затем в браузере http://127.0.0.1:9142/.
  Ключ только для туннеля, без доступа к оболочке — строка в `~/.ssh/authorized_keys`:
  `restrict,port-forwarding,permitopen="127.0.0.1:8142" ssh-ed25519 AAAA… имя`.
- **В игре**: админы из `BF2142_ADMINS` пишут в чат `!kick ник [причина]`, `!ban ник [30m|12h|7d|perm]`,
  `!unban солдат`, `!help`.
- **Консоль**: `docker compose exec backend python tools/accounts.py list | ban | unban | passwd …`.
- **Название, пароль сервера, карты**: `mkdir -p config && cp docker/gameserver/serversettings.con
  docker/gameserver/maplist.con config/`, поправить, `docker compose restart gameserver`.
- **Перезапуск / остановка**: `docker compose restart` / `docker compose down` (данные сохраняются).

## Данные и бэкапы

Всё важное — в `./data` (база игроков `bf2142.sqlite3`, ключи FESL, журнал). Бэкап на ходу:

```bash
docker compose exec backend python -c "import sqlite3; s=sqlite3.connect('/data/bf2142.sqlite3'); s.backup(sqlite3.connect('/data/backup.sqlite3'))"
cp data/backup.sqlite3 ~/bf2142-backup-$(date +%F).sqlite3
```

## Обновление

```bash
git pull && docker compose up -d --build
```

## Если что-то не так

| Симптом | Где смотреть |
|---|---|
| в игре вечное «Connecting» | открыт ли TCP 18300; `BF2142_PUBLIC_HOST` = IP из установщика игрока |
| сервера нет во вкладке «Интернет» | UDP 27900 и 29900, TCP 28910; `docker compose logs backend` |
| сервер виден, но не заходит | UDP 17567 |
| Штаб пустой, звания не грузятся | TCP `BF2142_STATS_PORT`; адрес в установщике с этим портом |
| опыт за раунд не засчитан | `logs/selfhost.log`; одинаковый `BF2142_SERVER_SECRET`; раунд ≥ 1 минуты |
| gameserver сразу выходит | есть ли `server-files/`; `tty: true` в compose (без терминала сервер не стартует) |
