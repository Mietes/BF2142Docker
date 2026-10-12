"""Управление аккаунтами и солдатами напрямую в базе бэкенда.

    .venv\\Scripts\\python.exe tools\\accounts.py list
    .venv\\Scripts\\python.exe tools\\accounts.py add <логин> <пароль> [солдат ...]
    .venv\\Scripts\\python.exe tools\\accounts.py soldier <логин> <солдат>
    .venv\\Scripts\\python.exe tools\\accounts.py passwd <логин или солдат> <новый пароль>
    .venv\\Scripts\\python.exe tools\\accounts.py stats <солдат>
    .venv\\Scripts\\python.exe tools\\accounts.py ban <логин или солдат> [30m|12h|7d|perm] [причина ...] [--ip]
    .venv\\Scripts\\python.exe tools\\accounts.py unban <логин или солдат>
    .venv\\Scripts\\python.exe tools\\accounts.py bans

Бан без срока — навсегда. --ip банит ещё и IP последнего входа (с него нельзя ни войти, ни
завести новый аккаунт); осторожно: у провайдеров с общим IP заденет и других игроков.
Игровой сервер кикает забаненного в течение пары минут.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bf2142srv import config, db as dbmod, progression  # noqa: E402
from bf2142srv.admin import NAME_RULE, describe_ban, parse_duration, resolve_account, valid_name  # noqa: E402


def need_valid(*names):
    for name in names:
        if not valid_name(name):
            sys.exit(f"недопустимое имя {name!r}: {NAME_RULE}")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cfg = config.load()
    db = dbmod.Database(cfg.db_path)
    cmd, args = sys.argv[1], sys.argv[2:]

    if cmd == "list":
        for a in db._all("SELECT * FROM accounts ORDER BY id"):
            soldiers = ", ".join(f"{s['name']} (pid {s['id']}, звание {int(db.stats(s['id']).get('rnk', 0))})"
                                 for s in db.soldiers(a["id"]))
            banned = " [БАН]" if db.active_ban(a["id"]) else ""
            print(f"#{a['id']} {a['name']}{banned}: {soldiers or 'нет солдат'}")
    elif cmd == "add" and len(args) >= 2:
        need_valid(args[0], *args[2:])
        account_id = db.create_account(args[0], args[1])
        print(f"аккаунт {args[0]} (#{account_id})")
        for name in args[2:]:
            print(f"  солдат {name} (pid {db.create_soldier(account_id, name, cfg.max_soldiers)})")
    elif cmd == "soldier" and len(args) == 2:
        need_valid(args[1])
        account = db.account_by_name(args[0]) or sys.exit("нет такого аккаунта")
        print(f"солдат {args[1]} (pid {db.create_soldier(account['id'], args[1], cfg.max_soldiers)})")
    elif cmd == "passwd" and len(args) == 2:
        account = resolve_account(db, args[0]) or sys.exit("нет такого аккаунта или солдата")
        with db.transaction():
            db._conn.execute("UPDATE accounts SET password_hash=?, login_token=NULL WHERE id=?",
                             (dbmod.hash_password(args[1]), account["id"]))
        print(f"пароль аккаунта {account['name']} изменён")
    elif cmd == "stats" and len(args) == 1:
        soldier = db.soldier_by_name(args[0]) or sys.exit("нет такого солдата")
        s = db.stats(soldier["id"])
        levels = db.unlocks(soldier["id"])
        rank = int(s.get("rnk", 0))
        print(f"{soldier['name']} (pid {soldier['id']}): звание {rank}, опыт {s.get('crpt', 0)}, "
              f"очки {s.get('gsco', 0)}, убийства {s.get('klls', 0)}, смерти {s.get('dths', 0)}")
        print(f"анлоки: {' '.join(progression.unlock_ids(levels)) or 'нет'}; свободных очков: "
              f"{max(0, progression.earned_credits(cfg, rank) - progression.spent_credits(levels))}")
    elif cmd == "ban" and args:
        with_ip = "--ip" in args
        args = [a for a in args if a != "--ip"]
        account = resolve_account(db, args[0]) or sys.exit("нет такого аккаунта или солдата")
        minutes, reason = None, args[1:]
        if reason:
            try:
                minutes, reason = parse_duration(reason[0]), reason[1:]
            except ValueError:
                pass  # первое слово — уже причина, бан навсегда
        ip = account["last_ip"] if with_ip else ""
        if with_ip and not ip:
            print("IP последнего входа неизвестен — баню только аккаунт")
        db.add_ban(account["id"], minutes, " ".join(reason), "консоль", ip)
        print(f"аккаунт {account['name']} забанен: {describe_ban(db.active_ban(account['id']))}")
    elif cmd == "unban" and len(args) == 1:
        account = resolve_account(db, args[0]) or sys.exit("нет такого аккаунта или солдата")
        lifted = db.lift_bans(account["id"])
        print(f"аккаунт {account['name']}: снято банов: {lifted}" if lifted else f"аккаунт {account['name']} не забанен")
    elif cmd == "bans":
        bans = db.active_bans()
        for b in bans:
            print(f"{b['account'] or '(только IP)'}: {describe_ban(b)}")
        print(f"действующих банов: {len(bans)}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
