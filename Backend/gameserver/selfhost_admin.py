# -*- coding: ascii -*-
# In-game administration for the self-hosted BF2142 server:
#  - chat commands for admins: !kick, !ban, !unban, !help;
#  - kicks players whose account is banned on the backend;
#  - kicks idle players (the commander and admins are exempt).
# Admins, bans and the idle limit come from the backend (config.toml [admin]), refreshed
# every few minutes. Same Python 2.3 restrictions as selfhost.py; loaded by selfhost.init().
# Messages are in English: chat fonts of non-Russian clients have no Cyrillic.

import host
import bf2
import time
import selfhost

TICK = 5            # seconds between checks
REFRESH = 120       # seconds between backend refreshes
WARN_BEFORE = 60    # warn idle players this many seconds before the kick
PREFIX = "[Admin] "
HELP = "Commands: !kick <name> [reason] | !ban <name> [30m|12h|7d|perm] [reason] | !unban <soldier>"
UNITS = {"m": 1, "h": 60, "d": 1440, "w": 10080}

_admins = {}        # pid -> 1
_banned = {}        # pid -> 1
_idleKick = 0       # seconds, 0 = off
_lastRefresh = 0
_playing = 0
_timer = None
_activity = {}      # player index -> [signature, idle since, warned]
_pendingKicks = []  # [time, player index, pid, message]
_positionBroken = 0


def init():
	global _timer
	host.registerGameStatusHandler(onGameStatusChanged)
	host.registerHandler('PlayerConnect', onPlayerConnect, 1)
	host.registerHandler('PlayerDisconnect', onPlayerDisconnect, 1)
	host.registerHandler('ChatMessage', onChatMessage, 1)
	_timer = bf2.Timer(onTick, TICK, 1)
	_timer.setRecurring(TICK)
	refresh()
	selfhost.log("admin module ready: %d admins, %d banned, idle kick %ds" % (len(_admins), len(_banned), _idleKick))


# --- messages and kicks --------------------------------------------------------

def announce(message):
	# The same call DICE's playerconnect.py uses for its public ban message.
	host.sgl_sendTextMessage(0, 12, 1, PREFIX + message, 0)


def tell(player, message):
	bf2.gameLogic.sendServerMessage(player.index, message)


def kick(player, message):
	if message:
		announce(message)
	selfhost.log("kick %s (pid %d): %s" % (player.getName(), player.getProfileId(), message))
	host.rcon_invoke("admin.kickPlayer %d" % player.index)
	if player.index in _activity:
		del _activity[player.index]


def humans():
	result = []
	for p in bf2.playerManager.getPlayers():
		if not p.isAIPlayer():
			result.append(p)
	return result


# --- backend -------------------------------------------------------------------

def refresh():
	global _admins, _banned, _idleKick, _lastRefresh
	_lastRefresh = time.time()
	try:
		status, reply = selfhost.httpRequest("GET", "/selfhost/serverinfo", "", 2.0)
	except:
		selfhost.logException("admin: backend unavailable")
		return
	if status.find(" 200 ") < 0:
		selfhost.log("admin: backend refused serverinfo: %s / %s" % (status, reply.strip()[:120]))
		return
	admins = {}
	banned = {}
	idle = _idleKick
	for line in reply.split("\n"):
		if line.find("=") < 0:
			continue
		key, value = line.split("=", 1)
		if key == "admins":
			for pid in value.split():
				admins[int(pid)] = 1
		elif key == "banned":
			for pid in value.split():
				banned[int(pid)] = 1
		elif key == "idle_kick":
			idle = int(value)
	_admins, _banned, _idleKick = admins, banned, idle
	for p in humans():
		if p.getProfileId() in _banned:
			kick(p, "%s is banned" % p.getName())


def post(path, fields):
	items = []
	for key, value in fields:
		items.append("%s=%s" % (key, selfhost.quote(value)))
	try:
		status, reply = selfhost.httpRequest("POST", path, "&".join(items), 3.0)
	except:
		selfhost.logException("admin: %s failed" % path)
		return "backend unavailable"
	if status.find(" 200 ") < 0:
		return "%s %s" % (status, reply.strip()[:60])
	return reply.strip()


# --- events --------------------------------------------------------------------

def onGameStatusChanged(status):
	global _playing, _activity
	_playing = status == bf2.GameStatus.Playing
	_activity = {}


def onPlayerConnect(player):
	try:
		if player.index in _activity:
			del _activity[player.index]
		if player.getProfileId() in _banned:
			# kicking inside the connect event is unsafe, do it on the next ticks
			_pendingKicks.append([time.time() + 3, player.index, player.getProfileId(),
				"%s is banned" % player.getName()])
	except:
		selfhost.logException("admin: onPlayerConnect")


def onPlayerDisconnect(player):
	if player.index in _activity:
		del _activity[player.index]


def onTick(data):
	global _pendingKicks
	try:
		now = time.time()
		later = []
		for item in _pendingKicks:
			if item[0] > now:
				later.append(item)
				continue
			p = bf2.playerManager.getPlayerByIndex(item[1])
			if p is not None and p.isValid() and p.getProfileId() == item[2]:
				kick(p, item[3])
		_pendingKicks = later
		if now - _lastRefresh >= REFRESH:
			refresh()
		if _playing and _idleKick > 0:
			checkIdle(now)
	except:
		selfhost.logException("admin: tick")


# --- idle kick -----------------------------------------------------------------

def activity(player):
	"""Anything that changes while a player actually plays: alive/dead, score,
	position and view direction of the soldier and of the vehicle he is in."""
	global _positionBroken
	sig = [player.isAlive(), player.score.score, player.score.kills, player.score.deaths]
	if player.isAlive() and not _positionBroken:
		try:
			for obj in (player.getVehicle(), player.getDefaultVehicle()):
				if obj is None:
					continue
				for v in obj.getPosition():
					sig.append(int(v * 2))
				for v in obj.getRotation():
					sig.append(int(v))
		except:
			_positionBroken = 1
			selfhost.logException("admin: positions unavailable, idle check uses score only")
	return sig


def checkIdle(now):
	for p in humans():
		if p.getProfileId() in _admins or p.isCommander():
			if p.index in _activity:
				del _activity[p.index]
			continue
		sig = activity(p)
		rec = _activity.get(p.index)
		if rec is None or rec[0] != sig:
			_activity[p.index] = [sig, now, 0]
			continue
		idle = now - rec[1]
		if idle >= _idleKick:
			kick(p, "%s was kicked for inactivity (%d min)" % (p.getName(), _idleKick // 60))
		elif idle >= _idleKick - WARN_BEFORE and not rec[2]:
			rec[2] = 1
			tell(p, "You are idle and will be kicked in %d seconds. Move!" % int(_idleKick - idle))


# --- chat commands -------------------------------------------------------------

def findPlayers(part):
	part = part.lower()
	exact = []
	partial = []
	for p in humans():
		name = p.getName().lower()
		if name == part or name.split(" ")[-1] == part:
			exact.append(p)
		elif name.find(part) >= 0:
			partial.append(p)
	if exact:
		return exact
	return partial


def findOne(admin, part):
	found = findPlayers(part)
	if not found:
		tell(admin, "No player matches '%s'" % part)
		return None
	if len(found) > 1:
		names = []
		for p in found:
			names.append(p.getName())
		tell(admin, "'%s' matches several players: %s" % (part, ", ".join(names)))
		return None
	if found[0].getProfileId() in _admins:
		tell(admin, "%s is an admin" % found[0].getName())
		return None
	return found[0]


def parseDuration(text):
	"""'30m', '12h', '7d', '2w', '90' (minutes) -> minutes; 'perm' -> 0 (forever); else -1."""
	text = text.lower()
	if text in ("perm", "forever"):
		return 0
	unit = "m"
	if text and text[-1] in UNITS.keys():
		unit = text[-1]
		text = text[:-1]
	if not text.isdigit() or int(text) <= 0:
		return -1
	return int(text) * UNITS[unit]


def durationText(minutes):
	if minutes == 0:
		return "permanently"
	for unit, name in (("d", "day"), ("h", "hour")):
		if minutes % UNITS[unit] == 0:
			n = minutes // UNITS[unit]
			if n == 1:
				return "for 1 %s" % name
			return "for %d %ss" % (n, name)
	return "for %d min" % minutes


def onChatMessage(playerId, text, channel, flags):
	try:
		handleChat(playerId, text)
	except:
		selfhost.logException("admin: chat command")


def handleChat(playerId, text):
	if playerId < 0:
		return
	pos = text.find("!")  # team/squad/dead prefixes come before the message
	if pos < 0:
		return
	words = text[pos + 1:].split()
	if not words or words[0].lower() not in ("kick", "ban", "unban", "help"):
		return
	admin = bf2.playerManager.getPlayerByIndex(playerId)
	if admin is None:
		return
	cmd = words[0].lower()
	if admin.getProfileId() not in _admins:
		tell(admin, "Only server admins can use !%s" % cmd)
		return
	selfhost.log("admin %s: %s" % (admin.getName(), " ".join(words)))
	if cmd == "help" or len(words) < 2:
		tell(admin, HELP)
	elif cmd == "kick":
		target = findOne(admin, words[1])
		if target is not None:
			message = "%s was kicked by %s" % (target.getName(), admin.getName())
			if len(words) > 2:
				message = message + ": " + " ".join(words[2:])
			kick(target, message)
	elif cmd == "ban":
		target = findOne(admin, words[1])
		if target is None:
			return
		minutes = 0
		reason = words[2:]
		if reason:
			minutes = parseDuration(reason[0])
			if minutes < 0:
				minutes = 0
			else:
				reason = reason[1:]
		fields = [("pid", target.getProfileId()), ("reason", " ".join(reason)), ("by", admin.getName())]
		if minutes:
			fields.append(("minutes", minutes))
		result = post("/selfhost/ban", fields)
		message = "%s was banned %s by %s" % (target.getName(), durationText(minutes), admin.getName())
		if reason:
			message = message + ": " + " ".join(reason)
		if result != "OK":
			tell(admin, "Ban was not saved (%s), kicking only" % result)
			message = "%s was kicked by %s" % (target.getName(), admin.getName())
		else:
			_banned[target.getProfileId()] = 1
		kick(target, message)
	elif cmd == "unban":
		result = post("/selfhost/unban", [("nick", words[1]), ("by", admin.getName())])
		if result == "OK":
			tell(admin, "%s is unbanned" % words[1])
			refresh()
		elif result == "NOTFOUND":
			tell(admin, "No soldier named '%s'" % words[1])
		elif result == "NOTBANNED":
			tell(admin, "%s is not banned" % words[1])
		else:
			tell(admin, "Unban failed: %s" % result)
