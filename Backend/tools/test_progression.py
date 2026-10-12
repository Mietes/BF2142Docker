"""Модульные тесты системы прокачки (без сети, на временной базе).

    .venv\\Scripts\\python.exe tools\\test_progression.py
"""

import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bf2142srv import progression, rounds  # noqa: E402
from bf2142srv.config import Config  # noqa: E402
from bf2142srv.context import Context, TicketStore  # noqa: E402
from bf2142srv.db import Database  # noqa: E402
from bf2142srv.stats_http import StatsService  # noqa: E402

failures = 0


def check(cond, what):
    global failures
    print(("  OK   " if cond else "  FAIL ") + what)
    failures += not cond


def snapshot(pid, crpt, team=1, win=1, ai=0, end=None, tt=600):
    end = end or int(time.time())
    return (f"v=1\nmap=minsk\ngm=gpm_cq\nwin={win}\nai={ai}\nstart={end - tt}\nend={end}\n"
            f"P\tpid={pid}\tnick=x\tt={team}\tgsco={crpt}\tcrpt={crpt}\ttt={tt}\n").encode()


def main():
    tmp = Path(tempfile.mkdtemp())
    cfg = Config(db_path=tmp / "t.sqlite3", min_round_seconds=60, awards=False)  # награды — в test_awards.py
    db = Database(cfg.db_path)
    ctx = Context(cfg, db, TicketStore())
    acc = db.create_account("acc", "pw")

    print("Очки анлоков по званиям (3 + 2×10 + 1×27):")
    for rank, want in [(0, 3), (1, 5), (10, 23), (11, 24), (37, 50), (40, 50)]:
        check(progression.earned_credits(cfg, rank) == want, f"звание {rank}: {progression.earned_credits(cfg, rank)} (ждём {want})")

    print("Множители опыта:")
    pid = db.create_soldier(acc, "Xp", 4)
    day = int(time.time())
    rounds.apply_round(ctx, snapshot(pid, 100, end=day), "127.0.0.1")
    check(db.stats(pid)["crpt"] == 240, f"первая победа за сутки: 100 × 1.2 × 2 = {db.stats(pid)['crpt']}")
    rounds.apply_round(ctx, snapshot(pid, 100, end=day + 60), "127.0.0.1")
    check(db.stats(pid)["crpt"] == 360, f"вторая победа: +120 (всего {db.stats(pid)['crpt']})")
    rounds.apply_round(ctx, snapshot(pid, 100, team=2, end=day + 120), "127.0.0.1")
    check(db.stats(pid)["crpt"] == 460, f"поражение: +100 (всего {db.stats(pid)['crpt']})")
    rounds.apply_round(ctx, snapshot(pid, 100, ai=1, end=day + 180), "127.0.0.1")
    check(db.stats(pid)["crpt"] == 520, f"кооп-победа: 100 × 0.5 × 1.2 = +60 (всего {db.stats(pid)['crpt']})")
    rounds.apply_round(ctx, snapshot(pid, 100, end=day + 86400), "127.0.0.1")
    check(db.stats(pid)["crpt"] == 760, f"победа на следующие сутки снова ×2: +240 (всего {db.stats(pid)['crpt']})")
    check(db.stats(pid)["gsco"] == 500, f"общий счёт без бонусов: {db.stats(pid)['gsco']}")
    check(db.stats(pid)["rnk"] == 7, f"звание по опыту 760: {db.stats(pid)['rnk']}")

    print("Недельный топ (спецзвания):")
    now = datetime.now()
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    last_week = int((monday - timedelta(days=3)).timestamp())
    generals = []
    for i in range(12):
        g = db.create_soldier(db.create_account(f"g{i}", "pw"), f"Gen{i}", 4)
        db.set_stats(g, {"rnk": 40, "crpt": 60000})
        rounds.apply_round(ctx, snapshot(g, 1000 + i * 10, team=2, end=last_week + i), "127.0.0.1")  # поражения: без бонусов
        generals.append(g)
    rookie = db.create_soldier(db.create_account("rookie", "pw"), "Rookie", 4)
    rounds.apply_round(ctx, snapshot(rookie, 5000, team=2, end=last_week), "127.0.0.1")
    this_week = db.create_soldier(db.create_account("fresh", "pw"), "Fresh", 4)
    db.set_stats(this_week, {"rnk": 40, "crpt": 60000})
    rounds.apply_round(ctx, snapshot(this_week, 9999, team=2, end=int(time.time())), "127.0.0.1")

    svc = StatsService(ctx)
    top = svc.weekly_top()
    best = generals[::-1]  # больше всех опыта у последнего
    check(top.get(best[0]) == 43, "1-е место — звание 43")
    check(top.get(best[1]) == 42 and top.get(best[2]) == 42, "2–3-е места — звание 42")
    check(all(top.get(g) == 41 for g in best[3:10]), "4–10-е места — звание 41")
    check(best[10] not in top and best[11] not in top, "11-е и ниже — без спецзвания")
    check(rookie not in top, "не генерал в топ не попадает, сколько бы ни набрал")
    check(this_week not in top, "считается прошлая неделя, текущая — нет")
    p = svc.player(best[0])
    check(p.values["rnk"] == 43 and p.available == 50, f"показываем 43, а очки анлоков — от звания 40 ({p.available})")

    print("\nИТОГ:", "всё работает" if failures == 0 else f"ошибок: {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
