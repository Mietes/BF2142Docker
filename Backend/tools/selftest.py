"""Самотест запущенного бэкенда: проходит путь клиента игры по всем сервисам.

    .venv\\Scripts\\python.exe tools\\selftest.py [адрес] [http-порт]
"""

import secrets
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tlslite.api import HandshakeSettings, TLSConnection  # noqa: E402

from bf2142srv import awards, config, eacrypt, progression  # noqa: E402
from bf2142srv.db import Database  # noqa: E402
from bf2142srv.fesl import encode_packet, parse_fields  # noqa: E402
from bf2142srv.gpcm import decode as gp_decode, encode as gp_encode, login_hash  # noqa: E402
from bf2142srv.servers import signature  # noqa: E402

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
HTTP_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else config.load().http_port
failures = 0


def check(cond, what):
    global failures
    print(("  OK   " if cond else "  FAIL ") + what)
    if not cond:
        failures += 1


class Fesl:
    def __init__(self):
        s = HandshakeSettings()
        s.minVersion = s.maxVersion = (3, 0)
        s.cipherNames, s.macNames, s.keyExchangeNames = ["rc4"], ["sha", "md5"], ["rsa"]
        self.conn = TLSConnection(socket.create_connection((HOST, 18300), timeout=10))
        self.conn.handshakeClientCert(settings=s)
        self.seq = 0

    def recv(self):
        hdr = self.conn.read(max=12, min=12)
        length = int.from_bytes(hdr[8:12], "big")
        return parse_fields(self.conn.read(max=length - 12, min=length - 12))

    def call(self, kind, **fields):
        self.seq += 1
        self.conn.write(encode_packet(kind, self.seq, list(fields.items()), flags=0xC0))
        return self.recv()


def server_list(fields):
    """Запрос списка как у клиента игры (enctypeX), разбор ответа."""
    import struct
    from bf2142srv import enctypex
    validate = b"Ab3dEf7h"
    body = (b"\x00\x01\x03\x00\x00\x00\x00" + b"stella\0stella\0" + validate + b"\0"
            + ("\\" + "\\".join(fields)).encode() + b"\0" + b"\x00\x00\x00\x00")
    s = socket.create_connection((HOST, 28910), timeout=10)
    s.sendall(struct.pack(">H", len(body) + 2) + body)
    data, plain = b"", b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
        try:
            chal, enc = enctypex.split_header(data)
            plain = enctypex.EnctypeX(b"M8o1Qw", validate, chal).decrypt(enc)
            if plain.endswith(b"\0\xff\xff\xff\xff"):
                break
        except (IndexError, ValueError):
            pass
    s.close()
    p = 6
    nkeys = plain[p]; p += 1
    keys = []
    for _ in range(nkeys):
        p += 1
        end = plain.index(b"\0", p); keys.append(plain[p:end].decode()); p = end + 1
    p += 1  # популярные значения: 0
    result = []
    while plain[p:p + 5] != b"\0\xff\xff\xff\xff":
        flags = plain[p]; p += 1
        ip = socket.inet_ntoa(plain[p:p + 4]); port = struct.unpack(">H", plain[p + 4:p + 6])[0]
        p += 4 + (2 if flags & 0x10 else 0) + (4 if flags & 0x02 else 0) + (2 if flags & 0x20 else 0) + (4 if flags & 0x08 else 0)
        entry = {"ip": ip, "port": port}
        for k in keys:
            assert plain[p] == 0xFF; p += 1
            end = plain.index(b"\0", p); entry[k] = plain[p:end].decode("latin-1"); p = end + 1
        result.append(entry)
    return result


def http(page, **params):
    from urllib.parse import urlencode
    url = f"http://{HOST}:{HTTP_PORT}/{page}?{urlencode(params)}"
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read().decode()


def game_server(method, path, body=b"", sign=True, secret=None):
    """Запрос как от игрового сервера (selfhost.py): (HTTP-статус, тело)."""
    url = f"http://{HOST}:{HTTP_PORT}{path}"
    if sign:
        ts = str(int(time.time()))
        url += f"?ts={ts}&sig={signature(secret or config.load().server_secret, ts, path, body)}"
    req = urllib.request.Request(url, data=body if method == "POST" else None, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def fresh_login(name, password="pass123"):
    c = Fesl()
    c.call("fsys", TXN="Hello")
    c.recv()
    return c, c.call("acct", TXN="Login", name=name, password=password)


def main():
    user = "t" + secrets.token_hex(4)
    soldier_name = "S" + secrets.token_hex(4)

    print("FESL (SSLv3/RC4):")
    f = Fesl()
    check(f.conn.version == (3, 0) and "rc4" in f.conn.getCipherName(), f"рукопожатие {f.conn.version} {f.conn.getCipherName()}")
    hello = f.call("fsys", TXN="Hello", clientString="bf2142-pc", sku="125170", locale="en_US",
                   clientPlatform="PC", clientVersion="1.10.112.0", SDKVersion="2.8.0.1.0",
                   protocolVersion="2.0", fragmentSize="2048")
    memcheck = f.recv()
    check(hello.get("TXN") == "Hello" and memcheck.get("TXN") == "MemCheck", "Hello + MemCheck")
    login = f.call("acct", TXN="Login", returnEncryptedInfo="1", name=user, password="pass123", machineId="", macAddr="")
    check(login.get("TXN") == "Login" and "errorCode" not in login, f"Login/авторегистрация {user}")
    bad = Fesl()
    bad.call("fsys", TXN="Hello")
    bad.recv()
    wrong = bad.call("acct", TXN="Login", name=user, password="wrong")
    check(wrong.get("errorCode") == "122", "неверный пароль отклонён")
    relog = bad.call("acct", TXN="Login", encryptedInfo=login.get("encryptedLoginInfo", ""))
    check("errorCode" not in relog and relog.get("displayName") == user, "вход по encryptedInfo (запомнить пароль)")
    add = f.call("acct", TXN="AddSubAccount", name=soldier_name)
    check("errorCode" not in add, f"AddSubAccount {soldier_name}")
    dup = f.call("acct", TXN="AddSubAccount", name=soldier_name)
    check(dup.get("errorCode") == "160", "дубликат имени солдата отклонён")
    for bad_name in ("Bad-Name", "Солдат", "ab", "x" * 17):
        r = f.call("acct", TXN="AddSubAccount", name=bad_name)
        check(r.get("errorCode") == "21" and r.get("errorContainer.0.fieldName") == "Account.ScreenName",
              f"имя солдата {bad_name!r} отклонено (только латиница и цифры, 3–16)")
    _, r = fresh_login("bad_" + secrets.token_hex(2))
    check(r.get("errorCode") == "21", "авторегистрация с недопустимым логином отклонена")
    subs = f.call("acct", TXN="GetSubAccounts")
    check(subs.get("subAccounts.0") == soldier_name and subs.get("subAccounts.[]") == "1", "GetSubAccounts")
    acc = f.call("acct", TXN="GetAccount")
    check(acc.get("name") == user, "GetAccount")
    sub = f.call("acct", TXN="LoginSubAccount", name=soldier_name)
    pid = int(sub.get("profileId", 0))
    check(pid > 2000, f"LoginSubAccount, pid {pid} > 2000")
    pre = f.call("acct", TXN="GameSpyPreAuth")
    check(bool(pre.get("ticket")), "GameSpyPreAuth выдал тикет")
    ent = f.call("subs", TXN="GetEntitlementByBundle", bundleId="REG-PC-BF2142-UNLOCK-1")
    inv = f.call("dobj", TXN="GetObjectInventory", domainId="eagames", subdomainId="bf2142",
                 partitionKey="online_content", **{"objectIds.[]": 1, "objectIds.0": "bf2142_bp1"})
    check(ent.get("TXN") == "GetEntitlementByBundle" and inv.get("TXN") == "GetObjectInventory", "subs/dobj")
    want = "1" if config.load().northern_strike else "0"
    check(inv.get("entitlements.[]") == want and (want == "0" or inv.get("entitlements.0.objectId") == "bf2142_bp1"),
          f"Northern Strike (bf2142_bp1): entitlements.[]={inv.get('entitlements.[]')}, ждём {want}")

    print("GPCM:")
    g = socket.create_connection((HOST, 29900), timeout=10)
    first = dict(gp_decode(g.recv(4096).decode().replace("\\final\\", "")))
    cc = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    resp = login_hash(pre["challenge"], pre["ticket"], cc, first["challenge"])
    g.sendall(gp_encode([("login", ""), ("challenge", cc), ("authtoken", pre["ticket"]), ("partnerid", "0"),
                         ("response", resp), ("firewall", "1"), ("port", "0"), ("productid", "10493"),
                         ("gamename", "stella"), ("namespaceid", "0"), ("sdkrevision", "3"), ("quiet", "0"), ("id", "1")]))
    reply = dict(gp_decode(g.recv(4096).decode().replace("\\final\\", "")))
    check(reply.get("lc") == "2" and reply.get("profileid") == str(pid), f"вход по тикету, profileid {reply.get('profileid')}")
    expected_proof = login_hash(pre["challenge"], pre["ticket"], first["challenge"], cc)
    check(reply.get("proof") == expected_proof, "proof корректен")
    g.close()

    print("Статистика (HTTP):")
    tok = eacrypt.encode(pid)
    info = http("getbackendinfo.aspx", auth=tok)
    check("rankSettings.setRank 40 57700" in info and "awards.setData" in info and info.rstrip().endswith("$"), "getbackendinfo")
    pinfo = http("getplayerinfo.aspx", auth=tok, mode="base")
    check(f"\t{soldier_name}\t" in pinfo and "UnlockID" in pinfo, "getplayerinfo mode=base")
    srv = http("getplayerinfo.aspx", auth=eacrypt.encode(1, is_server=True), pid=pid, mode="base")
    check("\tserver" in srv, "getplayerinfo от игрового сервера (pid в параметре)")
    for mode in ("ply", "wrk", "titan", "com", "wep", "veh", "ovr"):
        check(http("getplayerinfo.aspx", auth=tok, mode=mode).startswith("O\nH\tpid\tnick\ttid\tasof"), f"getplayerinfo mode={mode}")
    unl = http("getunlocksinfo.aspx", auth=tok)
    cfg = config.load()
    if cfg.unlock_mode == "progression":
        start = progression.earned_credits(cfg, 0)
        check(f"H\tAvcred\nD\t{start}" in unl, f"новый солдат: {start} стартовых очков")
        check(http("selectunlock.aspx", auth=tok, uid="113").startswith("E\t104"), "нельзя перескочить уровень")
        order = ["111", "112", "113", "114", "115", "121", "122", "123", "124", "125"]
        bought = order[:start]
        for uid in bought:
            check("OK" in http("selectunlock.aspx", auth=tok, uid=uid), f"покупка {uid}")
        check(http("selectunlock.aspx", auth=tok, uid=order[start]).startswith("E\t104"), "без очков анлок отклонён")
        Database(cfg.db_path).set_stats(pid, {"rnk": 3, "crpt": 120})
        left = progression.earned_credits(cfg, 3) - len(bought)
        after = http("getunlocksinfo.aspx", auth=tok)
        check(f"H\tAvcred\nD\t{left}" in after and f"D\t{bought[-1]}" in after, f"звание 3: осталось {left} очков")

        print("Итоги раунда (как их шлёт python/bf2/stats/selfhost.py):")
        end = int(time.time())
        body = (f"v=1\nmap=minsk\ngm=gpm_cq\nwin=1\nai=0\nstart={end - 900}\nend={end}\n"
                f"P\tpid={pid}\tnick={soldier_name}\tt=1\tc=1\tgsco=150\tcrpt=500\tklls=12\tdths=4\ttt=900"
                "\tklstrk=5\twkls-3=10\twdths-3=2\twbf-3=400\twbh-3=100\tktt-1=900\trnk=3\n"
                "P\tpid=1\tnick=bot\tt=2\tgsco=10\tcrpt=10\ttt=900\n").encode()
        status, _ = game_server("POST", "/selfhost/snapshot", body, sign=False)
        check(status == 403, f"итоги без подписи отклонены ({status})")
        status, _ = game_server("POST", "/selfhost/snapshot", body, secret="wrong")
        check(status == 403, f"итоги с чужим секретом отклонены ({status})")
        status, reply = game_server("POST", "/selfhost/snapshot", body)
        check(status == 200 and reply == "OK", f"подписанные итоги приняты ({status} {reply})")
        status, reply = game_server("POST", "/selfhost/snapshot", body)
        check(reply == "DUPLICATE", f"повтор тех же итогов отклонён ({status} {reply})")
        stats = Database(cfg.db_path).stats(pid)
        text = http("getawardsinfo.aspx", auth=tok)
        got = [line.split("\t")[1] for line in text.split("H\taward")[-1].splitlines() if line.startswith("D\t")]
        # первое место среди игроков с профилями (Gold Star) и серия из 5 убийств (Combat Efficiency Pin)
        want = ["202", "400"] if cfg.awards else []
        check(sorted(got) == sorted(want), f"награды за раунд: {got}, ждём {want}")
        award_xp = sum(awards.xp_for(cfg, a) for a in got)
        xp = 120 + round(500 * (1 + cfg.win_bonus) * cfg.first_win_multiplier) + award_xp  # победа, первая за сутки
        rank = progression.rank_for_points(xp)
        check(stats.get("crpt") == xp and stats.get("rnk") == rank and stats.get("rnkcg") == 1,
              f"опыт 120 + 500×бонусы + {award_xp} за награды = {xp} -> звание {rank}, уведомление о повышении "
              f"(crpt={stats.get('crpt')}, rnk={stats.get('rnk')})")
        check(stats.get("win") == 1 and stats.get("kdr") == 3 and stats.get("waccu-3") == 0.25, "победа, K/D 3, точность оружия 25%")
        left = progression.earned_credits(cfg, rank) - len(bought)
        check(f"H\tAvcred\nD\t{left}" in http("getunlocksinfo.aspx", auth=tok), f"звание {rank}: {left} свободных очков")
        prog = http("getplayerprogress.aspx", auth=tok, mode="point")
        check(f"\nD\t{end}\t{150 + xp}\t150\t{xp}\t0\n" in prog, "график прогресса (getplayerprogress)")
        check(http("clearranknotification.aspx", auth=tok).startswith("O\nH\tresult"), "clearranknotification")
        check(Database(cfg.db_path).stats(pid).get("rnkcg") == 0, "уведомление о звании сброшено")
    else:
        check("D\t115" in unl and "D\t516" in unl, "режим all: все анлоки")
    check("Ok" in http("ValidatePlayer.aspx", auth=tok, pid=pid, SoldierNick=soldier_name), "ValidatePlayer")
    check(soldier_name in http("playersearch.aspx", auth=tok, nick=soldier_name[:4]), "playersearch")
    check("globalscore" in http("getleaderboard.aspx", auth=tok, type="combatscore", pos=1, after=17), "getleaderboard")

    print("Администрирование (запросы игрового сервера):")
    status, info = game_server("GET", "/selfhost/serverinfo")
    check(status == 200 and "admins=" in info and "idle_kick=" in info, "serverinfo: админы, баны, кик за бездействие")
    status, reply = game_server("POST", "/selfhost/ban", f"pid={pid}&minutes=5&reason=selftest&by=selftest".encode())
    check(reply == "OK", f"бан из игры ({status} {reply})")
    banned = game_server("GET", "/selfhost/serverinfo")[1].split("banned=")[1].split("\n")[0].split()
    check(str(pid) in banned, "забаненный солдат в списке для кика")
    _, r = fresh_login(user)
    check(r.get("errorCode") == "103", f"забаненный аккаунт не может войти (errorCode {r.get('errorCode')})")
    r = f.call("acct", TXN="GameSpyPreAuth")
    check(r.get("errorCode") == "103", "уже вошедший забаненный не получает тикет на сервер")
    status, reply = game_server("POST", "/selfhost/unban", f"nick={soldier_name}&by=selftest".encode())
    check(reply == "OK", f"разбан из игры ({status} {reply})")
    _, r = fresh_login(user)
    check(r.get("TXN") == "Login" and "errorCode" not in r, "после разбана вход работает")

    print("Доступность (UDP 27900):")
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    u.settimeout(5)
    u.sendto(b"\x09\x00\x00\x00\x00stella\x00", (HOST, 27900))
    check(u.recvfrom(64)[0].startswith(b"\xfe\xfd\x09"), "ответ доступности")

    print("Мастер-сервер (QR2 + список серверов):")
    name = "Selftest " + secrets.token_hex(3)
    ikey = secrets.token_bytes(4)
    info = {"hostname": name, "gamename": "stella", "gamever": "1.10.112.0", "hostport": "17567",
            "mapname": "minsk", "gametype": "gpm_cq", "numplayers": "3", "maxplayers": "64"}
    hb = b"\x03" + ikey + b"".join(k.encode() + b"\0" + v.encode() + b"\0" for k, v in info.items()) + b"\0"
    u.sendto(hb, (HOST, 27900))
    chal = u.recvfrom(256)[0]
    check(chal[:3] == b"\xfe\xfd\x01" and chal[3:7] == ikey, "heartbeat -> challenge")
    u.sendto(b"\x01" + ikey + b"0123456789abcdef\0", (HOST, 27900))
    check(u.recvfrom(64)[0] == b"\xfe\xfd\x0a" + ikey, "ответ на challenge -> сервер зарегистрирован")
    servers = server_list(["hostname", "numplayers", "maxplayers", "mapname", "hostport"])
    mine = [s for s in servers if s.get("hostname") == name]
    check(len(mine) == 1 and mine[0]["mapname"] == "minsk" and mine[0]["port"] == u.getsockname()[1],
          f"сервер в списке ({len(servers)} всего): {mine[0] if mine else '-'}")

    db = Database(config.load().db_path)
    account = db.account_by_name(user)
    if account:
        db.delete_account(account["id"])
        print(f"\nТестовый аккаунт {user} удалён из базы.")

    print("\nИТОГ:", "всё работает" if failures == 0 else f"ошибок: {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
