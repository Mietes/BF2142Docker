"""Общее состояние сервисов: конфиг, БД, тикеты входа FESL -> GPCM."""

import secrets
import threading
import time
from dataclasses import dataclass

from .config import Config
from .db import Database
from .server_config import ServerConfig


@dataclass
class Ticket:
    pid: int
    account_id: int
    name: str
    challenge: str
    created: float


class TicketStore:
    """FESL выдаёт тикет в GameSpyPreAuth, клиент предъявляет его в GPCM как authtoken."""

    TTL = 600

    def __init__(self):
        self._lock = threading.Lock()
        self._tickets: dict[str, Ticket] = {}

    def issue(self, pid, account_id, name) -> tuple[str, Ticket]:
        token = secrets.token_urlsafe(48)
        challenge = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(8))
        ticket = Ticket(pid, account_id, name, challenge, time.time())
        with self._lock:
            now = time.time()
            for key in [k for k, t in self._tickets.items() if now - t.created > self.TTL]:
                del self._tickets[key]
            self._tickets[token] = ticket
        return token, ticket

    def get(self, token) -> Ticket | None:
        with self._lock:
            return self._tickets.get(token)


@dataclass
class Context:
    cfg: Config
    db: Database
    tickets: TicketStore
    server: ServerConfig | None = None  # настройки игрового сервера из админки, его состояние, команды

    def __post_init__(self):
        if self.server is None:
            self.server = ServerConfig(self.db)
