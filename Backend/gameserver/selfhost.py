# -*- coding: ascii -*-
# Send end-of-round player stats to the self-hosted BF2142 backend.
#
# Runs inside the BF2142 dedicated server (embedded Python 2.3), so: no f-strings,
# no generator expressions, no sorted()/set(), no try/except/finally in one block.
# The embedded runtime is stripped down: os is a stub, so urllib, httplib and
# traceback do not work. Only socket, string, time, md5 and builtins are used here.
# Installed by Backend\tools\install_server.py into python\bf2\stats\.
#
# Every request to the backend is signed with SECRET from selfhost_config.py:
# ?ts=<unix time>&sig=<HMAC-MD5 of "ts\npath\nbody">, so players cannot post fake rounds.

import host
import bf2
import sys
import socket
import time
import md5
from constants import *

try:
	from selfhost_config import BACKEND_HOST, BACKEND_PORT
except ImportError:
	BACKEND_HOST = "127.0.0.1"
	BACKEND_PORT = 80
try:
	from selfhost_config import SECRET
except ImportError:
	SECRET = ""

BACKEND_PATH = "/selfhost/snapshot"
TIMEOUT = 5.0
# Anti-air, ground defence and parachute stay in: the backend's awards need them.
IGNORED_VEHICLES = [VEHICLE_TYPE_SOLDIER]

LOG_FILE = "selfhost.log"  # in the server folder

_installed = 0
_mapStart = 0


def log(message):
	print "selfhost: " + message
	try:
		f = open(LOG_FILE, "a")
		f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
		f.close()
	except:
		pass


def logException(message):
	# traceback is unusable here (needs a real os module), so walk the frames by hand.
	etype, value, tb = sys.exc_info()
	where = []
	while tb is not None:
		where.append("%s:%d" % (tb.tb_frame.f_code.co_filename, tb.tb_lineno))
		tb = tb.tb_next
	log("%s: %s %s at %s" % (message, etype, value, " <- ".join(where)))


_SAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"


def quote(text):
	out = []
	for ch in str(text):
		if ch in _SAFE:
			out.append(ch)
		else:
			out.append("%%%02X" % ord(ch))
	return "".join(out)


def hmacMd5(key, message):
	# hmac.py lives in pylib, which stripped installs may lack; HMAC is short enough to inline.
	if len(key) > 64:
		key = md5.new(key).digest()
	key = key + "\0" * (64 - len(key))
	inner = []
	outer = []
	for ch in key:
		inner.append(chr(ord(ch) ^ 0x36))
		outer.append(chr(ord(ch) ^ 0x5C))
	digest = md5.new("".join(inner) + message).digest()
	return md5.new("".join(outer) + digest).hexdigest()


def signedPath(path, body):
	ts = int(time.time())
	return "%s?ts=%d&sig=%s" % (path, ts, hmacMd5(SECRET, "%d\n%s\n%s" % (ts, path, body)))


def httpRequest(method, path, body="", timeout=TIMEOUT):
	"""Minimal signed HTTP/1.0 request over a raw socket; returns (status line, body).
	It blocks the server loop, so callers keep the timeout short."""
	s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	s.settimeout(timeout)
	chunks = []
	try:
		s.connect((BACKEND_HOST, BACKEND_PORT))
		s.sendall("%s %s HTTP/1.0\r\nHost: %s\r\nContent-Type: text/plain\r\n"
			"Content-Length: %d\r\nConnection: close\r\n\r\n%s"
			% (method, signedPath(path, body), BACKEND_HOST, len(body), body))
		while 1:
			data = s.recv(4096)
			if not data:
				break
			chunks.append(data)
	finally:
		s.close()
	response = "".join(chunks)
	status = response.split("\r\n", 1)[0]
	pos = response.find("\r\n\r\n")
	if pos < 0:
		return status, ""
	return status, response[pos + 4:]


def httpPost(path, body):
	return httpRequest("POST", path, body)


def init():
	global _installed
	if _installed:
		return
	_installed = 1

	# stats.py calls bf2.stats.endofround.invoke() after finalizing every player and
	# before clearing the stats map - the right moment to read the round results.
	import bf2.stats.endofround
	original = bf2.stats.endofround.invoke

	def invoke():
		try:
			send()
		except:
			logException("failed to send round stats")
		original()

	bf2.stats.endofround.invoke = invoke
	host.registerGameStatusHandler(onGameStatusChanged)
	patchEndOfRoundData()
	if not SECRET:
		log("WARNING: selfhost_config.py has no SECRET, the backend will reject round stats; "
			"run Backend\\tools\\install_server.py again")
	try:
		import selfhost_admin
		selfhost_admin.init()
	except:
		logException("admin module failed to load")

	# In co-op/AI games bf2/__init__.py skips the rank module; load it here so the
	# player's rank still comes from the backend.
	if bf2.gameLogic.isAIGame():
		try:
			import bf2.stats.rank
			bf2.stats.rank.init()
		except ImportError:
			pass
	log("stats module ready, backend %s:%d" % (BACKEND_HOST, BACKEND_PORT))


def patchEndOfRoundData():
	# endofround.py sends the end-of-round summary to clients and adds the "r"
	# (ranked) key only on ranked servers. Clients seem to refresh the player's
	# stats after a ranked round, so mark our rounds as ranked in that summary.
	try:
		original = host.gl_sendEndOfRoundData

		def sendEndOfRoundData(data):
			if data.find("\\r\\") < 0:
				data = data + "\\r\\1"
			log("end-of-round summary sent to clients: " + data[:400])
			original(data)

		host.gl_sendEndOfRoundData = sendEndOfRoundData
		log("end-of-round summary will be flagged as ranked")
	except:
		logException("could not hook gl_sendEndOfRoundData")


def onGameStatusChanged(status):
	global _mapStart
	if status == bf2.GameStatus.Playing:
		_mapStart = int(time.time())
		log("round started: %s %s" % (bf2.gameLogic.getMapName(), bf2.serverSettings.getGameMode()))


def g(obj, name, default=0):
	try:
		value = getattr(obj, name)
	except:
		return default
	if value is None:
		return default
	return value


def playerPairs(sp):
	ls = sp.localScore
	away = int(g(ls, 'awayBonusScoreIAR') + g(ls, 'awayBonusScore'))
	experience = int(g(ls, 'experienceScoreIAR') + g(ls, 'experienceScore'))
	careerPoints = (sp.score - g(ls, 'diffRankScore')) + experience + away
	timePlayed = int(sp.timePlayed)
	timeAsCmd = int(sp.timeAsCmd)
	timeAsSql = int(sp.timeAsSql)
	timeInSquad = int(sp.timeInSquad)

	pairs = [
		("pid", sp.profileId), ("nick", sp.name), ("t", sp.team), ("c", sp.complete),
		("gsco", sp.score), ("crpt", careerPoints), ("awaybonus", away),
		("ban", sp.timesBanned), ("kick", sp.timesKicked),
		("capa", g(ls, 'cpAssists')), ("cpt", g(ls, 'cpCaptures')), ("dcpt", g(ls, 'cpDefends')),
		("ncpt", g(ls, 'cpNeutralizes')), ("cs", g(ls, 'commanderBonusScore')),
		("dass", g(ls, 'driverAssists')), ("klla", g(ls, 'damageAssists')),
		("klls", sp.kills), ("dths", sp.deaths), ("tkls", sp.teamkills), ("suic", g(ls, 'suicides')),
		("klstrk", sp.longestKillStreak), ("dstrk", sp.longestDeathStreak),
		("kluav", sp.weapons[WEAPON_TYPE_RECON_DRONE].kills),
		("hls", g(ls, 'heals')), ("rps", g(ls, 'repairs')), ("rvs", g(ls, 'revives')), ("resp", g(ls, 'ammos')),
		("pdt", len(sp.dogTags)), ("pdtc", sp.dogtagCount),
		("slbspn", sp.squadLeaderBeaconSpawns), ("sluav", sp.squadLeaderUAV),
		("tac", timeAsCmd), ("tasl", timeAsSql), ("tasm", timeInSquad - timeAsSql),
		("talw", timePlayed - timeAsCmd - timeInSquad), ("tt", timePlayed),
		("tas", g(ls, 'titanAttackKills')), ("tds", g(ls, 'titanDefendKills')),
		("tcd", g(ls, 'titanPartsDestroyed')), ("tcrd", g(ls, 'titanCoreDestroyed')),
		("tdrps", g(ls, 'titanAirDrops')), ("tgd", g(ls, 'titanWeaponsDestroyed')),
		("tgr", g(ls, 'titanWeaponsRepaired')),
		("tdmg", g(ls, 'teamDamages')), ("tvdmg", g(ls, 'teamVehicleDamages')),
		("toth", sp.bulletsHit), ("tots", sp.bulletsFired), ("twsc", sp.teamScore),
		("rnk", sp.rank), ("rnkcg", sp.roundRankup),
	]

	for k in range(0, NUM_KIT_TYPES):
		kit = sp.kits[k]
		pairs.append(("kkls-%d" % k, kit.kills))
		pairs.append(("kdths-%d" % k, kit.deaths))
		pairs.append(("ktt-%d" % k, int(kit.timeInObject)))

	for v in range(0, NUM_VEHICLE_TYPES):
		if v in IGNORED_VEHICLES:
			continue
		veh = sp.vehicles[v]
		if veh.timeInObject > 0:
			pairs.append(("vtp-%d" % v, int(veh.timeInObject)))
			pairs.append(("vkls-%d" % v, veh.kills))
			pairs.append(("vdths-%d" % v, veh.killedBy))
			pairs.append(("vrkls-%d" % v, veh.roadKills))
			pairs.append(("vdstry-%d" % v, veh.destroyed))
			pairs.append(("vbf-%d" % v, veh.bulletsFired))
			pairs.append(("vbh-%d" % v, veh.bulletsHit))

	for w in range(0, NUM_WEAPON_TYPES):
		wep = sp.weapons[w]
		if wep.timeInObject > 0 or wep.kills > 0:
			pairs.append(("wtp-%d" % w, int(wep.timeInObject)))
			pairs.append(("wkls-%d" % w, wep.kills))
			pairs.append(("wdths-%d" % w, wep.killedBy))
			pairs.append(("wbf-%d" % w, wep.bulletsFired))
			pairs.append(("wbh-%d" % w, wep.bulletsHit))
			if wep.headShots > 0:
				pairs.append(("whs-%d" % w, wep.headShots))
	return pairs


def send():
	statsMap = bf2.stats.stats.getStatsMap()
	mapName = bf2.gameLogic.getMapName()
	gameMode = bf2.serverSettings.getGameMode()
	armies = bf2.stats.stats.roundArmies
	lines = [
		"v=1",
		"map=" + quote(mapName),
		"gm=" + quote(gameMode),
		"mapid=%d" % getMapId(mapName),
		"gmid=%d" % getGameModeId(gameMode),
		"army1=%s" % armies[1],
		"army2=%s" % armies[2],
		"win=%d" % bf2.gameLogic.getWinner(),
		"ai=%d" % int(bf2.gameLogic.isAIGame()),
		"start=%d" % _mapStart,
		"end=%d" % int(time.time()),
	]
	count = 0
	for sp in statsMap.values():
		if sp.profileId <= 2000:
			continue  # bots and players without a backend profile
		items = []
		for key, value in playerPairs(sp):
			items.append("%s=%s" % (key, quote(value)))
		lines.append("P\t" + "\t".join(items))
		count = count + 1
	if count == 0:
		log("round ended: no players with profiles, nothing to send")
		return

	status, reply = httpPost(BACKEND_PATH, "\n".join(lines) + "\n")
	if status.find(" 200 ") < 0 or reply.strip() != "OK":
		log("round stats NOT accepted for %d players: %s / %s" % (count, status, reply.strip()[:120]))
	else:
		log("round stats sent for %d players: %s / %s" % (count, status, reply.strip()[:80]))
