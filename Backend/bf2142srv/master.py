"""Мастер-сервер GameSpy для вкладки «Интернет».

UDP 27900 — QR2: игровые серверы шлют heartbeat со своими параметрами;
              тут же отвечаем клиентам на проверку доступности GameSpy.
TCP 28910 — Server Browser: клиент запрашивает список, ответ шифруется enctypeX.
"""

import ipaddress
import logging
import secrets
import socket
import socketserver
import string
import struct
import threading
import time
from dataclasses import dataclass, field

from . import enctypex
from .context import Context
from .netutil import TCPServer, UDPServer

log = logging.getLogger("master")

AVAILABLE_REPLY = b"\xfe\xfd\x09\x00\x00\x00\x00"
GAMEKEYS = {"stella": b"M8o1Qw"}  # секретный ключ BF2142 для enctypeX
SERVER_TTL = 180  # сервер пропадает из списка, если молчит дольше (сек)

QR_CHALLENGE, QR_HEARTBEAT, QR_KEEPALIVE, QR_AVAILABLE, QR_REGISTERED = 0x01, 0x03, 0x08, 0x09, 0x0A

FLAG_PRIVATE_IP = 0x02
FLAG_NONSTANDARD_PORT = 0x10
FLAG_NONSTANDARD_PRIVATE_PORT = 0x20
FLAG_HAS_KEYS = 0x40


@dataclass
class GameServer:
    ip: str               # адрес, который отдаём клиентам
    query_port: int       # UDP-порт запросов (откуда пришёл heartbeat)
    instance_key: bytes
    local_ip: str = ""    # откуда на самом деле пришёл heartbeat
    info: dict = field(default_factory=dict)
    last_seen: float = 0.0
    registered: bool = False


class Registry:
    def __init__(self):
        self.lock = threading.Lock()
        self.servers: dict[tuple[str, int], GameServer] = {}

    def alive(self, gamename: str) -> list[GameServer]:
        now = time.time()
        with self.lock:
            for key in [k for k, s in self.servers.items() if now - s.last_seen > SERVER_TTL]:
                log.info("сервер %s:%d пропал из списка (нет heartbeat)", *key)
                del self.servers[key]
            return [s for s in self.servers.values() if s.info.get("gamename", gamename) == gamename]


def _advertised_ip(src_ip: str, ctx: Context) -> str:
    """Сервер на той же машине шлёт heartbeat с 127.0.0.1 или из локальной сети —
    игрокам снаружи нужно отдавать публичный адрес."""
    addr = ipaddress.ip_address(src_ip)
    if (addr.is_loopback or addr.is_private) and ctx.cfg.public_host:
        return ctx.cfg.public_host
    return src_ip


def _ip_for(client_ip: str, srv: GameServer, lan: bool = True) -> str:
    """Какой адрес сервера отдать этому игроку. Тому, кто на той же машине или в той же домашней сети,
    что и сервер, — локальный: на собственный внешний IP многие роутеры изнутри не пускают
    (нет NAT loopback), и хозяин не зашёл бы на свой сервер из списка.
    lan=False (Docker): частные адреса там — внутренняя сеть контейнеров, игрокам они недоступны."""
    if not srv.local_ip:
        return srv.ip
    client, local = ipaddress.ip_address(client_ip), ipaddress.ip_address(srv.local_ip)
    if local.is_loopback:  # сервер на машине бэкенда: 127.0.0.1 годится только для неё самой
        return srv.local_ip if client.is_loopback else srv.ip
    if lan and (client == local or (client.is_private and local.is_private)):
        return srv.local_ip
    return srv.ip


def _parse_heartbeat(payload: bytes) -> dict:
    """key\\0value\\0...\\0 — дальше идут игроки и команды, они нам не нужны."""
    info = {}
    parts = payload.split(b"\0")
    i = 0
    while i + 1 < len(parts) and parts[i]:
        info[parts[i].decode("latin-1")] = parts[i + 1].decode("latin-1")
        i += 2
    return info


# --- QR2 (UDP) ---------------------------------------------------------------

def _qr_handler(ctx: Context, registry: Registry):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            data, sock = self.request
            if not data:
                return
            ip, port = self.client_address
            kind = data[0]
            if kind == QR_AVAILABLE:
                sock.sendto(AVAILABLE_REPLY, self.client_address)
                return
            ikey = data[1:5]
            key = (ip, port)
            if kind == QR_HEARTBEAT:
                log.debug("QR heartbeat от %s:%d: %r", ip, port, data[:600])
                info = _parse_heartbeat(data[5:])
                with registry.lock:
                    srv = registry.servers.get(key)
                    if info.get("statechanged") == "2":
                        if srv:
                            log.info("сервер %s:%d (%s) завершает работу", ip, port, srv.info.get("hostname"))
                            del registry.servers[key]
                        return
                    if srv is None or srv.instance_key != ikey:
                        srv = GameServer(_advertised_ip(ip, ctx), port, ikey, local_ip=ip)
                        registry.servers[key] = srv
                        log.info("новый сервер %s:%d «%s» (%s %s, %s/%s)", ip, port, info.get("hostname"),
                                 info.get("mapname"), info.get("gametype"), info.get("numplayers"),
                                 info.get("maxplayers"))
                    srv.info.update(info)
                    srv.last_seen = time.time()
                    need_challenge = not srv.registered
                if need_challenge:
                    # Формат как у GameSpy: 6 случайных букв + "00" + IP и порт сервера в hex.
                    challenge = "".join(secrets.choice(string.ascii_letters) for _ in range(6))
                    challenge += "00" + socket.inet_aton(ip).hex().upper() + f"{port:04X}"
                    sock.sendto(b"\xfe\xfd" + bytes([QR_CHALLENGE]) + ikey + challenge.encode() + b"\0",
                                self.client_address)
            elif kind == QR_CHALLENGE:
                # Ответ сервера на challenge: подпись не проверяем — регистрируем.
                with registry.lock:
                    srv = registry.servers.get(key)
                    if srv:
                        srv.registered = True
                        srv.last_seen = time.time()
                sock.sendto(b"\xfe\xfd" + bytes([QR_REGISTERED]) + ikey, self.client_address)
            elif kind == QR_KEEPALIVE:
                with registry.lock:
                    srv = registry.servers.get(key)
                    if srv:
                        srv.last_seen = time.time()
            else:
                log.debug("QR %s:%d: пакет 0x%02x (%d байт) не обрабатывается", ip, port, kind, len(data))
    return Handler


# --- Server Browser (TCP) ----------------------------------------------------

def _cstr(data: bytes, pos: int) -> tuple[str, int]:
    end = data.index(b"\0", pos)
    return data[pos:end].decode("latin-1"), end + 1


def build_list(client_ip: str, fields: list[str], servers: list[GameServer], lan: bool = True) -> bytes:
    out = bytearray(socket.inet_aton(client_ip))
    out += struct.pack(">H", servers[0].query_port if servers else 29900)
    out.append(len(fields))
    for f in fields:
        out += b"\0" + f.encode("latin-1") + b"\0"  # тип 0 = строка
    out.append(0)  # «популярных» значений нет
    for s in servers:
        ip = socket.inet_aton(_ip_for(client_ip, s, lan))
        port = struct.pack(">H", s.query_port)
        out.append(FLAG_HAS_KEYS | FLAG_NONSTANDARD_PORT | FLAG_PRIVATE_IP | FLAG_NONSTANDARD_PRIVATE_PORT)
        out += ip + port + ip + port
        for f in fields:
            out += b"\xff" + s.info.get(f, "").encode("latin-1", "replace") + b"\0"
    out += b"\0\xff\xff\xff\xff"
    return bytes(out)


def _sb_handler(ctx: Context, registry: Registry):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            sock = self.request
            sock.settimeout(60)
            ip = self.client_address[0]
            buf = b""
            cipher = None
            try:
                while True:
                    while len(buf) < 2 or len(buf) < struct.unpack(">H", buf[:2])[0]:
                        chunk = sock.recv(4096)
                        if not chunk:
                            return
                        buf += chunk
                    size = struct.unpack(">H", buf[:2])[0]
                    packet, buf = buf[:size], buf[size:]
                    if packet[2] != 0x00:
                        log.debug("SB %s: запрос 0x%02x пропущен", ip, packet[2])
                        continue
                    query_game, pos = _cstr(packet, 9)
                    client_game, pos = _cstr(packet, pos)
                    validate = packet[pos:pos + 8]
                    flt, pos = _cstr(packet, pos + 8)
                    keylist, pos = _cstr(packet, pos)
                    fields = [k for k in keylist.split("\\") if k]
                    gamekey = GAMEKEYS.get(client_game)
                    if gamekey is None:
                        log.warning("SB %s: неизвестная игра %r", ip, client_game)
                        return
                    servers = registry.alive(query_game)
                    payload = build_list(ip, fields, servers, ctx.cfg.lan_addresses)
                    header, challenge = enctypex.make_header()
                    cipher = enctypex.EnctypeX(gamekey, validate, challenge)
                    sock.sendall(header + cipher.encrypt(payload))
                    log.info("SB %s: отдан список (%d серверов), фильтр %r", ip, len(servers), flt)
                    log.debug("SB поля: %s", fields)
            except (OSError, ValueError) as e:
                log.debug("SB %s: соединение закрыто: %r", ip, e)
    return Handler


def serve(ctx: Context):
    registry = Registry()

    def run_sb():
        with TCPServer((ctx.cfg.bind, ctx.cfg.sb_port), _sb_handler(ctx, registry)) as srv:
            log.info("список серверов (TCP) слушает %s:%d", ctx.cfg.bind, ctx.cfg.sb_port)
            srv.serve_forever()

    threading.Thread(target=run_sb, name="sb", daemon=True).start()
    with UDPServer((ctx.cfg.bind, ctx.cfg.available_port), _qr_handler(ctx, registry)) as srv:
        log.info("мастер QR2/доступность (UDP) слушает %s:%d", ctx.cfg.bind, ctx.cfg.available_port)
        srv.serve_forever()
