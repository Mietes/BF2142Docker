"""Загрузка config.toml с значениями по умолчанию."""

import os
import secrets
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# Изменяемые данные (база, журнал, ключи FESL, секрет, снимки раундов). В Docker — том /data.
DATA_DIR = Path(os.environ.get("BF2142_DATA_DIR") or BASE_DIR / "data")
# Неизменяемые справочники (условия наград, колонки статистики) — часть кода.
RES_DIR = Path(__file__).resolve().parent / "res"


@dataclass
class Config:
    bind: str = "0.0.0.0"
    public_host: str = "127.0.0.1"
    # Отдавать игрокам из той же сети, что и игровой сервер, его локальный адрес (дома за роутером).
    # В Docker выключено: частные адреса там — внутренняя сеть контейнеров.
    lan_addresses: bool = True
    fesl_port: int = 18300
    gpcm_port: int = 29900
    available_port: int = 27900
    sb_port: int = 28910
    http_port: int = 80
    auto_register: bool = True
    max_soldiers: int = 4
    unlock_mode: str = "progression"
    start_credits: int = 3
    # Очки анлоков за звания: (с какого звания, по какое, очков за каждое).
    credits_schedule: list = field(default_factory=lambda: [(1, 10, 2), (11, 37, 1)])
    squad_gadgets: bool = False
    northern_strike: bool = True
    count_coop: bool = True
    min_round_seconds: int = 60
    win_bonus: float = 0.2
    first_win_multiplier: float = 2.0
    coop_multiplier: float = 0.5
    day_starts_hour: int = 4
    awards: bool = True
    # Бонусный опыт за награду: значок по уровням (бронза, серебро, золото), медаль, лента, значок отличия.
    award_xp_badge: list = field(default_factory=lambda: [20, 100, 250])
    award_xp_medal: int = 150
    award_xp_ribbon: int = 100
    award_xp_pin: int = 10
    weekly_top: bool = True
    weekly_top_min_rank: int = 40
    # Игровые серверы: общий секрет для подписи запросов и (необязательно) их адреса.
    server_secret: str = ""
    server_ips: list = field(default_factory=list)
    # Администрирование: имена солдат-админов (команды в чате) и кик за бездействие (0 — выключен).
    admins: list = field(default_factory=list)
    idle_kick_minutes: int = 5
    admin_web_port: int = 8142  # веб-админка (0 — выключена)
    admin_web_bind: str = "127.0.0.1"  # в Docker 0.0.0.0, а наружу порт публикуется только на 127.0.0.1 хоста
    log_level: str = "INFO"
    db_path: Path = field(default_factory=lambda: DATA_DIR / "bf2142.sqlite3")
    # Папки игры (клиента) и дедик-сервера — для утилит (патч exe, патч Штаба, комплект, установка сервера).
    game_dir: Path = field(default_factory=lambda: BASE_DIR.parent.parent / "BF2142 Remaster")
    server_dir: Path = field(default_factory=lambda: BASE_DIR.parent / "GameServer")


def server_secret() -> str:
    """Секрет для подписи запросов игровых серверов: data/server_secret.txt, создаётся при первом запуске."""
    path = DATA_DIR / "server_secret.txt"
    if not path.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(24) + "\n", encoding="ascii")
    return path.read_text(encoding="ascii").strip()


# Переменные окружения поверх config.toml — так настраивается контейнер (файл .env у docker compose).
ENV_OVERRIDES = {
    "BF2142_PUBLIC_HOST": ("public_host", str),
    "BF2142_BIND": ("bind", str),
    "BF2142_HTTP_PORT": ("http_port", int),
    "BF2142_SERVER_SECRET": ("server_secret", str),
    "BF2142_AUTO_REGISTER": ("auto_register", lambda v: v.strip().lower() in ("1", "true", "yes")),
    "BF2142_ADMIN_WEB_BIND": ("admin_web_bind", str),
    "BF2142_ADMIN_WEB_PORT": ("admin_web_port", int),
    "BF2142_LOG_LEVEL": ("log_level", lambda v: v.strip().upper()),
    "BF2142_LAN_ADDRESSES": ("lan_addresses", lambda v: v.strip().lower() in ("1", "true", "yes")),
}


def apply_env(cfg: "Config"):
    for var, (attr, conv) in ENV_OVERRIDES.items():
        value = os.environ.get(var, "").strip()
        if value:
            setattr(cfg, attr, conv(value))
    admins = os.environ.get("BF2142_ADMINS", "").strip()
    if admins:  # солдаты-админы через запятую
        cfg.admins = [a.strip() for a in admins.split(",") if a.strip()]


def load(path: Path | None = None) -> Config:
    path = path or Path(os.environ.get("BF2142_CONFIG", BASE_DIR / "config.toml"))
    raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    storage = raw.get("storage", {})
    net = raw.get("network", {})
    ports = raw.get("ports", {})
    acc = raw.get("accounts", {})
    unl = raw.get("unlocks", {})
    content = raw.get("content", {})
    st = raw.get("stats", {})
    xp = raw.get("xp", {})
    ranks = raw.get("ranks", {})
    aw = raw.get("awards", {})
    srv = raw.get("servers", {})
    adm = raw.get("admin", {})
    log = raw.get("logging", {})
    paths = raw.get("paths", {})

    schedule = unl.get("credits_per_rank", [[1, 10, 2], [11, 37, 1]])
    if isinstance(schedule, int):  # старый формат: одно число на каждое звание
        schedule = [[1, 40, schedule]]

    cfg = Config(
        bind=net.get("bind", "0.0.0.0"),
        public_host=net.get("public_host", "127.0.0.1"),
        lan_addresses=net.get("lan_addresses", True),
        fesl_port=ports.get("fesl", 18300),
        gpcm_port=ports.get("gpcm", 29900),
        available_port=ports.get("available", 27900),
        sb_port=ports.get("server_browser", 28910),
        http_port=ports.get("http", 80),
        auto_register=acc.get("auto_register", True),
        max_soldiers=acc.get("max_soldiers", 4),
        unlock_mode=unl.get("mode", "progression"),
        start_credits=unl.get("start_credits", 3),
        credits_schedule=[tuple(int(x) for x in row) for row in schedule],
        squad_gadgets=unl.get("squad_gadgets", False),
        northern_strike=content.get("northern_strike", True),
        count_coop=st.get("count_coop", True),
        min_round_seconds=st.get("min_round_seconds", 60),
        win_bonus=float(xp.get("win_bonus", 0.2)),
        first_win_multiplier=float(xp.get("first_win_multiplier", 2.0)),
        coop_multiplier=float(xp.get("coop_multiplier", 0.5)),
        day_starts_hour=int(xp.get("day_starts_hour", 4)),
        awards=aw.get("enabled", True),
        award_xp_badge=[int(x) for x in aw.get("xp_badge", [20, 100, 250])],
        award_xp_medal=int(aw.get("xp_medal", 150)),
        award_xp_ribbon=int(aw.get("xp_ribbon", 100)),
        award_xp_pin=int(aw.get("xp_pin", 10)),
        weekly_top=ranks.get("weekly_top", True),
        weekly_top_min_rank=int(ranks.get("weekly_top_min_rank", 40)),
        server_secret=srv.get("secret") or server_secret(),
        server_ips=[str(x) for x in srv.get("allowed_ips", [])],
        admins=[str(x) for x in adm.get("admins", [])],
        idle_kick_minutes=int(adm.get("idle_kick_minutes", 5)),
        admin_web_port=int(adm.get("web_port", 8142)),
        admin_web_bind=adm.get("web_bind", "127.0.0.1"),
        log_level=log.get("level", "INFO").upper(),
    )
    if "db" in storage:
        cfg.db_path = (BASE_DIR / storage["db"]).resolve()
    apply_env(cfg)
    if paths.get("game"):
        cfg.game_dir = (BASE_DIR / paths["game"]).resolve()  # абсолютный путь остаётся как есть
    if paths.get("server"):
        cfg.server_dir = (BASE_DIR / paths["server"]).resolve()
    if cfg.unlock_mode not in ("all", "progression"):
        raise ValueError(f'unlocks.mode должен быть "all" или "progression", а не {cfg.unlock_mode!r}')
    return cfg
