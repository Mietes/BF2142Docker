"""Запуск: .venv\\Scripts\\python.exe -m bf2142srv"""

import logging
import sys
import threading
import time

from . import admin_web, config, fesl, gpcm, master, stats_http
from .context import Context, TicketStore
from .db import Database


def main():
    cfg = config.load()
    config.DATA_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)-6s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.DATA_DIR / "backend.log", encoding="utf-8"),
        ],
    )
    log = logging.getLogger("main")
    ctx = Context(cfg, Database(cfg.db_path), TicketStore())
    log.info("режим анлоков: %s; публичный адрес: %s", cfg.unlock_mode, cfg.public_host)

    services = {"fesl": fesl.serve, "gpcm": gpcm.serve, "stats": stats_http.serve, "master": master.serve,
                "admin": admin_web.serve}
    errors = []

    def run(name, fn):
        try:
            fn(ctx)
        except OSError as e:
            errors.append(name)
            log.error("%s не запустился: %s (порт занят или нет прав?)", name, e)
        except Exception:
            errors.append(name)
            log.exception("%s упал", name)

    for name, fn in services.items():
        threading.Thread(target=run, args=(name, fn), name=name, daemon=True).start()
    time.sleep(1)
    if errors:
        log.error("не запущены: %s", ", ".join(errors))
    else:
        log.info("бэкенд запущен, Ctrl+C — остановка")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        log.info("остановка")


if __name__ == "__main__":
    main()
