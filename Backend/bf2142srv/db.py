"""SQLite-хранилище: аккаунты, солдаты, статистика, анлоки."""

import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    email         TEXT NOT NULL DEFAULT '',
    country       TEXT NOT NULL DEFAULT '',
    dob           TEXT NOT NULL DEFAULT '',
    login_token   TEXT UNIQUE,
    created       INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS soldiers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    disabled   INTEGER NOT NULL DEFAULT 0,
    created    INTEGER NOT NULL,
    last_login INTEGER NOT NULL DEFAULT 0
);
-- Статистика солдата в виде пар ключ/значение: ключи те же, что в ответах
-- getplayerinfo.aspx (crpt, rnk, klls, wkls-3 ...).
CREATE TABLE IF NOT EXISTS stats (
    pid   INTEGER NOT NULL REFERENCES soldiers(id),
    key   TEXT NOT NULL,
    value NUMERIC NOT NULL,
    PRIMARY KEY (pid, key)
);
-- Сыгранные раунды и итог каждого игрока (для графиков прогресса в BFHQ).
CREATE TABLE IF NOT EXISTS rounds (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    server_ip  TEXT NOT NULL,
    map        TEXT NOT NULL,
    game_mode  TEXT NOT NULL,
    winner     INTEGER NOT NULL,
    ai_game    INTEGER NOT NULL,
    started    INTEGER NOT NULL,
    ended      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS round_players (
    round_id INTEGER NOT NULL REFERENCES rounds(id),
    pid      INTEGER NOT NULL REFERENCES soldiers(id),
    data     TEXT NOT NULL,           -- JSON с итогами игрока за раунд
    PRIMARY KEY (round_id, pid)
);
CREATE INDEX IF NOT EXISTS round_players_pid ON round_players(pid, round_id);
-- Открытые анлоки: для ветки (kit, tree) — достигнутый уровень.
CREATE TABLE IF NOT EXISTS unlocks (
    pid   INTEGER NOT NULL REFERENCES soldiers(id),
    kit   INTEGER NOT NULL,
    tree  INTEGER NOT NULL,
    level INTEGER NOT NULL,
    PRIMARY KEY (pid, kit, tree)
);
-- Награды: значки ('100_1' — по строке на уровень), ленты ('300') — один раз; медали ('200')
-- и значки отличия ('400') — сколько угодно раз, count — сколько.
CREATE TABLE IF NOT EXISTS awards (
    pid   INTEGER NOT NULL REFERENCES soldiers(id),
    award TEXT NOT NULL,
    count INTEGER NOT NULL,
    first INTEGER NOT NULL,
    last  INTEGER NOT NULL,
    PRIMARY KEY (pid, award)
);
-- Баны: аккаунта и/или IP. until = NULL — навсегда, lifted — когда снят досрочно.
CREATE TABLE IF NOT EXISTS bans (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id),
    ip         TEXT NOT NULL DEFAULT '',
    until      INTEGER,
    reason     TEXT NOT NULL DEFAULT '',
    by         TEXT NOT NULL DEFAULT '',
    created    INTEGER NOT NULL,
    lifted     INTEGER
);
CREATE INDEX IF NOT EXISTS bans_account ON bans(account_id);
"""
# Столбцы, добавленные после первых версий: (таблица, столбец, определение).
MIGRATIONS = [("accounts", "last_ip", "TEXT NOT NULL DEFAULT ''")]


def _active_ban(alias=""):
    """Условие «бан действует» (параметр — текущее время)."""
    return f"{alias}lifted IS NULL AND ({alias}until IS NULL OR {alias}until > ?)"


# ID профиля обязан быть > 2000, иначе серверные скрипты не запросят ранг и анлоки.
FIRST_ACCOUNT_ID = 50000
FIRST_SOLDIER_ID = 10000000


class AlreadyExists(Exception):
    pass


class LimitReached(Exception):
    pass


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2$200000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    _, rounds, salt, digest = stored.split("$")
    test = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
    return hmac.compare_digest(test.hex(), digest)


def _num(value):
    """Число из SQLite -> int, если оно целое."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


class _Transaction:
    def __init__(self, db: "Database"):
        self.db = db

    def __enter__(self):
        self.db._lock.acquire()
        self.db._conn.execute("BEGIN")
        return self.db

    def __exit__(self, exc_type, exc, tb):
        try:
            self.db._conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.db._lock.release()
        return False


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)
            for table, column, definition in MIGRATIONS:
                if column not in [r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")]:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            for table, first in (("accounts", FIRST_ACCOUNT_ID), ("soldiers", FIRST_SOLDIER_ID)):
                if not self._conn.execute("SELECT 1 FROM sqlite_sequence WHERE name=?", (table,)).fetchone():
                    self._conn.execute("INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)", (table, first))

    def _one(self, sql, args=()):
        with self._lock:
            return self._conn.execute(sql, args).fetchone()

    def _all(self, sql, args=()):
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    # --- аккаунты -----------------------------------------------------------

    def create_account(self, name, password, email="", country="", dob="") -> int:
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO accounts(name, password_hash, email, country, dob, created) VALUES (?,?,?,?,?,?)",
                    (name, hash_password(password), email, country, dob, int(time.time())),
                )
            except sqlite3.IntegrityError as e:
                raise AlreadyExists(name) from e
            return cur.lastrowid

    def account_by_name(self, name):
        return self._one("SELECT * FROM accounts WHERE name=?", (name,))

    def account(self, account_id):
        return self._one("SELECT * FROM accounts WHERE id=?", (account_id,))

    def account_by_token(self, token):
        return self._one("SELECT * FROM accounts WHERE login_token=?", (token,))

    def set_login_token(self, account_id, token, ip=""):
        with self._lock:
            self._conn.execute("UPDATE accounts SET login_token=?, last_ip=? WHERE id=?", (token, ip, account_id))

    def update_account(self, account_id, email, country):
        with self._lock:
            self._conn.execute("UPDATE accounts SET email=?, country=? WHERE id=?", (email, country, account_id))

    # --- солдаты ------------------------------------------------------------

    def soldiers(self, account_id):
        return self._all("SELECT * FROM soldiers WHERE account_id=? AND disabled=0 ORDER BY id", (account_id,))

    def soldier(self, pid):
        return self._one("SELECT * FROM soldiers WHERE id=?", (pid,))

    def soldier_by_name(self, name):
        return self._one("SELECT * FROM soldiers WHERE name=? AND disabled=0", (name,))

    def create_soldier(self, account_id, name, max_soldiers) -> int:
        with self._lock:
            if len(self.soldiers(account_id)) >= max_soldiers:
                raise LimitReached(name)
            try:
                cur = self._conn.execute(
                    "INSERT INTO soldiers(account_id, name, created) VALUES (?,?,?)",
                    (account_id, name, int(time.time())),
                )
            except sqlite3.IntegrityError as e:
                raise AlreadyExists(name) from e
            return cur.lastrowid

    def disable_soldier(self, account_id, name):
        with self._lock:
            # Освобождаем имя, чтобы его можно было занять снова.
            self._conn.execute(
                "UPDATE soldiers SET disabled=1, name=name || '#' || id WHERE account_id=? AND name=? AND disabled=0",
                (account_id, name),
            )

    def delete_account(self, account_id):
        """Полное удаление аккаунта со всеми солдатами, статистикой, анлоками и наградами."""
        with self.transaction():
            pids = [r["id"] for r in self._all("SELECT id FROM soldiers WHERE account_id=?", (account_id,))]
            for pid in pids:
                for table in ("stats", "unlocks", "awards", "round_players"):
                    self._conn.execute(f"DELETE FROM {table} WHERE pid=?", (pid,))
            self._conn.execute("DELETE FROM soldiers WHERE account_id=?", (account_id,))
            self._conn.execute("DELETE FROM bans WHERE account_id=?", (account_id,))
            self._conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))

    def rename_soldier(self, pid, name):
        with self._lock:
            try:
                self._conn.execute("UPDATE soldiers SET name=? WHERE id=?", (name, pid))
            except sqlite3.IntegrityError as e:
                raise AlreadyExists(name) from e

    def touch_soldier(self, pid):
        with self._lock:
            self._conn.execute("UPDATE soldiers SET last_login=? WHERE id=?", (int(time.time()), pid))

    def search_soldiers(self, nick_prefix, limit=20):
        return self._all(
            "SELECT * FROM soldiers WHERE disabled=0 AND name LIKE ? ESCAPE '\\' ORDER BY name LIMIT ?",
            (nick_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%", limit),
        )

    def soldier_count(self) -> int:
        return self._one("SELECT COUNT(*) FROM soldiers WHERE disabled=0")[0]

    def leaderboard(self, key, offset, limit):
        return self._all(
            "SELECT s.id, s.name, COALESCE(v.value, 0) AS score, COALESCE(r.value, 0) AS rank "
            "FROM soldiers s "
            "LEFT JOIN stats v ON v.pid = s.id AND v.key = ? "
            "LEFT JOIN stats r ON r.pid = s.id AND r.key = 'rnk' "
            "WHERE s.disabled = 0 ORDER BY score DESC, s.id LIMIT ? OFFSET ?",
            (key, limit, offset),
        )

    # --- статистика ---------------------------------------------------------

    def stats(self, pid) -> dict:
        return {r["key"]: _num(r["value"]) for r in self._all("SELECT key, value FROM stats WHERE pid=?", (pid,))}

    def set_stats(self, pid, values: dict):
        with self._lock:
            self._conn.executemany(
                "INSERT INTO stats(pid, key, value) VALUES (?,?,?) "
                "ON CONFLICT(pid, key) DO UPDATE SET value=excluded.value",
                [(pid, k, v) for k, v in values.items()],
            )

    # --- раунды -------------------------------------------------------------

    def add_round(self, server_ip, map_name, game_mode, winner, ai_game, started, ended) -> int:
        with self._lock:
            return self._conn.execute(
                "INSERT INTO rounds(server_ip, map, game_mode, winner, ai_game, started, ended) VALUES (?,?,?,?,?,?,?)",
                (server_ip, map_name, game_mode, winner, ai_game, started, ended),
            ).lastrowid

    def round_exists(self, server_ip, map_name, started, ended) -> bool:
        return self._one("SELECT 1 FROM rounds WHERE server_ip=? AND map=? AND started=? AND ended=?",
                         (server_ip, map_name, started, ended)) is not None

    def add_round_player(self, round_id, pid, data: dict):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO round_players(round_id, pid, data) VALUES (?,?,?)",
                (round_id, pid, json.dumps(data)),
            )

    def round_history(self, pid, limit=20) -> list[tuple[int, dict]]:
        rows = self._all(
            "SELECT r.ended, p.data FROM round_players p JOIN rounds r ON r.id = p.round_id "
            "WHERE p.pid=? ORDER BY p.round_id DESC LIMIT ?",
            (pid, limit),
        )
        return [(r["ended"], json.loads(r["data"])) for r in reversed(rows)]

    def xp_between(self, start: int, end: int) -> list[tuple[int, float]]:
        """Опыт (с бонусами), набранный солдатами в раундах, закончившихся в [start, end)."""
        rows = self._all(
            "SELECT p.pid, SUM(json_extract(p.data, '$.round.crpt')) AS xp "
            "FROM round_players p JOIN rounds r ON r.id = p.round_id "
            "WHERE r.ended >= ? AND r.ended < ? GROUP BY p.pid ORDER BY xp DESC",
            (start, end),
        )
        return [(r["pid"], r["xp"] or 0) for r in rows]

    def transaction(self):
        """with db.transaction(): ... — несколько записей атомарно."""
        return _Transaction(self)

    # --- анлоки -------------------------------------------------------------

    def unlocks(self, pid) -> dict[tuple[int, int], int]:
        return {(r["kit"], r["tree"]): r["level"] for r in self._all("SELECT * FROM unlocks WHERE pid=?", (pid,))}

    def set_unlock(self, pid, kit, tree, level):
        with self._lock:
            self._conn.execute(
                "INSERT INTO unlocks(pid, kit, tree, level) VALUES (?,?,?,?) "
                "ON CONFLICT(pid, kit, tree) DO UPDATE SET level=excluded.level",
                (pid, kit, tree, level),
            )

    # --- награды ------------------------------------------------------------

    def awards(self, pid) -> dict[str, dict]:
        """award -> {"count", "first", "last"}."""
        return {r["award"]: {"count": r["count"], "first": r["first"], "last": r["last"]}
                for r in self._all("SELECT * FROM awards WHERE pid=? ORDER BY award", (pid,))}

    def remove_award(self, pid, award) -> bool:
        """Снять одну награду (у повторяемых — уменьшить счётчик). False, если её нет."""
        with self._lock:
            row = self._conn.execute("SELECT count FROM awards WHERE pid=? AND award=?", (pid, award)).fetchone()
            if row is None:
                return False
            if row["count"] > 1:
                self._conn.execute("UPDATE awards SET count=count-1 WHERE pid=? AND award=?", (pid, award))
            else:
                self._conn.execute("DELETE FROM awards WHERE pid=? AND award=?", (pid, award))
            return True

    def add_award(self, pid, award, when):
        with self._lock:
            self._conn.execute(
                "INSERT INTO awards(pid, award, count, first, last) VALUES (?,?,1,?,?) "
                "ON CONFLICT(pid, award) DO UPDATE SET count=count+1, last=excluded.last",
                (pid, award, when, when),
            )

    # --- баны ---------------------------------------------------------------

    def add_ban(self, account_id, minutes, reason="", by="", ip="") -> int:
        """Бан аккаунта (и IP, если указан) на minutes минут; None — навсегда."""
        now = int(time.time())
        until = None if minutes is None else now + int(minutes) * 60
        with self._lock:
            return self._conn.execute(
                "INSERT INTO bans(account_id, ip, until, reason, by, created) VALUES (?,?,?,?,?,?)",
                (account_id, ip, until, reason, by, now),
            ).lastrowid

    def lift_bans(self, account_id) -> int:
        """Снять действующие баны аккаунта (и IP-баны, выданные вместе с ними). Возвращает их число."""
        with self._lock:
            return self._conn.execute(
                f"UPDATE bans SET lifted=? WHERE account_id=? AND {_active_ban()}",
                (int(time.time()), account_id, int(time.time())),
            ).rowcount

    def active_ban(self, account_id=None, ip=""):
        """Действующий бан аккаунта или IP (самый долгий) либо None."""
        return self._one(
            f"SELECT * FROM bans WHERE {_active_ban()} AND (account_id=? OR (ip != '' AND ip=?)) "
            "ORDER BY until IS NULL DESC, until DESC LIMIT 1",
            (int(time.time()), account_id, ip or None),
        )

    def active_bans(self):
        return self._all(
            "SELECT b.*, a.name AS account FROM bans b LEFT JOIN accounts a ON a.id = b.account_id "
            f"WHERE {_active_ban('b.')} ORDER BY b.created",
            (int(time.time()),),
        )

    def banned_pids(self) -> list[int]:
        """Солдаты забаненных аккаунтов: их кикает игровой сервер."""
        return [r["id"] for r in self._all(
            "SELECT s.id FROM soldiers s JOIN bans b ON b.account_id = s.account_id "
            f"WHERE s.disabled=0 AND {_active_ban('b.')} GROUP BY s.id",
            (int(time.time()),),
        )]
