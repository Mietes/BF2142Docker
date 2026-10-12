"""Итоги раунда от игрового сервера (python/bf2/stats/selfhost.py) -> статистика и звания.

Формат: строки "ключ=значение" о раунде, затем по строке на игрока:
"P<TAB>ключ=значение<TAB>..." (значения в URL-кодировке).
"""

import logging
import time
from datetime import datetime, timedelta
from urllib.parse import unquote

from . import awards, progression
from .config import DATA_DIR
from .context import Context

log = logging.getLogger("rounds")

IGNORED_KEYS = {"pid", "nick", "t", "c", "rnk", "rnkcg"}
MAX_KEYS = {"klstrk", "dstrk"}
# Номера карт и режимов, как в python/bf2/stats/constants.py сервера (mapMap, gameModeMap). Сервер
# сам присылает mapid/gmid; таблицы — на случай итогов без них.
MAP_IDS = {
    "suez_canal": 0, "verdun": 1, "shuhia_taiba": 2, "minsk": 3, "camp_gibraltar": 4,
    "sidi_power_plant": 5, "fall_of_berlin": 6, "belgrade": 7, "cerbere_landing": 8, "tunis_harbor": 9,
    "bridge_at_remagen": 10, "liberation_of_leipzig": 11, "port_bavaria": 12, "highway_tampa": 14,
    "operation_blue_pearl": 15, "wake_island_2142": 16, "operation_shingle": 17, "yellow_knife": 18,
    "strike_at_karkand": 19, "molokai": 20,
}
GM_IDS = {"gpm_cq": 0, "gpm_ti": 1, "gpm_sl": 2, "gpm_coop": 3, "gpm_nv": 0, "gpm_ca": 0}
# В статистике режимов три: 0 Conquest, 1 Titan, 2 Assault Lines; кооп (3) идёт как Conquest.
STAT_GM = {0: 0, 1: 1, 2: 2, 3: 0}
_criteria = None
# Итоговые значения, которые сохраняются после каждого раунда — для графиков BFHQ.
HISTORY_KEYS = [
    "gsco", "crpt", "awaybonus", "tt", "klls", "dths", "kpm", "dpm", "spm", "tac", "tasl", "tasm", "talw",
    "cpt", "capa", "dcpt", "ovaccu", "win", "los", "twsc", "hls", "rps", "rvs", "resp", "rnk",
]


def parse(body: bytes) -> tuple[dict, list[dict]]:
    info, players = {}, []
    for line in body.decode("latin-1").splitlines():
        if line.startswith("P\t"):
            player = {}
            for item in line[2:].split("\t"):
                key, _, value = item.partition("=")
                player[key] = unquote(value)
            players.append(player)
        elif "=" in line:
            key, _, value = line.partition("=")
            info[key] = unquote(value)
    return info, players


def _num(value) -> float | int:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 0
    return int(x) if x.is_integer() else x


def _ratio(a, b):
    return round(a / b, 4) if b else 0


def derive(s: dict):
    """Производные показатели, которые нельзя просто сложить."""
    minutes = s.get("tt", 0) / 60
    s["kdr"] = _ratio(s.get("klls", 0), s.get("dths", 0)) if s.get("dths") else s.get("klls", 0)
    s["kpm"] = _ratio(s.get("klls", 0), minutes)
    s["dpm"] = _ratio(s.get("dths", 0), minutes)
    s["spm"] = _ratio(s.get("gsco", 0), minutes)
    s["ovaccu"] = _ratio(s.get("toth", 0), s.get("tots", 0))
    s["wlr"] = _ratio(s.get("win", 0), s.get("los", 0)) if s.get("los") else s.get("win", 0)
    for key in list(s):
        if key.startswith("wbf-"):
            i = key[4:]
            s[f"waccu-{i}"] = _ratio(s.get(f"wbh-{i}", 0), s[key])
        elif key.startswith("wkls-"):
            i = key[5:]
            s[f"wkdr-{i}"] = _ratio(s[key], s.get(f"wdths-{i}", 0)) if s.get(f"wdths-{i}") else s[key]
        elif key.startswith("vbf-"):
            i = key[4:]
            s[f"vaccu-{i}"] = _ratio(s.get(f"vbh-{i}", 0), s[key])
        elif key.startswith("vkls-"):
            i = key[5:]
            s[f"vkdr-{i}"] = _ratio(s[key], s.get(f"vdths-{i}", 0)) if s.get(f"vdths-{i}") else s[key]


def round_setting(info: dict) -> tuple[int | None, int | None, dict]:
    """(режим для статистики 0..2, номер карты, {команда: фракция 0 ЕС / 1 ПАК})."""
    gm = int(_num(info["gmid"])) if "gmid" in info else GM_IDS.get(info.get("gm", "").lower())
    map_id = int(_num(info["mapid"])) if "mapid" in info else MAP_IDS.get(info.get("map", "").lower())
    armies = {t: int(info[f"army{t}"]) for t in (1, 2) if info.get(f"army{t}") in ("0", "1")}
    return STAT_GM.get(gm), (map_id if map_id is not None and 0 <= map_id < 99 else None), armies


def career_extras(g: dict, gm, map_id, army, won: bool, lost: bool) -> tuple[dict, dict]:
    """Показатели за карьеру, которых нет в итогах напрямую: по режимам, картам, фракциям,
    технике и снаряжению (их ждут страницы BFHQ и условия наград). (суммируемые, максимумы)."""
    sums, maxes = {}, {}

    def each(prefix, ids):
        return sum(g.get(f"{prefix}-{i}", 0) for i in ids)
    tt, kills, score = g.get("tt", 0), g.get("klls", 0), g.get("gsco", 0)
    if gm is not None:
        sums.update({f"tgpm-{gm}": tt, f"kgpm-{gm}": kills, f"csgpm-{gm}": g.get("cs", 0),
                     f"ctgpm-{gm}": g.get("tac", 0), f"trpm-{gm}": 1})
        maxes[f"bksgpm-{gm}"] = g.get("klstrk", 0)
        if map_id is not None:
            m = f"{gm}-{map_id}"
            sums.update({f"mtt-{m}": tt, f"mkls-{m}": kills, f"msc-{m}": score,
                         f"mwin-{m}": int(won), f"mlos-{m}": int(lost)})
            maxes[f"mbr-{m}"] = score
    if army is not None:
        sums.update({f"attp-{army}": tt, f"awin-{army}": int(won), f"alos-{army}": int(lost)})
    sums["klse"] = each("wkls", awards.EXPLOSIVES)
    sums["klsk"] = g.get("wkls-12", 0)
    sums["atp"], sums["akl"] = each("vtp", awards.ARMOR), each("vkls", awards.ARMOR)
    sums["htp"], sums["hkl"] = each("vtp", awards.AIR), each("vkls", awards.AIR)
    for i in range(17):  # снаряжение: оружие 32.. (дефибриллятор, ключ, аптечки, ящики...)
        if f"wtp-{32 + i}" in g:
            sums[f"etp-{i}"] = sums[f"etpk-{i}"] = g[f"wtp-{32 + i}"]
    return sums, maxes


def places(players: list[dict]) -> dict[int, int]:
    """pid -> 1..3 по очкам раунда (только у кого очки > 0)."""
    scored = sorted(((_num(p.get("gsco")), -_num(p.get("dths")), int(_num(p.get("pid")))) for p in players
                     if _num(p.get("gsco")) > 0), reverse=True)
    return {pid: i + 1 for i, (_, _, pid) in enumerate(scored[:3])}


def criteria():
    global _criteria
    if _criteria is None:
        _criteria = awards.load()
    return _criteria


def day_id(cfg, timestamp: int) -> int:
    """Номер «игровых суток» (ГГГГММДД), сутки начинаются в day_starts_hour по времени сервера."""
    moment = datetime.fromtimestamp(timestamp) - timedelta(hours=cfg.day_starts_hour)
    return int(moment.strftime("%Y%m%d"))


def xp_multiplier(cfg, current: dict, ai_game: bool, won: bool, ended: int) -> tuple[float, list[str], int | None]:
    """Множитель опыта за раунд, пояснения для журнала и (если была) отметка первой победы за сутки."""
    multiplier, notes, first_win_day = 1.0, [], None
    if ai_game and cfg.coop_multiplier != 1:
        multiplier *= cfg.coop_multiplier
        notes.append(f"кооп ×{cfg.coop_multiplier:g}")
    if won and cfg.win_bonus:
        multiplier *= 1 + cfg.win_bonus
        notes.append(f"победа +{cfg.win_bonus * 100:g}%")
    if won and cfg.first_win_multiplier != 1:
        today = day_id(cfg, ended)
        if int(current.get("fwday", 0)) != today:
            multiplier *= cfg.first_win_multiplier
            notes.append(f"первая победа за сутки ×{cfg.first_win_multiplier:g}")
            first_win_day = today
    return multiplier, notes, first_win_day


def apply_round(ctx: Context, body: bytes, server_ip: str) -> str:
    cfg, db = ctx.cfg, ctx.db
    snap_dir = DATA_DIR / "snapshots"
    snap_dir.mkdir(exist_ok=True)
    (snap_dir / f"{time.strftime('%Y%m%d_%H%M%S')}_{server_ip.replace(':', '_')}.txt").write_bytes(body)
    info, players = parse(body)
    started, ended = int(_num(info.get("start"))), int(_num(info.get("end")))
    if db.round_exists(server_ip, info.get("map", ""), started, ended):
        log.warning("%s: раунд %s (%s–%s) уже засчитан — повтор отклонён", server_ip, info.get("map"), started, ended)
        return "DUPLICATE"
    ai_game = info.get("ai") == "1"
    winner = int(_num(info.get("win")))
    if ai_game and not cfg.count_coop:
        log.info("раунд с ботами (%s) не засчитывается: stats.count_coop = false", info.get("map"))
        return "OK"

    summary = []
    gm, map_id, armies = round_setting(info)
    place_of = places(players)
    with db.transaction():
        round_id = db.add_round(server_ip, info.get("map", ""), info.get("gm", ""), winner, int(ai_game),
                                started, ended)
        for p in players:
            pid = int(_num(p.get("pid")))
            soldier = db.soldier(pid)
            if soldier is None:
                log.warning("в итогах раунда неизвестный pid %s (%s)", pid, p.get("nick"))
                continue
            gained = {k: _num(v) for k, v in p.items() if k not in IGNORED_KEYS}
            if gained.get("tt", 0) < cfg.min_round_seconds:
                summary.append(f"{soldier['name']}: {gained.get('tt', 0)} с в бою (нужно {cfg.min_round_seconds}) — не засчитано")
                continue
            team = int(_num(p.get("t")))
            won = winner in (1, 2) and team == winner
            lost = winner in (1, 2) and team in (1, 2) and not won
            if winner in (1, 2) and team in (1, 2):
                gained["win" if won else "los"] = 1

            current = db.stats(pid)
            raw_xp = gained.get("crpt", 0)
            multiplier, notes, first_win_day = xp_multiplier(cfg, current, ai_game, won, ended)
            if raw_xp > 0:  # штрафной (отрицательный) опыт бонусами не умножаем
                gained["crpt"] = round(raw_xp * multiplier)

            total = dict(current)
            for key, value in gained.items():
                if key in MAX_KEYS:
                    total[key] = max(current.get(key, 0), value)
                else:
                    total[key] = current.get(key, 0) + value
            total["brs"] = max(current.get("brs", 0), gained.get("gsco", 0))
            sums, maxes = career_extras(gained, gm, map_id, armies.get(team), won, lost)
            for key, value in sums.items():
                total[key] = current.get(key, 0) + value
            for key, value in maxes.items():
                total[key] = max(current.get(key, 0), value)
            derive(total)

            earned, award_xp = [], 0
            if cfg.awards:
                r = awards.Round(gained, gm=gm, map_id=map_id, army=armies.get(team), won=won,
                                 place=place_of.get(pid))
                earned = awards.evaluate(criteria(), r, total, db.awards(pid))
                award_xp = sum(awards.xp_for(cfg, a) for a in earned)
                for award in earned:
                    db.add_award(pid, award, ended)
                total["crpt"] = total.get("crpt", 0) + award_xp

            old_rank = int(current.get("rnk", 0))
            rank = max(old_rank, min(progression.rank_for_points(total.get("crpt", 0)), progression.MAX_NORMAL_RANK))
            total["rnk"] = rank
            if rank > old_rank:
                total["rnkcg"] = 1
            total["lgdt"] = ended
            if first_win_day:
                total["fwday"] = first_win_day
            db.set_stats(pid, total)
            db.add_round_player(round_id, pid, {
                "round": gained, "raw_xp": raw_xp, "multiplier": multiplier,
                "awards": earned, "award_xp": award_xp,
                "total": {k: total.get(k, 0) for k in HISTORY_KEYS},
            })
            bonus = f" = {raw_xp} × {multiplier:g} ({', '.join(notes)})" if notes and raw_xp > 0 else ""
            line = f"{soldier['name']}: +{gained.get('crpt', 0)} опыта{bonus}"
            if earned:
                line += f", награды {', '.join(earned)} +{award_xp}"
            line += f" (всего {total.get('crpt', 0)})"
            if rank > old_rank:
                line += f", ПОВЫШЕНИЕ {old_rank} -> {rank}"
            summary.append(line)

    log.info("раунд #%d %s (%s), победила команда %d:\n  %s", round_id, info.get("map"), info.get("gm"),
             winner, "\n  ".join(summary) or "нет игроков с профилями")
    return "OK"
