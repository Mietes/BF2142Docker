"""Запросы игровых серверов к бэкенду (/selfhost/...): итоги раунда, админы и баны, бан из игры.

Каждый запрос подписан общим секретом (cfg.server_secret; install_server.py кладёт его в
selfhost_config.py игрового сервера): ?ts=<unix-время>&sig=<HMAC-MD5 от "ts\\nпуть\\nтело">.
MD5 — потому что во встроенном Python 2.3 сервера другого хеша нет; для подписи этого хватает.
Без подписи любой игрок мог бы прислать выдуманный раунд и получить звания и награды.
"""

import hmac
import logging
import time
from urllib.parse import parse_qsl

from . import rounds
from .admin import describe_ban
from .context import Context

log = logging.getLogger("servers")

MAX_CLOCK_SKEW = 600  # секунд: старее — повтор чужого запроса или сбитые часы


def signature(secret: str, ts: str, path: str, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{ts}\n{path}\n".encode() + body, "md5").hexdigest()


class ServerAPI:
    def __init__(self, ctx: Context):
        self.ctx, self.cfg, self.db = ctx, ctx.cfg, ctx.db

    def handle(self, method, path, params, body, client_ip) -> tuple[int, bytes]:
        problem = self._check(path, params, body, client_ip)
        if problem:
            log.warning("%s: запрос %s отклонён: %s", client_ip, path, problem)
            return 403, b"DENIED " + problem.encode()
        action = path.rsplit("/", 1)[-1]
        handler = getattr(self, f"{method.lower()}_{action}", None)
        if handler is None:
            return 404, b"Not found"
        return 200, handler(body, client_ip).encode()

    def _check(self, path, params, body, client_ip) -> str:
        if self.cfg.server_ips and client_ip not in self.cfg.server_ips:
            return "адреса нет в servers.allowed_ips"
        ts, sig = params.get("ts", ""), params.get("sig", "")
        if not ts.isdigit() or not sig:
            return "нет подписи (модуль сервера старый — перезапусти install_server.py)"
        if abs(time.time() - int(ts)) > MAX_CLOCK_SKEW:
            return f"время запроса расходится с бэкендом на {int(time.time()) - int(ts)} с"
        if not self.cfg.server_secret or not hmac.compare_digest(
                signature(self.cfg.server_secret, ts, path, body), sig.lower()):
            return "неверная подпись (секрет сервера не совпадает с бэкендом)"
        return ""

    # --- запросы ------------------------------------------------------------

    def post_snapshot(self, body, client_ip) -> str:
        return rounds.apply_round(self.ctx, body, client_ip)

    def get_serverinfo(self, body, client_ip) -> str:
        """Админы и забаненные (pid через пробел) и кик за бездействие (секунды)."""
        admins = []
        for name in self.cfg.admins:
            soldier = self.db.soldier_by_name(name)
            if soldier is None:
                log.warning("админ %s из настроек: такого солдата нет", name)
            else:
                admins.append(soldier["id"])
        return (f"admins={' '.join(map(str, admins))}\n"
                f"banned={' '.join(map(str, self.db.banned_pids()))}\n"
                f"idle_kick={max(0, self.cfg.idle_kick_minutes) * 60}\n")

    def post_ban(self, body, client_ip) -> str:
        """Бан из игры: pid, minutes (пусто — навсегда), reason, by."""
        f = dict(parse_qsl(body.decode("utf-8", "replace")))
        soldier = self.db.soldier(int(f["pid"])) if f.get("pid", "").isdigit() else None
        if soldier is None:
            return "NOTFOUND"
        minutes = int(f["minutes"]) if f.get("minutes", "").isdigit() else None
        self.db.add_ban(soldier["account_id"], minutes, f.get("reason", ""), f.get("by", ""))
        ban = self.db.active_ban(soldier["account_id"])
        log.info("%s: %s забанил %s: %s", client_ip, f.get("by", "?"), soldier["name"], describe_ban(ban))
        return "OK"

    def post_unban(self, body, client_ip) -> str:
        """Разбан из игры по имени солдата: nick, by."""
        f = dict(parse_qsl(body.decode("utf-8", "replace")))
        soldier = self.db.soldier_by_name(f.get("nick", ""))
        if soldier is None:
            return "NOTFOUND"
        lifted = self.db.lift_bans(soldier["account_id"])
        log.info("%s: %s разбанил %s (снято банов: %d)", client_ip, f.get("by", "?"), soldier["name"], lifted)
        return "OK" if lifted else "NOTBANNED"
