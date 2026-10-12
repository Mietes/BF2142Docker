"""Тест модуля администрирования игрового сервера (gameserver/selfhost_admin.py) на заглушках
движка: команды в чате, кик забаненных, кик за бездействие. Модуль написан для Python 2.3,
но без синтаксиса, которого нет в Python 3, поэтому его можно проверить здесь.

    .venv\\Scripts\\python.exe tools\\test_server_admin.py
"""

import importlib.util
import sys
import types
from pathlib import Path
from urllib.parse import parse_qsl, quote

ROOT = Path(__file__).resolve().parent.parent
failures = 0


def check(cond, what):
    global failures
    print(("  OK   " if cond else "  FAIL ") + what)
    failures += not cond


class Clock:
    now = 1_000_000.0

    def time(self):
        return self.now


class Obj:
    def __init__(self):
        self.pos, self.rot = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]

    def getPosition(self):
        return tuple(self.pos)

    def getRotation(self):
        return tuple(self.rot)


class Score:
    score = kills = deaths = 0


class Player:
    def __init__(self, index, name, pid, ai=False):
        self.index, self.name, self.pid, self.ai = index, name, pid, ai
        self.alive, self.commander, self.score, self.obj = True, False, Score(), Obj()

    def getName(self): return self.name
    def getProfileId(self): return self.pid
    def isAIPlayer(self): return self.ai
    def isAlive(self): return self.alive
    def isCommander(self): return self.commander
    def isValid(self): return True
    def getVehicle(self): return self.obj
    def getDefaultVehicle(self): return self.obj


class World:
    def __init__(self):
        self.players, self.handlers, self.public, self.private, self.kicked = [], {}, [], [], []
        self.backend = {"admins": [1], "banned": [], "idle": 300}
        self.bans, self.unbans, self.logs = [], [], []

    # host
    def registerHandler(self, name, fn, always):
        self.handlers[name] = fn

    def registerGameStatusHandler(self, fn):
        self.handlers["status"] = fn

    def sgl_sendTextMessage(self, pid, channel, kind, text, flags):
        self.public.append(text)

    def rcon_invoke(self, cmd):
        index = int(cmd.split()[-1])
        self.kicked.append(index)
        self.players = [p for p in self.players if p.index != index]

    # bf2.gameLogic / playerManager
    def sendServerMessage(self, index, text):
        self.private.append((index, text))

    def getPlayers(self):
        return list(self.players)

    def getPlayerByIndex(self, index):
        return next((p for p in self.players if p.index == index), None)

    # selfhost
    def httpRequest(self, method, path, body="", timeout=0):
        if path == "/selfhost/serverinfo":
            b = self.backend
            return "HTTP/1.0 200 OK", (f"admins={' '.join(map(str, b['admins']))}\n"
                                       f"banned={' '.join(map(str, b['banned']))}\nidle_kick={b['idle']}\n")
        fields = dict(parse_qsl(body))
        if path == "/selfhost/ban":
            self.bans.append(fields)
            return "HTTP/1.0 200 OK", "OK"
        if path == "/selfhost/unban":
            self.unbans.append(fields)
            return "HTTP/1.0 200 OK", "OK" if fields["nick"] == "Bob" else "NOTFOUND"
        return "HTTP/1.0 404 Not found", ""

    def logException(self, message):
        raise


def load(world, clock):
    host = types.SimpleNamespace(registerHandler=world.registerHandler,
                                 registerGameStatusHandler=world.registerGameStatusHandler,
                                 sgl_sendTextMessage=world.sgl_sendTextMessage, rcon_invoke=world.rcon_invoke)

    class Timer:
        def __init__(self, fn, delta, always):
            world.tick = fn

        def setRecurring(self, interval):
            pass

    bf2 = types.SimpleNamespace(Timer=Timer, GameStatus=types.SimpleNamespace(Playing=1, EndGame=3),
                                playerManager=world, gameLogic=world)
    selfhost = types.SimpleNamespace(httpRequest=world.httpRequest, log=world.logs.append,
                                     logException=world.logException, quote=lambda v: quote(str(v), safe=""))
    sys.modules.update(host=host, bf2=bf2, selfhost=selfhost)
    spec = importlib.util.spec_from_file_location("selfhost_admin", ROOT / "gameserver" / "selfhost_admin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.time = clock
    module.init()
    return module


def main():
    world, clock = World(), Clock()
    boss, bob, bobby, joe, bot = (Player(0, "Boss", 1), Player(1, "Bob", 2), Player(2, "Bobby", 3),
                                  Player(3, "Joe", 4), Player(4, "Bot", 0, ai=True))
    world.players = [boss, bob, bobby, joe, bot]
    m = load(world, clock)
    chat = world.handlers["ChatMessage"]
    world.handlers["status"](1)  # раунд идёт

    def last_private():
        return world.private[-1][1] if world.private else ""

    print("Команды в чате:")
    chat(3, "!kick Bob", 0, 0)
    check(world.kicked == [] and "Only server admins" in last_private(), "не-админу команды недоступны")
    chat(0, "HUD_TEXT_CHAT_TEAM!help", 0, 0)
    check(last_private().startswith("Commands:"), "!help из командного чата")
    chat(0, "!kick bo", 0, 0)
    check(world.kicked == [] and "several players" in last_private(), "неоднозначное имя — ничего не делать")
    chat(0, "!kick boss", 0, 0)
    check(world.kicked == [] and "is an admin" in last_private(), "админа кикнуть нельзя")
    chat(0, "!kick Bobby spawn camping", 0, 0)
    check(world.kicked == [2] and world.public[-1] == "[Admin] Bobby was kicked by Boss: spawn camping",
          "!kick с причиной")
    chat(0, "!ban bob 7d wallhack", 0, 0)
    check(world.bans == [{"pid": "2", "reason": "wallhack", "by": "Boss", "minutes": "10080"}],
          f"!ban на 7 дней ушёл в бэкенд: {world.bans}")
    check(world.kicked[-1] == 1 and world.public[-1] == "[Admin] Bob was banned for 7 days by Boss: wallhack",
          "забаненный кикнут, объявление в чате")
    chat(0, "!ban Joe aimbot", 0, 0)
    check(world.bans[-1] == {"pid": "4", "reason": "aimbot", "by": "Boss"} and "permanently" in world.public[-1],
          "!ban без срока — навсегда")
    chat(0, "!unban Bob", 0, 0)
    check(world.unbans[-1]["nick"] == "Bob" and last_private() == "Bob is unbanned", "!unban")
    chat(0, "!unban Nobody", 0, 0)
    check(last_private() == "No soldier named 'Nobody'", "!unban неизвестного")

    print("Забаненные:")
    world.backend["banned"] = [7]
    clock.now += m.REFRESH
    world.tick(None)
    late = Player(5, "Cheater", 7)
    world.players.append(late)
    world.handlers["PlayerConnect"](late)
    world.tick(None)
    check(5 not in world.kicked, "при входе не кикает сразу (движку это вредно)")
    clock.now += 5
    world.tick(None)
    check(world.kicked[-1] == 5 and "Cheater is banned" in world.public[-1], "кик забаненного через пару секунд")

    print("Бездействие:")
    afk, mover, cmdr = Player(6, "Afk", 10), Player(7, "Mover", 11), Player(8, "Cmdr", 12)
    cmdr.commander = True
    world.players += [afk, mover, cmdr]
    start = clock.now
    while clock.now - start < 240:
        clock.now += 5
        mover.obj.pos[0] += 3
        world.tick(None)
    check(not any(i == 6 for i, _ in world.private), "до предупреждения тихо")
    clock.now += 10
    world.tick(None)
    check(world.private[-1][0] == 6 and "idle" in world.private[-1][1], "предупреждение за минуту")
    while clock.now - start < 310:
        clock.now += 5
        mover.obj.pos[0] += 3
        world.tick(None)
    check(6 in world.kicked and "[Admin] Afk was kicked for inactivity (5 min)" in world.public, "кик за 5 минут без движения")
    check(7 not in world.kicked and 8 not in world.kicked and 0 not in world.kicked,
          "двигающийся, командир и админ остаются")
    check(4 not in world.kicked, "боты не проверяются (бот стоит на месте и не кикнут)")

    print("\nИТОГ:", "всё работает" if failures == 0 else f"ошибок: {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
