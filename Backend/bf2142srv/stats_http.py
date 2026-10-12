"""HTTP-сервис статистики (адрес stella.prod в оригинале).

Запросы *.aspx приходят и от клиента игры (BFHQ, меню анлоков), и от игрового
сервера (ранг и анлоки подключившегося игрока).
"""

import json
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

from . import aspx, eacrypt, progression, rounds
from .config import RES_DIR
from .context import Context
from .servers import ServerAPI

log = logging.getLogger("stats")

COLUMNS: dict[str, list[str]] = json.loads((RES_DIR / "playerinfo_columns.json").read_text())
AWARD_DEFS = (RES_DIR / "awards_backend.con").read_text(encoding="utf-8").strip().splitlines()
LATEST_VERSION = "1.7.94.0"
BASE_EXTRA = ["nick", "rnkcg", "unavl", "pdt", "pdtc", "kdr", "acdt", "lgdt"]
# Графики прогресса BFHQ: колонка -> функция от итоговых значений после раунда.
PROGRESS_COLUMNS = {
    "point": {"points": lambda t: t["gsco"] + t["crpt"], "globalscore": "gsco",
              "experiencepoints": "crpt", "awaybonus": "awaybonus"},
    "score": {"score": "gsco"},
    "ttp": {"ttp": "tt"},
    "kills": {"kpm": "kpm", "dpm": "dpm"},
    "spm": {"spm": "spm"},
    "role": {"cotime": "tac", "sltime": "tasl", "smtime": "tasm", "lwtime": "talw", "ttp": "tt"},
    "flag": {"captures": "cpt", "assist": "capa", "defend": "dcpt"},
    "waccu": {"waccu": "ovaccu"},
    "wl": {"wins": "win", "losses": "los"},
    "twsc": {"twsc": "twsc"},
    "sup": {"hls": "hls", "rps": "rps", "rvs": "rvs", "resp": "resp"},
}
NEWS_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<news>\n'
    '\t<newsitem header="Battlefield 2142"><p>{text}</p></newsitem>\n</news>\n'
)


def _dedupe(items):
    seen = set()
    return [x for x in items if not (x in seen or seen.add(x))]


@dataclass
class Player:
    pid: int
    name: str
    values: dict
    levels: dict
    available: int


class StatsService:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.cfg = ctx.cfg
        self.db = ctx.db
        self._top: dict[int, int] = {}
        self._top_at = 0.0
        self.servers = ServerAPI(ctx)

    def weekly_top(self) -> dict[int, int]:
        """pid -> спецзвание (41–43) по опыту за прошлую календарную неделю. Кэш на 10 минут."""
        if not self.cfg.weekly_top:
            return {}
        if time.time() - self._top_at < 600:
            return self._top
        now = datetime.now()
        monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        start, end = int((monday - timedelta(days=7)).timestamp()), int(monday.timestamp())
        eligible = [pid for pid, xp in self.db.xp_between(start, end)
                    if xp > 0 and int(self.db.stats(pid).get("rnk", 0)) >= self.cfg.weekly_top_min_rank]
        top = {}
        for place, pid in enumerate(eligible, 1):
            rank = progression.special_rank(place)
            if rank is None:
                break
            top[pid] = rank
        self._top, self._top_at = top, time.time()
        return top

    # --- общие вспомогательные ---------------------------------------------

    @staticmethod
    def _identify(params) -> tuple[int | None, bool]:
        token = eacrypt.decode(params["auth"]) if params.get("auth") else None
        if params.get("pid", "").isdigit():
            pid = int(params["pid"])
        else:
            pid = token.pid if token else None
        return pid, bool(token and token.is_server)

    def player(self, pid) -> Player | None:
        soldier = self.db.soldier(pid) if pid else None
        if soldier is None:
            return None
        values = self.db.stats(pid)
        rank = int(values.get("rnk", 0))  # настоящее звание: от него считаются очки анлоков
        shown_rank = self.weekly_top().get(pid, rank)  # спецзвание 41–43, если в недельном топе
        if self.cfg.unlock_mode == "all":
            levels = progression.all_unlocks(self.cfg)
            available = 0
        else:
            levels = self.db.unlocks(pid)
            available = max(0, progression.earned_credits(self.cfg, rank) - progression.spent_credits(levels))
        values.update(
            pid=pid, nick=soldier["name"], subaccount=soldier["name"], tid=0, rnk=shown_rank,
            unavl=available, unlc=progression.spent_credits(levels),
            acdt=soldier["created"], lgdt=soldier["last_login"],
        )
        if self.cfg.northern_strike:  # дополнение Northern Strike (booster pack 1) есть у всех
            values["bp-1"] = 1
        return Player(pid, soldier["name"], values, levels, available)

    # --- маршрутизация ------------------------------------------------------

    def handle(self, method, path, params, body, client_ip) -> tuple[int, str, bytes]:
        name = path.lstrip("/").lower()
        text = "text/plain"
        if name.startswith(("bf2142ticker/", "bf2142eanews/", "bf2142demoticker/")):
            return 200, "text/xml", NEWS_XML.format(text="Добро пожаловать на сервер!").encode()
        if name == "motd.asp":
            return 200, text, b"Welcome!"
        if name.startswith("selfhost/"):  # запросы игровых серверов, подписанные секретом
            status, data = self.servers.handle(method, path, params, body, client_ip)
            return status, text, data
        handler = getattr(self, "page_" + name.removesuffix(".aspx").replace("-", "_"), None)
        if not name.endswith(".aspx") or handler is None:
            log.warning("неизвестный запрос %s %s", method, path)
            return 404, text, b"Not found"
        return 200, text, handler(params, client_ip)

    # --- страницы -----------------------------------------------------------

    def page_getbackendinfo(self, params, client_ip):
        _, is_server = self._identify(params)
        config = []
        if not is_server:
            config.append(f"swiffHost.setLatestGameVersion {LATEST_VERSION}")
        config += [f"rankSettings.setRank {r} {p}" for r, p in enumerate(progression.RANK_POINTS)]
        config += [f"rankSettings.setRank {r} 0" for r in (41, 42, 43)]
        config.append("rankSettings.save")
        if not is_server:
            config += AWARD_DEFS
        cb = "server" if is_server else "client"
        return aspx.build_raw(
            f"O\nH\tasof\ttid\tserverip\tcb\nD\t{int(time.time())}\t0\t{client_ip}\t{cb}\n"
            "H\tconfig\nD\t" + "\n".join(config)
        )

    def page_getplayerinfo(self, params, client_ip):
        pid, is_server = self._identify(params)
        p = self.player(pid)
        if p is None:
            return aspx.error(104)
        now = int(time.time())
        mode = params.get("mode", "base")
        if mode == "base":
            cols = _dedupe(COLUMNS["base"] + BASE_EXTRA)
            return aspx.build(
                (["asof", "cb"], [[now, "server" if is_server else "client"]]),
                (cols, [[p.values.get(c, 0) for c in cols]]),
                (["UnlockID"], [[u] for u in progression.unlock_ids(p.levels)]),
            )
        cols = COLUMNS.get(mode) or sorted(p.values)
        if mode == "award":  # полосы прогресса наград: все ключи из условий, даже нулевые
            needed = {k for crits in rounds.criteria().values() for c in crits for k in c.keys
                      if not k[0].isdigit()}
            cols = sorted(set(cols) | needed)
        return aspx.build(
            (["pid", "nick", "tid", "asof"], [[p.pid, p.name, 0, now]]),
            (cols, [[p.values.get(c, 0) for c in cols]]),
        )

    def page_getunlocksinfo(self, params, client_ip):
        pid, _ = self._identify(params)
        p = self.player(pid)
        if p is None:
            return aspx.error(104)
        return aspx.build(
            (["pid", "nick", "asof"], [[p.pid, p.name, int(time.time())]]),
            (["Avcred"], [[p.available]]),
            (["UnlockID"], [[u] for u in progression.unlock_ids(p.levels)]),
        )

    def page_selectunlock(self, params, client_ip):
        pid, _ = self._identify(params)
        p = self.player(pid)
        parsed = progression.parse_unlock_id(params.get("uid", ""))
        if p is None or parsed is None or self.cfg.unlock_mode != "progression":
            return aspx.error(104)
        kit, tree, level = parsed
        if level != p.levels.get((kit, tree), 0) + 1 or p.available < 1:
            log.info("%s: отказ в анлоке %s (очков %d)", p.name, params.get("uid"), p.available)
            return aspx.error(104)
        self.db.set_unlock(pid, kit, tree, level)
        log.info("%s открыл анлок %d%d%d", p.name, kit, tree, level)
        return aspx.build(
            (["pid", "nick", "asof"], [[p.pid, p.name, int(time.time())]]),
            (["result"], [["OK"]]),
        )

    def page_getawardsinfo(self, params, client_ip):
        pid, _ = self._identify(params)
        p = self.player(pid)
        if p is None:
            return aspx.error(104)
        # Значки (1xx_N) и ленты (3xx) — level 0, first 0; медали (2xx) и значки отличия (4xx) —
        # level = сколько раз получены, when — последний раз, first — первый.
        rows = []
        for award, a in self.db.awards(p.pid).items():
            repeatable = award[0] in "24"
            rows.append([award, a["count"] if repeatable else 0, a["last"], a["first"] if repeatable else 0])
        return aspx.build(
            (["pid", "nick", "asof"], [[p.pid, p.name, int(time.time())]]),
            (["award", "level", "when", "first"], rows),
        )

    def page_getrankinfo(self, params, client_ip):
        pid, _ = self._identify(params)
        p = self.player(pid)
        if p is None:
            return aspx.error(104)
        return aspx.build(
            (["pid", "nick", "asof"], [[p.pid, p.name, int(time.time())]]),
            (["rnk", "rnkcg"], [[p.values["rnk"], p.values.get("rnkcg", 0)]]),
        )

    def page_getplayerprogress(self, params, client_ip):
        pid, _ = self._identify(params)
        p = self.player(pid)
        cols = PROGRESS_COLUMNS.get(params.get("mode", "point"))
        if p is None or cols is None:
            return aspx.error(104)
        history = [(ended, data["total"]) for ended, data in self.db.round_history(pid)]
        if not history:
            # Без единой строки данных клиент падает при открытии штаба — отдаём текущую точку.
            history = [(int(time.time()), p.values)]
        rows = []
        for ended, totals in history:
            total = defaultdict(int, totals)
            rows.append([ended] + [f(total) if callable(f) else total[f] for f in cols.values()])
        return aspx.build((["pid", "asof"], [[p.pid, int(time.time())]]), (["date", *cols], rows))

    def page_getleaderboard(self, params, client_ip):
        pos = max(1, int(params.get("pos", "1") or 1))
        after = min(50, max(1, int(params.get("after", "17") or 17)))
        rows = self.db.leaderboard("gsco", pos - 1, after)
        return aspx.build(
            (["size", "asof"], [[self.db.soldier_count(), int(time.time())]]),
            (["pos", "pid", "nick", "globalscore", "playerrank", "countrycode", "Vet"],
             [[pos + i, r["id"], r["name"], r["score"], r["rank"], "", 0] for i, r in enumerate(rows)]),
        )

    def page_playersearch(self, params, client_ip):
        pid, _ = self._identify(params)
        nick = params.get("nick", "")
        rows = self.db.search_soldiers(nick.strip("*"))
        return aspx.build(
            (["pid", "asof"], [[pid or 0, int(time.time())]]),
            (["searchpattern"], [[nick]]),
            (["pid", "nick"], [[r["id"], r["name"]] for r in rows]),
        )

    def page_clearranknotification(self, params, client_ip):
        pid, _ = self._identify(params)
        if self.player(pid) is None:
            return aspx.error(104)
        self.db.set_stats(pid, {"rnkcg": 0})
        return aspx.build((["result", "asof"], [[0, int(time.time())]]))

    def page_validateplayer(self, params, client_ip):
        pid, _ = self._identify(params)
        p = self.player(pid)
        nick = params.get("SoldierNick") or (p.name if p else "")
        result = "Ok" if p is not None and p.name.lower() == nick.lower() else "InvalidUser"
        return aspx.build(
            (["pid", "nick", "spid", "asof"], [[pid or 0, nick, pid or 0, int(time.time())]]),
            (["result"], [[result]]),
        )

    def _ok(self, params, client_ip):
        return aspx.build((["result"], [["Ok"]]))

    page_playerdisconnect = _ok
    page_rankchange = _ok
    page_grantaward = _ok


def serve(ctx: Context):
    service = StatsService(ctx)

    class Handler(BaseHTTPRequestHandler):
        server_version = "BF2142Stats/1.0"

        def _dispatch(self, method):
            url = urlsplit(self.path)
            params = dict(parse_qsl(url.query, keep_blank_values=True))
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            ip = self.client_address[0]
            try:
                status, ctype, data = service.handle(method, url.path, params, body, ip)
            except Exception:
                log.exception("ошибка обработки %s", self.path)
                status, ctype, data = 500, "text/plain", aspx.error(999)
            log.debug("%s %s -> %d\n%s", method, self.path, status, data.decode("utf-8", "replace"))
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def log_message(self, fmt, *args):
            # Ленту новостей клиент запрашивает каждые несколько секунд — не засоряем журнал.
            quiet = "ticker" in self.path.lower() or "news" in self.path.lower()
            (log.debug if quiet else log.info)("%s %s", self.client_address[0], fmt % args)

    class Server(ThreadingHTTPServer):
        allow_reuse_address = sys.platform != "win32"
        daemon_threads = True

    httpd = Server((ctx.cfg.bind, ctx.cfg.http_port), Handler)
    log.info("статистика (HTTP) слушает %s:%d", ctx.cfg.bind, ctx.cfg.http_port)
    httpd.serve_forever()
