r"""GPCM — сервер профилей GameSpy. TCP 29900, текстовый протокол \ключ\значение\...\final\.

Клиент входит по authtoken — тикету, выданному FESL в GameSpyPreAuth.
ID профиля отсюда игра потом показывает игровому серверу как getProfileId().
"""

import hashlib
import logging
import secrets
import socketserver
import string

from .context import Context
from .netutil import TCPServer

log = logging.getLogger("gpcm")


def encode(pairs) -> bytes:
    return ("\\" + "\\".join(f"{k}\\{v}" for k, v in pairs) + "\\final\\").encode("latin-1", "replace")


def decode(message: str) -> list[tuple[str, str]]:
    parts = message.strip("\\").split("\\")
    return [(parts[i], parts[i + 1] if i + 1 < len(parts) else "") for i in range(0, len(parts), 2)]


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("latin-1")).hexdigest()


def login_hash(password: str, user: str, first: str, second: str) -> str:
    pw = _md5(password)
    return _md5(pw + " " * 48 + user + first + second + pw)


class GpcmSession:
    def __init__(self, ctx: Context, sock, addr):
        self.ctx = ctx
        self.sock = sock
        self.addr = addr
        self.server_challenge = "".join(secrets.choice(string.ascii_uppercase) for _ in range(10))
        self.ticket = None
        self.sesskey = secrets.randbelow(2**31 - 1) + 1

    def send(self, pairs):
        data = encode(pairs)
        log.debug("%s <- %s", self.addr[0], data.decode("latin-1"))
        self.sock.sendall(data)

    def run(self):
        self.send([("lc", "1"), ("challenge", self.server_challenge), ("id", "1")])
        buf = b""
        try:
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\\final\\" in buf:
                    raw, buf = buf.split(b"\\final\\", 1)
                    if not self.handle(decode(raw.decode("latin-1"))):
                        return
        except OSError as e:
            log.debug("%s: соединение закрыто: %r", self.addr[0], e)
        finally:
            name = self.ticket.name if self.ticket else "?"
            log.info("%s: GPCM отключение (%s)", self.addr[0], name)

    def handle(self, pairs) -> bool:
        if not pairs:
            return True
        cmd = pairs[0][0]
        args = dict(pairs)
        log.debug("%s -> %s", self.addr[0], pairs)
        if cmd == "login":
            return self.login(args)
        if cmd == "getprofile":
            self.getprofile(args)
        elif cmd == "ka":
            self.send([("ka", "")])
        elif cmd == "logout":
            return False
        # status, updatepro, addbuddy и прочее — без ответа.
        return True

    def login(self, args) -> bool:
        token = args.get("authtoken", "")
        ticket = self.ctx.tickets.get(token)
        if ticket is None:
            log.info("%s: GPCM вход с неизвестным тикетом", self.addr[0])
            self.send([("error", ""), ("err", "266"), ("fatal", ""), ("errmsg", "Invalid authtoken"), ("id", "1")])
            return False
        self.ticket = ticket
        client_challenge = args.get("challenge", "")
        # Пароль при входе по тикету — challenge из GameSpyPreAuth.
        expected = login_hash(ticket.challenge, token, client_challenge, self.server_challenge)
        if args.get("response") and args["response"] != expected:
            log.debug("%s: response клиента не совпал (не критично)", self.addr[0])
        proof = login_hash(ticket.challenge, token, self.server_challenge, client_challenge)
        lt = secrets.token_urlsafe(16)[:22] + "__"
        self.send([
            ("lc", "2"), ("sesskey", self.sesskey), ("proof", proof), ("userid", ticket.account_id),
            ("profileid", ticket.pid), ("uniquenick", ticket.name), ("lt", lt), ("id", args.get("id", "1")),
        ])
        log.info("%s: GPCM вход солдата %s (pid %d)", self.addr[0], ticket.name, ticket.pid)
        return True

    def getprofile(self, args):
        if self.ticket is None:
            return
        pid = int(args.get("profileid") or self.ticket.pid)
        soldier = self.ctx.db.soldier(pid)
        name = soldier["name"] if soldier else ""
        user = soldier["account_id"] if soldier else 0
        self.send([
            ("pi", ""), ("profileid", pid), ("nick", name), ("userid", user), ("email", f"{name}@localhost"),
            ("sig", secrets.token_hex(16)), ("uniquenick", name), ("pid", 0), ("lon", "0.000000"),
            ("lat", "0.000000"), ("loc", ""), ("id", args.get("id", "2")),
        ])


def serve(ctx: Context):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            log.debug("%s: GPCM подключение", self.client_address[0])
            GpcmSession(ctx, self.request, self.client_address).run()

    with TCPServer((ctx.cfg.bind, ctx.cfg.gpcm_port), Handler) as server:
        log.info("GPCM слушает %s:%d", ctx.cfg.bind, ctx.cfg.gpcm_port)
        server.serve_forever()
