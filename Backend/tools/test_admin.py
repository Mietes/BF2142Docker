"""Модульные тесты администрирования (без сети, на временной базе): подпись запросов игровых
серверов, повтор итогов раунда, баны, правила имён.

    .venv\\Scripts\\python.exe tools\\test_admin.py
"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bf2142srv import admin  # noqa: E402
from bf2142srv.master import GameServer, _ip_for  # noqa: E402
from bf2142srv.config import Config  # noqa: E402
from bf2142srv.context import Context, TicketStore  # noqa: E402
from bf2142srv.db import Database  # noqa: E402
from bf2142srv.servers import signature  # noqa: E402
from bf2142srv.stats_http import StatsService  # noqa: E402

failures = 0
SECRET = "test-secret"


def check(cond, what):
    global failures
    print(("  OK   " if cond else "  FAIL ") + what)
    failures += not cond


def request(svc, method, path, body=b"", ip="127.0.0.1", secret=SECRET, ts=None):
    ts = str(int(time.time()) if ts is None else ts)
    params = {"ts": ts, "sig": signature(secret, ts, path, body)} if secret else {}
    status, _, data = svc.handle(method, path, params, body, ip)
    return status, data.decode()


def main():
    tmp = Path(tempfile.mkdtemp())
    cfg = Config(db_path=tmp / "t.sqlite3", server_secret=SECRET, admins=["Boss"], idle_kick_minutes=5)
    db = Database(cfg.db_path)
    ctx = Context(cfg, db, TicketStore())
    svc = StatsService(ctx)
    acc = db.create_account("player", "pw")
    pid = db.create_soldier(acc, "Hero", 4)
    boss = db.create_soldier(db.create_account("boss", "pw"), "Boss", 4)

    print("Имена и сроки:")
    check(all(admin.valid_name(n) for n in ("abc", "Tester1", "A" * 16)), "латиница и цифры, 3–16 — можно")
    check(not any(admin.valid_name(n) for n in ("ab", "A" * 17, "Bad-Name", "Имя", "a b", "x_y", "")),
          "короче 3, длиннее 16, дефис, кириллица, пробел, подчёркивание — нельзя")
    check([admin.parse_duration(x) for x in ("30m", "12h", "7d", "2w", "90", "perm")] == [30, 720, 10080, 20160, 90, None],
          "сроки банов 30m/12h/7d/2w/90/perm")
    try:
        admin.parse_duration("cheater")
        check(False, "не срок -> ValueError")
    except ValueError:
        check(True, "не срок -> ValueError")

    print("Подпись запросов игровых серверов:")
    end = int(time.time())
    body = (f"v=1\nmap=minsk\ngm=gpm_cq\nwin=1\nai=0\nstart={end - 600}\nend={end}\n"
            f"P\tpid={pid}\tnick=Hero\tt=1\tgsco=10\tcrpt=100\ttt=600\n").encode()
    check(request(svc, "POST", "/selfhost/snapshot", body, secret=None)[0] == 403, "без подписи — 403")
    check(request(svc, "POST", "/selfhost/snapshot", body, secret="other")[0] == 403, "чужой секрет — 403")
    check(request(svc, "POST", "/selfhost/snapshot", body, ts=end - 3600)[0] == 403, "подпись часовой давности — 403")
    check(db.stats(pid).get("crpt") is None, "отклонённые итоги не засчитаны")
    check(request(svc, "POST", "/selfhost/snapshot", body) == (200, "OK"), "подписанные итоги приняты")
    xp = db.stats(pid).get("crpt")
    check(request(svc, "POST", "/selfhost/snapshot", body) == (200, "DUPLICATE") and db.stats(pid).get("crpt") == xp,
          f"повтор не засчитан (опыт остался {xp})")
    cfg.server_ips = ["10.0.0.5"]
    check(request(svc, "GET", "/selfhost/serverinfo")[0] == 403, "адреса нет в allowed_ips — 403")
    check(request(svc, "GET", "/selfhost/serverinfo", ip="10.0.0.5")[0] == 200, "адрес из allowed_ips — 200")
    cfg.server_ips = []

    print("Баны:")
    status, info = request(svc, "GET", "/selfhost/serverinfo")
    check(f"admins={boss}\n" in info and "banned=\n" in info and "idle_kick=300\n" in info,
          "serverinfo: админ Boss, банов нет, кик через 300 с")
    check(request(svc, "POST", "/selfhost/ban", f"pid={pid}&minutes=60&reason=wallhack&by=Boss".encode())[1] == "OK",
          "бан из игры на час")
    ban = db.active_ban(acc)
    check(ban is not None and 3590 < ban["until"] - time.time() <= 3600 and ban["reason"] == "wallhack",
          f"бан записан: {admin.describe_ban(ban)}")
    check(f"banned={pid}\n" in request(svc, "GET", "/selfhost/serverinfo")[1], "солдат в списке для кика")
    check(request(svc, "POST", "/selfhost/unban", b"nick=Hero&by=Boss")[1] == "OK" and db.active_ban(acc) is None,
          "разбан из игры")
    check(request(svc, "POST", "/selfhost/unban", b"nick=Hero&by=Boss")[1] == "NOTBANNED", "повторный разбан: не забанен")
    check(request(svc, "POST", "/selfhost/ban", b"pid=999&by=Boss")[1] == "NOTFOUND", "бан несуществующего солдата")
    db.add_ban(acc, None, "", "консоль", ip="1.2.3.4")
    check(db.active_ban(acc)["until"] is None, "бан навсегда")
    check(db.active_ban(None, "1.2.3.4") is not None and db.active_ban(None, "5.6.7.8") is None,
          "IP-бан мешает новым аккаунтам только с этого адреса")
    db.lift_bans(acc)
    check(db.active_ban(None, "1.2.3.4") is None, "разбан аккаунта снимает и его IP-бан")
    db.add_ban(acc, 1)
    db._conn.execute("UPDATE bans SET until=? WHERE account_id=? AND lifted IS NULL", (int(time.time()) - 1, acc))
    check(db.active_ban(acc) is None and db.banned_pids() == [], "истёкший бан не действует")

    print("Настройки сервера из панели:")
    sc = ctx.server
    status, reply = request(svc, "POST", "/selfhost/status",
                            b"config=0\nmap=minsk\nmode=gpm_cq\nsv.serverName=Test\nplayer=3\tHero\t%d\t1\t50\t5\t2\t40\n" % pid)
    check(status == 200 and "config=0" in reply and f"admins={boss}" in reply, "статус сервера принят, в ответе админы и версия")
    st = sc.current_status()
    check(st["map"] == "minsk" and st["settings"]["serverName"] == "Test" and st["players"][0]["name"] == "Hero",
          "панель видит карту, настройки и игроков")
    for bad, why in (({"soldierFriendlyFire": 150}, "огонь 150%"), ({"nope": 1}, "неизвестный ключ")):
        try:
            sc.save(settings=bad)
            check(False, f"отказ: {why}")
        except ValueError:
            check(True, f"отказ: {why}")
    try:
        sc.save(maplist=[["minsk", "gpm_ti", 64]])
        check(False, "отказ: Титан на 64 на Минске (бывает только 48)")
    except ValueError:
        check(True, "отказ: Титан на 64 на Минске (бывает только 48)")
    try:
        sc.save(settings={"serverName": "Мой сервер"})
        check(False, "отказ: кириллица в названии")
    except ValueError:
        check(True, "отказ: кириллица в названии")
    version = sc.save(settings={"serverName": 'My "server"\n', "soldierFriendlyFire": "0", "tkPunishEnabled": False},
                      maplist=[["minsk", "gpm_ti", 48], ["outpost_87", "gpm_cq", 64]])
    lines = request(svc, "GET", "/selfhost/serverconfig")[1].splitlines()
    check(lines[0] == f"version={version}" and 'sv.serverName "My server"' in lines and "sv.soldierFriendlyFire 0" in lines
          and "sv.tkPunishEnabled 0" in lines and lines[-2:] == ["mapList.append minsk gpm_ti 48",
                                                                "mapList.append outpost_87 gpm_cq 64"],
          f"конфиг для сервера: кавычки и переводы строк вычищены ({lines[1:4]})")
    sc.queue("next_map")
    sc.queue("say", "Привет")
    reply = request(svc, "POST", "/selfhost/status", b"config=0\n")[1]
    check(f"config={version}" in reply and "cmd=next_map" in reply and "cmd=say Привет" in reply,
          "в ответе новая версия и команды")
    check("cmd=" not in request(svc, "POST", "/selfhost/status", b"config=0\n")[1], "команды отдаются один раз")

    print("Адрес игрового сервера в списке:")
    local = GameServer("203.0.113.5", 29900, b"k", local_ip="127.0.0.1")  # сервер на машине бэкенда
    check(_ip_for("127.0.0.1", local) == "127.0.0.1", "хозяину на той же машине — 127.0.0.1")
    check(_ip_for("95.31.18.119", local) == "203.0.113.5", "игроку из интернета — внешний адрес")
    check(_ip_for("26.10.20.30", local) == "203.0.113.5", "игроку из Radmin (26.x) — public_host")
    check(_ip_for("192.168.1.20", local) == "203.0.113.5", "соседу по сети 127.0.0.1 не годится — внешний")
    lan = GameServer("203.0.113.5", 29900, b"k", local_ip="192.168.1.10")  # сервер на другом ПК дома
    check(_ip_for("192.168.1.20", lan) == "192.168.1.10" and _ip_for("127.0.0.1", lan) == "192.168.1.10",
          "сервер на другом ПК в домашней сети — своим его локальный адрес")
    check(_ip_for("95.31.18.119", lan) == "203.0.113.5", "чужим — внешний")
    docker = GameServer("203.0.113.5", 29900, b"k", local_ip="172.20.0.3")  # сервер в контейнере
    check(_ip_for("172.20.0.1", docker, lan=False) == "203.0.113.5",
          "Docker (lan выключен): даже из внутренней сети — внешний адрес")

    print("\nИТОГ:", "всё работает" if failures == 0 else f"ошибок: {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
