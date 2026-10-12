"""FESL — сервер аккаунтов EA (вход, регистрация, солдаты). TCP 18300, SSLv3.

Пакет: тип (4 символа: fsys/acct/subs/dobj), флаги (1 байт), номер (3 байта),
полная длина (4 байта, big-endian), затем строки "ключ=значение\\n" и байт 0.
"""

import base64
import logging
import secrets
import socketserver
import threading
import time
from urllib.parse import unquote

from tlslite.api import TLSConnection

from . import db as dbmod
from .admin import describe_ban, valid_name
from .config import DATA_DIR
from .context import Context
from .netutil import TCPServer
from .tls import ServerCredentials

log = logging.getLogger("fesl")

FLAG_REPLY = 0x80
FLAG_MULTI = 0xF0
PING_INTERVAL = 30
# Коды ошибок, которые клиент переводит в сообщения (найдены в BF2142.exe):
# 103 -> LOCERROR_accountbanned; 21 + errorContainer с полем Account.ScreenName и fieldError 0
# -> LOCERROR_accountnameinvalid (текст обоих меняет build_hq_patch.py).
ERR_BANNED = 103
ERR_FIELD = 21
NAME_FIELD = "Account.ScreenName"

COUNTRIES = [
    ("RU", "Russia"), ("UA", "Ukraine"), ("BY", "Belarus"), ("KZ", "Kazakhstan"),
    ("US", "United States"), ("GB", "United Kingdom"), ("DE", "Germany"), ("PL", "Poland"),
]
TOS = "Battlefield 2142 community server. Have fun!"


def encode_packet(kind: str, seq: int, fields, flags: int = FLAG_REPLY) -> bytes:
    body = "".join(f"{k}={v}\n" for k, v in fields).encode("utf-8") + b"\0"
    return kind.encode("ascii") + bytes([flags]) + seq.to_bytes(3, "big") + (12 + len(body)).to_bytes(4, "big") + body


def parse_fields(raw: bytes) -> dict[str, str]:
    fields = {}
    for line in raw.rstrip(b"\0").decode("utf-8", "replace").split("\n"):
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value
    return fields


def _lkey() -> str:
    return secrets.token_hex(14)[:27] + "."


class FeslSession:
    def __init__(self, ctx: Context, creds: ServerCredentials, sock, addr):
        self.ctx, self.cfg, self.db = ctx, ctx.cfg, ctx.db
        self.creds = creds
        self.sock = sock
        self.addr = addr
        self.conn: TLSConnection | None = None
        self.write_lock = threading.Lock()
        self.alive = True
        self.account = None
        self.soldier = None
        self.multi: dict[tuple[str, int], bytearray] = {}

    # --- ввод/вывод -----------------------------------------------------------

    def _read(self, n: int) -> bytes | None:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.conn.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return bytes(buf)

    def send(self, kind, seq, fields):
        data = encode_packet(kind, seq, fields)
        log.debug("%s <- %s", self.addr[0], data[12:-1].decode("utf-8", "replace").replace("\n", " | "))
        with self.write_lock:
            self.conn.write(data)

    def error(self, kind, seq, txn, code, message):
        log.info("%s: %s отклонён (%d %s)", self.addr[0], txn, code, message)
        self.send(kind, seq, [
            ("TXN", txn), ("localizedMessage", f'"{message}"'), ("errorContainer.[]", 0), ("errorCode", code),
        ])

    def name_error(self, kind, seq, txn, name):
        """Недопустимое имя аккаунта или солдата: клиент покажет «Недопустимое название…»."""
        log.info("%s: %s отклонён: недопустимое имя %r", self.addr[0], txn, name)
        self.send(kind, seq, [
            ("TXN", txn), ("localizedMessage", '"Invalid name"'), ("errorContainer.[]", 1),
            ("errorContainer.0.fieldName", NAME_FIELD), ("errorContainer.0.fieldError", 0),
            ("errorContainer.0.value", '""'), ("errorCode", ERR_FIELD),
        ])

    def banned(self, kind, seq, txn, account_id) -> bool:
        """Если аккаунт или IP забанены — отказать с «Учетная запись заблокирована»."""
        ban = self.db.active_ban(account_id, self.addr[0])
        if ban is None:
            return False
        log.info("%s: %s отклонён: бан (%s)", self.addr[0], txn, describe_ban(ban))
        self.send(kind, seq, [
            ("TXN", txn), ("localizedMessage", '"The account has been banned"'), ("errorContainer.[]", 0),
            ("errorCode", ERR_BANNED),
        ])
        return True

    def _pinger(self):
        while self.alive:
            time.sleep(PING_INTERVAL)
            if self.alive:
                try:
                    self.send("fsys", 0, [("TXN", "Ping")])
                except Exception:
                    return

    # --- основной цикл ---------------------------------------------------------

    def run(self):
        self.conn = TLSConnection(self.sock)
        try:
            self.conn.handshakeServer(certChain=self.creds.chain, privateKey=self.creds.key, settings=self.creds.settings)
        except Exception as e:
            log.warning("%s: SSL-рукопожатие не удалось: %r", self.addr[0], e)
            return
        log.info("%s: подключение (%s, %s)", self.addr[0],
                 {(3, 0): "SSLv3", (3, 1): "TLS1.0"}.get(self.conn.version, self.conn.version), self.conn.getCipherName())
        threading.Thread(target=self._pinger, daemon=True).start()
        try:
            while self.alive:
                header = self._read(12)
                if header is None:
                    break
                kind = header[:4].decode("ascii", "replace")
                flags = header[4]
                seq = int.from_bytes(header[5:8], "big")
                length = int.from_bytes(header[8:12], "big")
                payload = self._read(length - 12) if length > 12 else b""
                if payload is None:
                    break
                fields = parse_fields(payload)
                if flags == FLAG_MULTI:
                    fields = self._collect_multi(kind, seq, fields)
                    if fields is None:
                        continue
                self.dispatch(kind, seq, fields)
        except Exception as e:
            log.debug("%s: соединение закрыто: %r", self.addr[0], e)
        finally:
            self.alive = False
            try:
                self.conn.close()
            except Exception:
                pass
            log.info("%s: отключение", self.addr[0])

    def _collect_multi(self, kind, seq, fields):
        """Большие запросы клиент шлёт частями: size=<всего>, data=<кусок base64>."""
        buf = self.multi.setdefault((kind, seq), bytearray())
        buf += base64.b64decode(unquote(fields.get("data", "")))
        if len(buf) < int(fields.get("size", "0")):
            return None
        del self.multi[(kind, seq)]
        return parse_fields(bytes(buf))

    def dispatch(self, kind, seq, fields):
        txn = fields.get("TXN", "")
        shown = {k: ("***" if "password" in k.lower() else v) for k, v in fields.items()}
        log.debug("%s -> %s %s", self.addr[0], kind, shown)
        handler = getattr(self, "txn_" + txn, None)
        if handler is None:
            log.warning("%s: неизвестная транзакция %s/%s %s", self.addr[0], kind, txn, shown)
            self.send(kind, seq, [("TXN", txn)])
            return
        handler(kind, seq, fields)

    # --- fsys -------------------------------------------------------------------

    def txn_Hello(self, kind, seq, f):
        cur = time.strftime("%b-%d-%Y %H:%M:%S UTC", time.gmtime()).replace(":", "%3a")
        self.send(kind, seq, [
            ("TXN", "Hello"),
            ("domainPartition.domain", "eagames"),
            ("messengerIp", "0.0.0.0"),
            ("messengerPort", 0),
            ("domainPartition.subDomain", "BF2142"),
            ("activityTimeoutSecs", 0),
            ("curTime", f'"{cur}"'),
            ("theaterIp", ""),
            ("theaterPort", 0),
        ])
        self.send(kind, seq, [("TXN", "MemCheck"), ("memcheck.[]", 0), ("type", 0), ("salt", secrets.randbelow(2**31))])

    def txn_MemCheck(self, kind, seq, f):
        pass

    def txn_Ping(self, kind, seq, f):
        pass

    def txn_Goodbye(self, kind, seq, f):
        self.alive = False

    # --- аккаунт ----------------------------------------------------------------

    def txn_GetCountryList(self, kind, seq, f):
        fields = [("TXN", "GetCountryList")]
        for i, (code, name) in enumerate(COUNTRIES):
            fields += [(f"countryList.{i}.ISOCode", code), (f"countryList.{i}.description", f'"{name}"')]
        fields.append(("countryList.[]", len(COUNTRIES)))
        self.send(kind, seq, fields)

    def txn_GetTos(self, kind, seq, f):
        self.send(kind, seq, [("TXN", "GetTos"), ("tos", f'"{TOS}"')])

    def txn_AddAccount(self, kind, seq, f):
        name, password = f.get("name", ""), f.get("password", "")
        if not valid_name(name):
            return self.name_error(kind, seq, "AddAccount", name)
        if not password:
            return self.error(kind, seq, "AddAccount", 21, "Invalid account name or password")
        if self.banned(kind, seq, "AddAccount", None):
            return
        dob = f"{f.get('DOBYear', '')}-{f.get('DOBMonth', '')}-{f.get('DOBDay', '')}"
        try:
            account_id = self.db.create_account(name, password, f.get("email", ""), f.get("countryCode", ""), dob)
        except dbmod.AlreadyExists:
            return self.error(kind, seq, "AddAccount", 160, "That account name is already taken")
        log.info("%s: создан аккаунт %s (#%d)", self.addr[0], name, account_id)
        self.send(kind, seq, [("TXN", "AddAccount"), ("userId", account_id), ("profileId", account_id)])

    def txn_Login(self, kind, seq, f):
        if f.get("encryptedInfo"):
            account = self.db.account_by_token(f["encryptedInfo"])
            if account is None:
                return self.error(kind, seq, "Login", 101, "The user was not found")
        else:
            name, password = f.get("name", ""), f.get("password", "")
            account = self.db.account_by_name(name)
            if account is None and self.cfg.auto_register and password:
                if not valid_name(name):
                    return self.name_error(kind, seq, "Login", name)
                if self.banned(kind, seq, "Login", None):
                    return
                self.db.create_account(name, password)
                log.info("%s: авторегистрация аккаунта %s", self.addr[0], name)
                account = self.db.account_by_name(name)
            if account is None:
                return self.error(kind, seq, "Login", 101, "The user was not found")
            if not dbmod.verify_password(password, account["password_hash"]):
                return self.error(kind, seq, "Login", 122, "The password is incorrect")
        if self.banned(kind, seq, "Login", account["id"]):
            return
        token = secrets.token_hex(32)
        self.db.set_login_token(account["id"], token, self.addr[0])
        self.account = account
        log.info("%s: вход в аккаунт %s (#%d)", self.addr[0], account["name"], account["id"])
        self.send(kind, seq, [
            ("TXN", "Login"),
            ("profileId", account["id"]),
            ("userId", account["id"]),
            ("displayName", account["name"]),
            ("lkey", _lkey()),
            ("encryptedLoginInfo", token),
            ("entitledGameFeatureWrappers.0.gameFeatureId", 2590),
            ("entitledGameFeatureWrappers.0.status", 0),
            ("entitledGameFeatureWrappers.0.entitlementExpirationDate", ""),
            ("entitledGameFeatureWrappers.0.message", ""),
            ("entitledGameFeatureWrappers.0.entitlementExpirationDays", -1),
        ])

    def _need_account(self, kind, seq, txn) -> bool:
        if self.account is None:
            self.error(kind, seq, txn, 101, "Not logged in")
            return False
        return True

    def txn_GetAccount(self, kind, seq, f):
        if not self._need_account(kind, seq, "GetAccount"):
            return
        a = self.db.account(self.account["id"])
        year, month, day = (a["dob"].split("-") + ["", "", ""])[:3]
        country = a["country"] or "RU"
        self.send(kind, seq, [
            ("TXN", "GetAccount"),
            ("name", a["name"]),
            ("profileId", a["id"]),
            ("userId", a["id"]),
            ("email", a["email"] or f"{a['name']}@localhost"),
            ("countryCode", country),
            ("countryDesc", f'"{dict(COUNTRIES).get(country, country)}"'),
            ("dobDay", day or 1), ("dobMonth", month or 1), ("dobYear", year or 1990),
            ("zipCode", 0),
            ("gender", "U"),
            ("eaMailFlag", 0),
            ("thirdPartyMailFlag", 0),
        ])

    def txn_UpdateAccount(self, kind, seq, f):
        if self._need_account(kind, seq, "UpdateAccount"):
            self.db.update_account(self.account["id"], f.get("email", ""), f.get("countryCode", ""))
            self.send(kind, seq, [("TXN", "UpdateAccount")])

    def _simple(self, kind, seq, f):
        self.send(kind, seq, [("TXN", f.get("TXN", ""))])

    txn_RegisterGame = _simple
    txn_SendAccountName = _simple
    txn_SendAccountPassword = _simple

    # --- солдаты ---------------------------------------------------------------

    def txn_GetSubAccounts(self, kind, seq, f):
        if not self._need_account(kind, seq, "GetSubAccounts"):
            return
        soldiers = self.db.soldiers(self.account["id"])
        fields = [("TXN", "GetSubAccounts")]
        fields += [(f"subAccounts.{i}", s["name"]) for i, s in enumerate(soldiers)]
        fields.append(("subAccounts.[]", len(soldiers)))
        self.send(kind, seq, fields)

    def txn_AddSubAccount(self, kind, seq, f):
        if not self._need_account(kind, seq, "AddSubAccount"):
            return
        name = f.get("name", "")
        if not valid_name(name):
            return self.name_error(kind, seq, "AddSubAccount", name)
        try:
            pid = self.db.create_soldier(self.account["id"], name, self.cfg.max_soldiers)
        except dbmod.AlreadyExists:
            return self.error(kind, seq, "AddSubAccount", 160, "LOCERROR_soldiernameexists")
        except dbmod.LimitReached:
            return self.error(kind, seq, "AddSubAccount", 163, "Too many soldiers")
        log.info("%s: создан солдат %s (pid %d)", self.addr[0], name, pid)
        self.send(kind, seq, [("TXN", "AddSubAccount")])

    def txn_DisableSubAccount(self, kind, seq, f):
        if self._need_account(kind, seq, "DisableSubAccount"):
            self.db.disable_soldier(self.account["id"], f.get("name", ""))
            log.info("%s: удалён солдат %s", self.addr[0], f.get("name", ""))
            self.send(kind, seq, [("TXN", "DisableSubAccount")])

    def txn_LoginSubAccount(self, kind, seq, f):
        if not self._need_account(kind, seq, "LoginSubAccount"):
            return
        soldier = self.db.soldier_by_name(f.get("name", ""))
        if soldier is None or soldier["account_id"] != self.account["id"]:
            return self.error(kind, seq, "LoginSubAccount", 101, "The soldier was not found")
        self.soldier = soldier
        self.db.touch_soldier(soldier["id"])
        log.info("%s: выбран солдат %s (pid %d)", self.addr[0], soldier["name"], soldier["id"])
        self.send(kind, seq, [
            ("TXN", "LoginSubAccount"), ("lkey", _lkey()), ("profileId", soldier["id"]), ("userId", self.account["id"]),
        ])

    def txn_GameSpyPreAuth(self, kind, seq, f):
        if self.soldier is None:
            return self.error(kind, seq, "GameSpyPreAuth", 101, "No soldier selected")
        if self.banned(kind, seq, "GameSpyPreAuth", self.account["id"]):  # забанен уже после входа
            return
        token, ticket = self.ctx.tickets.issue(self.soldier["id"], self.account["id"], self.soldier["name"])
        self.send(kind, seq, [("TXN", "GameSpyPreAuth"), ("challenge", ticket.challenge), ("ticket", token)])

    # --- subs / dobj ------------------------------------------------------------

    def txn_GetEntitlementByBundle(self, kind, seq, f):
        self.send(kind, seq, [("TXN", "GetEntitlementByBundle"), ("EntitlementByBundle.[]", 0)])

    def txn_GetObjectInventory(self, kind, seq, f):
        # Клиент спрашивает дополнение Northern Strike: domainId=eagames, objectIds.0=bf2142_bp1
        # (ещё бывают домен cqc и bf2142_bp1_beta — их не выдаём). Из ответа он смотрит entitlements.[].
        wanted = [f.get(f"objectIds.{i}", "") for i in range(int(f.get("objectIds.[]", 0) or 0))]
        owned = []
        if self.ctx.cfg.northern_strike and f.get("domainId") == "eagames" and "bf2142_bp1" in wanted:
            owned.append("bf2142_bp1")
        fields = [("TXN", "GetObjectInventory"), ("entitlements.[]", len(owned))]
        for i, obj in enumerate(owned):
            fields += [(f"entitlements.{i}.objectId", obj), (f"entitlements.{i}.entitlementId", i + 1),
                       (f"entitlements.{i}.useCount", 0), (f"entitlements.{i}.editionNo", 0),
                       (f"entitlements.{i}.dateEntitled", "2007-03-13 00:00:00.0 UTC")]
        self.send(kind, seq, fields)


def serve(ctx: Context):
    creds = ServerCredentials(DATA_DIR)

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            FeslSession(ctx, creds, self.request, self.client_address).run()

    with TCPServer((ctx.cfg.bind, ctx.cfg.fesl_port), Handler) as server:
        log.info("FESL (SSLv3) слушает %s:%d", ctx.cfg.bind, ctx.cfg.fesl_port)
        server.serve_forever()
