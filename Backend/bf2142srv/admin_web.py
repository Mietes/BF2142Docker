"""Админка: веб-панель http://127.0.0.1:<[admin] web_port>/ — игроки, звания, награды, анлоки, баны.

Слушает только 127.0.0.1: с других машин (в том числе из Radmin) её не видно. От чужих сайтов,
открытых в том же браузере (CSRF), защищают проверка Host и обязательный заголовок X-Admin в
запросах-изменениях: обычная ссылка или форма с другого сайта их не отправит.
Изменения пишутся прямо в базу; игрок увидит их в игре после перезахода.
"""

import json
import logging
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from . import progression, server_config
from .admin import NAME_RULE, describe_ban, valid_name
from .context import Context
from .db import AlreadyExists, hash_password

log = logging.getLogger("admin")

UI_FILE = Path(__file__).with_name("admin_ui.html")
PASSWORD_RE = re.compile(r"[A-Za-z0-9]{4,16}")  # как разрешает экран входа игры
KITS = {1: "Разведчик", 2: "Штурмовик", 3: "Инженер", 4: "Поддержка", 5: "Общие"}
TREE_NAMES = {(5, 1): "Снаряжение игрока", (5, 2): "Командир отделения"}
BADGE_LEVELS = {"1": "бронза", "2": "серебро", "3": "золото"}
LIST_STATS = ("rnk", "crpt", "gsco", "klls", "dths", "tt", "win", "los")


def load_names(game_dir: Path) -> dict[str, str]:
    """Русские названия званий, наград и анлоков из локализации Remaster (если игра на месте)."""
    path = game_dir / "mods" / "Project_Remaster_v17" / "Localization" / "strings.csv"
    try:
        rows = [line.split("\t") for line in path.read_bytes().decode("utf-16").split("\r\r\n")]
    except OSError:
        return {}
    ru = rows[0].index("Russian") if "Russian" in rows[0] else 1
    names = {}
    for r in rows[1:]:
        if r and re.match(r"(RANK_\d+|AWARD_NAME_\d+(_\d)?|NAME_UNLOCK_\d+)$", r[0]):
            text = (r[ru] if len(r) > ru and r[ru] else r[1] if len(r) > 1 else "").strip()
            names[r[0]] = text
    return names


class AdminAPI:
    def __init__(self, ctx: Context):
        self.ctx, self.cfg, self.db = ctx, ctx.cfg, ctx.db
        self.names = load_names(self.cfg.game_dir)
        self.award_ids = sorted(self._award_ids(), key=self._award_sort)

    # --- справочники ----------------------------------------------------------

    @staticmethod
    def _award_ids():
        from . import rounds  # условия наград грузит модуль раундов
        return list(rounds.criteria().keys())

    @staticmethod
    def _award_sort(award):
        base, _, level = award.partition("_")
        return int(base), level

    def award_name(self, award: str) -> str:
        name = self.names.get(f"AWARD_NAME_{award}") or f"Награда {award}"
        base, _, level = award.partition("_")
        return f"{name} ({BADGE_LEVELS[level]})" if level in BADGE_LEVELS else name

    @staticmethod
    def award_kind(award: str) -> str:
        return {"1": "badge", "2": "medal", "3": "ribbon", "4": "pin"}.get(award[0], "other")

    def rank_name(self, rank: int) -> str:
        return self.names.get(f"RANK_{rank}") or f"Звание {rank}"

    def meta(self):
        trees = []
        for (kit, tree), size in sorted(progression.TREES.items()):
            trees.append({
                "kit": kit, "tree": tree, "max": size, "kitName": KITS[kit],
                "name": TREE_NAMES.get((kit, tree), f"Ветка {tree}"),
                "items": [{"uid": f"{kit}{tree}{lvl}",
                           "name": self.names.get(f"NAME_UNLOCK_{kit}{tree}{lvl}") or f"{kit}{tree}{lvl}"}
                          for lvl in range(1, size + 1)],
            })
        return {
            "ranks": [{"rank": r, "xp": xp, "name": self.rank_name(r)} for r, xp in enumerate(progression.RANK_POINTS)],
            "awards": [{"id": a, "name": self.award_name(a), "kind": self.award_kind(a)} for a in self.award_ids],
            "trees": trees,
            "unlockMode": self.cfg.unlock_mode,
            "nameRule": NAME_RULE,
        }

    # --- игроки ---------------------------------------------------------------

    def players(self, q: str):
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stat_cols = ", ".join(f"(SELECT value FROM stats WHERE pid = s.id AND key = '{k}') AS \"{k}\""
                              for k in LIST_STATS)
        rows = self.db._all(
            f"SELECT s.id AS pid, s.name, s.created, s.last_login, a.id AS account_id, a.name AS account, {stat_cols} "
            "FROM soldiers s JOIN accounts a ON a.id = s.account_id "
            "WHERE s.disabled = 0 AND (s.name LIKE ? ESCAPE '\\' OR a.name LIKE ? ESCAPE '\\') "
            "ORDER BY s.last_login DESC, s.id DESC LIMIT 500", (like, like))
        banned = {b["account_id"] for b in self.db.active_bans()}
        result = []
        for r in rows:
            item = {k: r[k] for k in r.keys()}
            for k in LIST_STATS:
                item[k] = item[k] or 0
            item["rankName"] = self.rank_name(int(item["rnk"]))
            item["banned"] = item["account_id"] in banned
            result.append(item)
        return result

    def player(self, pid: int):
        soldier = self.db.soldier(pid)
        if soldier is None or soldier["disabled"]:
            raise LookupError("нет такого солдата")
        account = self.db.account(soldier["account_id"])
        stats = self.db.stats(pid)
        rank = int(stats.get("rnk", 0))
        levels = self.db.unlocks(pid)
        earned = progression.earned_credits(self.cfg, rank)
        spent = progression.spent_credits(levels)
        ban = self.db.active_ban(account["id"])
        awards = self.db.awards(pid)
        history = []
        for ended, data in reversed(self.db.round_history(pid, 15)):
            history.append({
                "ended": ended, "xp": data.get("round", {}).get("crpt", 0), "raw": data.get("raw_xp"),
                "multiplier": data.get("multiplier"), "awards": [self.award_name(a) for a in data.get("awards", [])],
                "awardXp": data.get("award_xp", 0), "total": data.get("total", {}).get("crpt"),
                "kills": data.get("round", {}).get("klls", 0), "deaths": data.get("round", {}).get("dths", 0),
            })
        return {
            "pid": pid, "name": soldier["name"], "created": soldier["created"], "lastLogin": soldier["last_login"],
            "account": {"id": account["id"], "name": account["name"], "created": account["created"],
                        "lastIp": account["last_ip"],
                        "soldiers": [s["name"] for s in self.db.soldiers(account["id"])]},
            "rank": rank, "rankName": self.rank_name(rank), "xp": stats.get("crpt", 0),
            "nextXp": progression.RANK_POINTS[rank + 1] if rank < progression.MAX_NORMAL_RANK else None,
            "credits": {"earned": earned, "spent": spent, "free": max(0, earned - spent)},
            "unlocks": {f"{k}{t}": lvl for (k, t), lvl in levels.items()},
            "awards": [{"id": a, "name": self.award_name(a), "kind": self.award_kind(a), **v}
                       for a, v in sorted(awards.items(), key=lambda kv: self._award_sort(kv[0]))],
            "ban": None if ban is None else {"text": describe_ban(ban), "until": ban["until"], "reason": ban["reason"],
                                             "by": ban["by"], "ip": ban["ip"]},
            "stats": stats,
            "history": history,
        }

    # --- изменения ------------------------------------------------------------

    def act(self, pid: int, action: str, data: dict) -> str:
        soldier = self.db.soldier(pid)
        if soldier is None or soldier["disabled"]:
            raise LookupError("нет такого солдата")
        name, account_id = soldier["name"], soldier["account_id"]
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            raise ValueError(f"неизвестное действие {action}")
        message = handler(pid, account_id, data)
        log.info("админка: %s — %s", name, message)
        return message

    def _set_xp(self, pid, xp):
        xp = int(xp)
        if not 0 <= xp <= 10_000_000:
            raise ValueError("опыт должен быть от 0 до 10 000 000")
        rank = progression.rank_for_points(xp)
        self.db.set_stats(pid, {"crpt": xp, "rnk": rank})
        return f"опыт {xp}, звание {rank} ({self.rank_name(rank)})"

    def _do_set_xp(self, pid, account_id, data):
        return self._set_xp(pid, data.get("xp"))

    def _do_set_rank(self, pid, account_id, data):
        rank = int(data.get("rank"))
        if not 0 <= rank <= progression.MAX_NORMAL_RANK:
            raise ValueError(f"звание от 0 до {progression.MAX_NORMAL_RANK}")
        return self._set_xp(pid, progression.RANK_POINTS[rank])

    def _do_set_unlock(self, pid, account_id, data):
        kit, tree, level = int(data["kit"]), int(data["tree"]), int(data["level"])
        size = progression.TREES.get((kit, tree))
        if size is None or not 0 <= level <= size:
            raise ValueError("нет такой ветки или уровня")
        if level == 0:
            self.db._all("DELETE FROM unlocks WHERE pid = ? AND kit = ? AND tree = ?", (pid, kit, tree))
        else:
            self.db.set_unlock(pid, kit, tree, level)
        return f"ветка {KITS[kit]} {tree}: уровень {level}"

    def _do_unlocks_reset(self, pid, account_id, data):
        self.db._all("DELETE FROM unlocks WHERE pid = ?", (pid,))
        return "анлоки сброшены (очки вернулись)"

    def _do_unlocks_all(self, pid, account_id, data):
        for (kit, tree), level in progression.all_unlocks(self.cfg).items():
            self.db.set_unlock(pid, kit, tree, level)
        return "открыты все анлоки"

    def _do_award_add(self, pid, account_id, data):
        award = str(data.get("award", ""))
        if award not in self.award_ids:
            raise ValueError("нет такой награды")
        if self.award_kind(award) in ("badge", "ribbon") and award in self.db.awards(pid):
            raise ValueError("эта награда выдаётся один раз и уже есть")
        self.db.add_award(pid, award, int(time.time()))
        return f"выдана награда {self.award_name(award)}"

    def _do_award_remove(self, pid, account_id, data):
        award = str(data.get("award", ""))
        if not self.db.remove_award(pid, award):
            raise ValueError("такой награды у игрока нет")
        return f"снята награда {self.award_name(award)}"

    def _do_set_stats(self, pid, account_id, data):
        values = {}
        for key, value in (data.get("values") or {}).items():
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", str(key)):
                raise ValueError(f"странный ключ статистики {key!r}")
            values[key] = float(value) if "." in str(value) else int(value)
        if not values:
            raise ValueError("нечего сохранять")
        if "crpt" in values and "rnk" not in values:
            values["rnk"] = progression.rank_for_points(values["crpt"])
        self.db.set_stats(pid, values)
        return "статистика: " + ", ".join(f"{k}={v}" for k, v in values.items())

    def _do_rename(self, pid, account_id, data):
        new = str(data.get("name", "")).strip()
        if not valid_name(new):
            raise ValueError(f"имя: {NAME_RULE}")
        self.db.rename_soldier(pid, new)
        return f"переименован в {new}"

    def _do_ban(self, pid, account_id, data):
        minutes = data.get("minutes")
        minutes = None if minutes in (None, "", 0, "0") else int(minutes)
        account = self.db.account(account_id)
        ip = account["last_ip"] if data.get("ip") else ""
        self.db.add_ban(account_id, minutes, str(data.get("reason", ""))[:200], "админка", ip)
        return f"бан аккаунта {account['name']}: {describe_ban(self.db.active_ban(account_id))}"

    def _do_unban(self, pid, account_id, data):
        return f"разбан: снято банов {self.db.lift_bans(account_id)}"

    def _do_password(self, pid, account_id, data):
        password = str(data.get("password", ""))
        if not PASSWORD_RE.fullmatch(password):
            raise ValueError("пароль: 4–16 латинских букв и цифр")
        with self.db.transaction():
            self.db._conn.execute("UPDATE accounts SET password_hash = ?, login_token = NULL WHERE id = ?",
                                  (hash_password(password), account_id))
        return "пароль аккаунта изменён"

    def _do_delete_soldier(self, pid, account_id, data):
        soldier = self.db.soldier(pid)
        if data.get("confirm") != soldier["name"]:
            raise ValueError("для удаления впиши имя солдата")
        self.db.disable_soldier(account_id, soldier["name"])
        return "солдат удалён (имя освободилось)"

    def bans(self):
        return [{"id": b["id"], "accountId": b["account_id"], "account": b["account"], "text": describe_ban(b),
                 "created": b["created"],
                 "soldiers": [s["name"] for s in self.db.soldiers(b["account_id"])] if b["account_id"] else []}
                for b in self.db.active_bans()]

    def unban_account(self, account_id: int):
        lifted = self.db.lift_bans(account_id)
        log.info("админка: разбан аккаунта #%d (снято %d)", account_id, lifted)
        return f"снято банов: {lifted}"

    # --- игровой сервер: состояние, настройки, ротация, команды -------------------

    def server(self):
        sc = self.ctx.server
        cfg = sc.load()
        status = sc.current_status()
        if status:
            for p in status["players"]:
                soldier = self.db.soldier(p["pid"]) if p["pid"] > 2000 else None
                p["rankName"] = self.rank_name(int(self.db.stats(p["pid"]).get("rnk", 0))) if soldier else ""
        return {
            "status": status,
            "config": cfg,
            "fields": [{"key": k, "type": t, "label": label, "min": lo, "max": hi}
                       for k, t, label, lo, hi in server_config.FIELDS],
            "modes": server_config.MODES,
            "levels": server_config.LEVELS,
        }

    def server_action(self, data: dict) -> str:
        sc, action = self.ctx.server, data.get("action")
        if action == "settings":
            version = sc.save(settings=data.get("values") or {})
            message = f"настройки сохранены (версия {version}), сервер применит их в течение 30 секунд"
        elif action == "maplist":
            version = sc.save(maplist=data.get("maplist") or [])
            message = f"ротация сохранена (версия {version}), действует со следующей карты"
        elif action == "command":
            sc.queue(str(data.get("command", "")), str(data.get("arg", "")))
            message = f"команда «{data.get('command')}» отправлена, сервер выполнит её в течение 30 секунд"
        else:
            raise ValueError("неизвестное действие")
        log.info("админка: сервер — %s", message)
        return message


def serve(ctx: Context):
    port = ctx.cfg.admin_web_port
    if not port:
        log.info("админка выключена ([admin] web_port = 0)")
        return
    api = AdminAPI(ctx)

    class Handler(BaseHTTPRequestHandler):
        server_version = "BF2142Admin/1.0"

        def log_message(self, fmt, *args):  # обычный журнал HTTP не нужен
            pass

        def _send(self, status, body: bytes, ctype="application/json; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, obj):
            self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def _guard(self, write: bool) -> bool:
            # Только 127.0.0.1/localhost (порт любой — в Docker его могут пробросить на другой):
            # защита от подмены DNS чужим сайтом.
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in ("127.0.0.1", "localhost"):
                self._json(403, {"error": "открой админку по адресу http://127.0.0.1:%d/" % port})
                return False
            if write and self.headers.get("X-Admin") != "1":
                self._json(403, {"error": "нет заголовка X-Admin"})
                return False
            return True

        def do_GET(self):
            if not self._guard(False):
                return
            url = urlsplit(self.path)
            params = dict(parse_qsl(url.query))
            try:
                if url.path in ("/", "/index.html"):
                    return self._send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")
                if url.path == "/api/meta":
                    return self._json(200, api.meta())
                if url.path == "/api/players":
                    return self._json(200, api.players(params.get("q", "").strip()))
                m = re.fullmatch(r"/api/player/(\d+)", url.path)
                if m:
                    return self._json(200, api.player(int(m.group(1))))
                if url.path == "/api/bans":
                    return self._json(200, api.bans())
                if url.path == "/api/server":
                    return self._json(200, api.server())
                self._json(404, {"error": "не найдено"})
            except LookupError as e:
                self._json(404, {"error": str(e)})
            except Exception as e:
                log.exception("админка: ошибка GET %s", self.path)
                self._json(500, {"error": f"ошибка сервера: {e}"})

        def do_POST(self):
            if not self._guard(True):
                return
            url = urlsplit(self.path)
            try:
                length = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(length) or b"{}") if length else {}
                m = re.fullmatch(r"/api/player/(\d+)", url.path)
                if m:
                    return self._json(200, {"ok": api.act(int(m.group(1)), str(data.get("action", "")), data)})
                m = re.fullmatch(r"/api/account/(\d+)/unban", url.path)
                if m:
                    return self._json(200, {"ok": api.unban_account(int(m.group(1)))})
                if url.path == "/api/server":
                    return self._json(200, {"ok": api.server_action(data)})
                self._json(404, {"error": "не найдено"})
            except (ValueError, KeyError, TypeError, AlreadyExists) as e:
                self._json(400, {"error": str(e) if not isinstance(e, AlreadyExists) else "такое имя уже занято"})
            except LookupError as e:
                self._json(404, {"error": str(e)})
            except Exception as e:
                log.exception("админка: ошибка POST %s", self.path)
                self._json(500, {"error": f"ошибка сервера: {e}"})

    server = ThreadingHTTPServer((ctx.cfg.admin_web_bind, port), Handler)
    server.daemon_threads = True
    log.info("админка: http://127.0.0.1:%d/ (слушает %s)", port, ctx.cfg.admin_web_bind)
    server.serve_forever()
