"""Настройки игрового сервера из админки: параметры sv.* и ротация карт, плюс команды серверу.

Хранятся в базе (таблица settings). Игровой сервер (gameserver/selfhost_admin.py) раз в полминуты шлёт
бэкенду своё состояние (/selfhost/status: карта, игроки, текущие значения sv.*), получает в ответ номер
версии настроек и команды; если версия новая — забирает /selfhost/serverconfig и применяет на ходу.
"""

import json
import re
import threading
import time

from .config import RES_DIR

# (ключ sv.*, тип, подпись, мин, макс). Список ключей должен совпадать с SETTINGS в selfhost_admin.py.
FIELDS = [
    ("serverName", "str", "Название сервера", None, None),
    ("password", "str", "Пароль на вход (пусто — без пароля)", None, None),
    ("welcomeMessage", "str", "Приветствие в чате", None, None),
    ("maxPlayers", "int", "Игроков максимум (после перезапуска сервера)", 2, 64),
    ("numPlayersNeededToStart", "int", "Игроков, чтобы начать раунд", 0, 64),
    ("ticketRatio", "int", "Тикеты, % от стандарта", 10, 1000),
    ("timeLimit", "int", "Лимит времени раунда, сек (0 — без лимита)", 0, 36000),
    ("roundsPerMap", "int", "Раундов на одной карте", 1, 10),
    ("spawnTime", "int", "Время возрождения, сек", 0, 120),
    ("manDownTime", "int", "Сколько ждать медика, сек", 0, 120),
    ("soldierFriendlyFire", "int", "Огонь по своим — пехота, %", 0, 100),
    ("vehicleFriendlyFire", "int", "Огонь по своим — техника, %", 0, 100),
    ("soldierSplashFriendlyFire", "int", "Взрывы по своим — пехота, %", 0, 100),
    ("vehicleSplashFriendlyFire", "int", "Взрывы по своим — техника, %", 0, 100),
    ("tkPunishEnabled", "bool", "Наказание за убийство своих", None, None),
    ("tkNumPunishToKick", "int", "Наказаний до кика", 1, 20),
    ("tkPunishByDefault", "bool", "Наказывать, даже если жертва не просила", None, None),
    ("autoBalanceTeam", "bool", "Автобаланс команд", None, None),
    ("teamRatioPercent", "int", "Соотношение команд, %", 50, 200),
    ("votingEnabled", "bool", "Голосования (кик, смена карты)", None, None),
    ("minPlayersForVoting", "int", "Игроков для голосования", 1, 64),
    ("allowFreeCam", "bool", "Свободная камера после смерти", None, None),
    ("allowExternalViews", "bool", "Вид от третьего лица в технике", None, None),
    ("allowNoseCam", "bool", "Камера «из носа» техники", None, None),
    ("hitIndicator", "bool", "Индикатор попаданий", None, None),
    ("allowTitanMovement", "bool", "Титаны двигаются", None, None),
    ("botSkill", "float", "Сложность ботов (0–1, кооп)", 0, 1),
    ("startDelay", "int", "Задержка перед стартом раунда, сек", 0, 300),
    ("endDelay", "int", "Пауза после раунда, сек", 0, 300),
]
FIELD = {f[0]: f for f in FIELDS}
MODES = {
    "gpm_cq": "Завоевание", "gpm_ti": "Титан", "gpm_coop": "Кооператив с ботами", "gpm_sl": "Контроль",
    "gpm_nv": "Только пехота", "gpm_ca": "Завоевание: штурм", "gpm_ctf": "Захват флага",
    "gpm_tdm": "Командный бой",
}
LEVELS: dict[str, dict[str, list[int]]] = json.loads((RES_DIR / "levels.json").read_text(encoding="utf-8"))["levels"]
COMMANDS = {"next_map", "restart_map", "kick", "say"}
STATUS_TTL = 90  # сек: дольше нет вестей — сервер считается выключенным


def _clean_text(value) -> str:
    """Строки идут в консоль сервера в кавычках: без кавычек, переводов строк и не длиннее 120 символов."""
    return re.sub(r'["\r\n\t\\]', "", str(value)).strip()[:120]


def validate_settings(values: dict) -> dict:
    result = {}
    for key, value in values.items():
        field = FIELD.get(key)
        if field is None:
            raise ValueError(f"неизвестная настройка {key}")
        _, kind, label, lo, hi = field
        if kind == "str":
            text = _clean_text(value)
            if any(not 0x20 <= ord(ch) < 0x7F for ch in text):
                raise ValueError(f"«{label}»: только латиница, цифры и обычные знаки — "
                                 "кириллицу игра в списке серверов и чате не покажет")
            result[key] = text
            continue
        if kind == "bool":
            result[key] = 1 if value in (True, 1, "1", "true", "on") else 0
            continue
        try:
            number = float(value) if kind == "float" else int(value)
        except (TypeError, ValueError):
            raise ValueError(f"«{label}»: нужно число") from None
        if not lo <= number <= hi:
            raise ValueError(f"«{label}»: от {lo} до {hi}")
        result[key] = number
    return result


def validate_maplist(entries: list) -> list[list]:
    result = []
    for e in entries:
        name, mode, size = str(e[0]), str(e[1]), int(e[2])
        if size not in LEVELS.get(name, {}).get(mode, []):
            raise ValueError(f"карта {name}: нет режима {mode} на {size} игроков")
        result.append([name, mode, size])
    if not result:
        raise ValueError("ротация карт не может быть пустой")
    return result


def con_value(key, value) -> str:
    return f'"{value}"' if FIELD[key][1] == "str" else str(value)


class ServerConfig:
    """Настройки в базе + команды и последнее состояние сервера в памяти."""

    def __init__(self, db):
        self.db = db
        self.lock = threading.Lock()
        self.commands: list[str] = []
        self.status: dict = {}
        self.status_at = 0.0

    def load(self) -> dict:
        raw = self.db.get_setting("server_config")
        return json.loads(raw) if raw else {"version": 0, "settings": {}, "maplist": None}

    def save(self, settings=None, maplist=None) -> int:
        with self.lock:
            cfg = self.load()
            if settings is not None:
                cfg["settings"].update(validate_settings(settings))
            if maplist is not None:
                cfg["maplist"] = validate_maplist(maplist)
            cfg["version"] += 1
            self.db.set_setting("server_config", json.dumps(cfg, ensure_ascii=False))
            return cfg["version"]

    def config_lines(self) -> str:
        """Ответ /selfhost/serverconfig: команды консоли сервера, по одной в строке."""
        cfg = self.load()
        lines = [f"version={cfg['version']}"]
        lines += [f"sv.{k} {con_value(k, v)}" for k, v in cfg["settings"].items() if k in FIELD]
        if cfg["maplist"]:
            lines.append("mapList.clear")
            lines += [f"mapList.append {n} {m} {s}" for n, m, s in cfg["maplist"]]
        return "\n".join(lines) + "\n"

    def queue(self, command: str, arg: str = ""):
        if command not in COMMANDS:
            raise ValueError("неизвестная команда")
        with self.lock:
            self.commands.append(f"{command} {_clean_text(arg)}".strip())

    def take_commands(self) -> list[str]:
        with self.lock:
            taken, self.commands = self.commands, []
            return taken

    def update_status(self, text: str, server_ip: str):
        """Тело /selfhost/status: ключ=значение по строкам, игроки — player=индекс\\tимя\\tpid\\t…"""
        status = {"ip": server_ip, "settings": {}, "players": []}
        for line in text.splitlines():
            key, _, value = line.partition("=")
            if key == "player":
                parts = value.split("\t")
                if len(parts) >= 8:
                    idx, name, pid, team, score, kills, deaths, ping = parts[:8]
                    status["players"].append({"index": int(idx), "name": name, "pid": int(pid), "team": int(team),
                                              "score": int(score), "kills": int(kills), "deaths": int(deaths),
                                              "ping": int(ping)})
            elif key.startswith("sv."):
                status["settings"][key[3:]] = value
            elif key:
                status[key] = value
        with self.lock:
            self.status, self.status_at = status, time.time()

    def current_status(self) -> dict | None:
        with self.lock:
            if not self.status or time.time() - self.status_at > STATUS_TTL:
                return None
            return dict(self.status, age=int(time.time() - self.status_at))
