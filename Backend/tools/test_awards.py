"""Модульные тесты наград (без сети, на временной базе).

    .venv\\Scripts\\python.exe tools\\test_awards.py
"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bf2142srv import eacrypt, rounds  # noqa: E402
from bf2142srv.config import Config  # noqa: E402
from bf2142srv.context import Context, TicketStore  # noqa: E402
from bf2142srv.db import Database  # noqa: E402
from bf2142srv.stats_http import StatsService  # noqa: E402

failures = 0


def check(cond, what):
    global failures
    print(("  OK   " if cond else "  FAIL ") + what)
    failures += not cond


END = int(time.time())


def play(ctx, players, mapname="minsk", gm="gpm_cq", win=1, extra_info=""):
    """Раунд: players — список словарей ключей игрока (pid, t и т. п.)."""
    global END
    END += 3600
    lines = [f"v=1\nmap={mapname}\ngm={gm}\nwin={win}\nai=0\nstart={END - 600}\nend={END}\n{extra_info}"]
    for p in players:
        p = {"t": 1, "tt": 600, "gsco": 0, "crpt": 0, **p}
        lines.append("P\t" + "\t".join(f"{k}={v}" for k, v in p.items()) + "\n")
    rounds.apply_round(ctx, "".join(lines).encode(), "127.0.0.1")


def last_awards(db, pid):
    return db.round_history(pid, 1)[0][1].get("awards", [])


def main():
    tmp = Path(tempfile.mkdtemp())
    cfg = Config(db_path=tmp / "t.sqlite3", min_round_seconds=60)
    db = Database(cfg.db_path)
    ctx = Context(cfg, db, TicketStore())
    acc = db.create_account("acc", "pw")
    pid = db.create_soldier(acc, "Hero", 4)
    others = [db.create_soldier(db.create_account(f"o{i}", "pw"), f"Other{i}", 4) for i in range(4)]

    print("Значки по уровням:")
    play(ctx, [{"pid": pid, "kkls-3": 12}])
    check(last_awards(db, pid) == ["100_1"], f"12 убийств с поддержкой -> бронза 100_1 ({last_awards(db, pid)})")
    check(db.stats(pid)["crpt"] == cfg.award_xp_badge[0], f"бонус за бронзу: crpt={db.stats(pid)['crpt']}")
    play(ctx, [{"pid": pid, "kkls-3": 12}])
    check(last_awards(db, pid) == [], "повторно тот же значок не выдаётся")
    play(ctx, [{"pid": pid, "kkls-3": 20}])
    check("100_2" not in last_awards(db, pid), "серебро без 15 часов с набором — нет")
    db.set_stats(pid, {"ktt-3": 54000 - 600})
    play(ctx, [{"pid": pid, "kkls-3": 20, "ktt-3": 600}])
    check(last_awards(db, pid) == ["100_2"], f"20 убийств и 15 часов с набором -> серебро ({last_awards(db, pid)})")
    other = others[0]
    db.set_stats(other, {"ktt-3": 200000})
    play(ctx, [{"pid": other, "kkls-3": 30}])
    check(last_awards(db, other) == ["100_1", "100_2", "100_3"],
          f"все условия выполнены — все три уровня за один раунд ({last_awards(db, other)})")
    play(ctx, [{"pid": others[1], "kkls-3": 30}])
    check(last_awards(db, others[1]) == ["100_1"], f"без часов с набором — только бронза ({last_awards(db, others[1])})")

    print("Значки отличия и медали:")
    play(ctx, [{"pid": pid, "klstrk": 5}])
    play(ctx, [{"pid": pid, "klstrk": 6}])
    check(db.awards(pid).get("400", {}).get("count") == 2, "значок отличия 400 (серия 5) — дважды за два раунда")
    for badge in ("101_1", "102_1", "103_1", "105_1", "106_1", "107_1"):
        db.add_award(pid, badge, END)
    play(ctx, [{"pid": pid, "klstrk": 10}])
    got = last_awards(db, pid)
    check(got == ["400", "401", "204"], f"серия 10 + все бронзовые значки -> 400, 401 и медаль 204 ({got})")
    play(ctx, [{"pid": pid, "dths": 12, "klls": 2}])
    check("216" in last_awards(db, pid), "Purple Heart: 2 убийства при 12 смертях")
    play(ctx, [{"pid": pid, "dths": 5, "klls": 1}])
    check("216" not in last_awards(db, pid), "Purple Heart не за 5 смертей")

    print("Ленты и места:")
    play(ctx, [{"pid": pid, "vtp-8": 12}])
    check(last_awards(db, pid) == ["302"], f"10 с в парашюте -> лента HALO 302 ({last_awards(db, pid)})")
    play(ctx, [{"pid": pid, "vtp-8": 12}])
    check("302" not in last_awards(db, pid), "лента второй раз не выдаётся")
    play(ctx, [{"pid": pid, "gsco": 50}, {"pid": others[1], "gsco": 40}, {"pid": others[2], "gsco": 30},
               {"pid": others[3], "gsco": 20}])
    check("202" in last_awards(db, pid) and "201" in last_awards(db, others[1])
          and "200" in last_awards(db, others[2]) and not last_awards(db, others[3]),
          "золото, серебро, бронза за 1–3 место, 4-му ничего")
    play(ctx, [{"pid": others[3], "gsco": 5}])
    check("202" in last_awards(db, others[3]), "один в раунде — тоже первое место")

    print("Статистика по режимам, картам и фракциям:")
    hero = Database(cfg.db_path)
    s0 = hero.stats(pid)
    play(ctx, [{"pid": pid, "klls": 7, "klstrk": 4, "gsco": 33, "t": 2}], mapname="belgrade", gm="gpm_ti", win=2,
         extra_info="mapid=7\ngmid=1\narmy1=1\narmy2=0\n")
    s = hero.stats(pid)
    check(s.get("tgpm-1", 0) - s0.get("tgpm-1", 0) == 600 and s.get("kgpm-1", 0) - s0.get("kgpm-1", 0) == 7,
          "Titan: время и убийства по режиму")
    check(s.get("mtt-1-7", 0) - s0.get("mtt-1-7", 0) == 600 and s.get("mwin-1-7", 0) - s0.get("mwin-1-7", 0) == 1
          and s.get("mbr-1-7") == 33, "Белград в Titan: время, победа, лучший раунд")
    check(s.get("attp-0", 0) - s0.get("attp-0", 0) == 600 and s.get("awin-0", 0) - s0.get("awin-0", 0) == 1,
          "команда 2 = ЕС: время и победа за ЕС")
    check(s.get("bksgpm-1") == 4, "лучшая серия в Titan")

    print("getawardsinfo:")
    svc = StatsService(ctx)
    status, _, body = svc.handle("GET", "/getawardsinfo.aspx", {"auth": eacrypt.encode(pid)}, b"", "127.0.0.1")
    text = body.decode()
    check(status == 200 and "H\taward\tlevel\twhen\tfirst" in text, "заголовки ответа")
    check("\nD\t100_1\t0\t" in text and "\nD\t400\t3\t" in text and "\nD\t302\t0\t" in text,
          "значок 100_1 (level 0), значок отличия 400 трижды, лента 302")
    status, _, body = svc.handle("GET", "/getplayerinfo.aspx", {"auth": eacrypt.encode(pid), "mode": "award"},
                                 b"", "127.0.0.1")
    check(status == 200 and "ktt-3" in body.decode() and "mtt-0-0" in body.decode(),
          "getplayerinfo mode=award отдаёт ключи из условий (в том числе нулевые)")

    print("\nИТОГ:", "всё работает" if failures == 0 else f"ошибок: {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
