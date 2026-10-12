"""Награды (значки, медали, ленты, значки отличия) по итогам раунда.

Условия — из bf2142srv/res/awards_backend.con (их же получает клиент в getbackendinfo для полос прогресса):
    awards.setData 100_2 "6,1, ,20" "9,23,ktt-3,54000"
Каждое условие — "тип,код,ключ,порог":
    1, 3   — показатель за всю карьеру (ключ; несколько через ";" складываются) >= порог;
    5      — уже есть награда (ключ вида 100_1) или показатель за карьеру >= порог;
    6      — показатель за раунд по коду (ROUND_CODES) >= порог; без порога — условие «да/нет»;
    7      — показатель за раунд по ключу >= порог;
    9, 11  — время за карьеру в секундах >= порог (порог 0 — «хоть раз»);
    10     — время за раунд в секундах по коду >= порог.
Модуля выдачи наград у неранговых серверов нет (bf2.stats.medal_data был только у EA), поэтому
проверяет их бэкенд при обработке итогов раунда.

Виды: 1xx — значки, по уровням _1/_2/_3 (уровень требует предыдущий), один раз каждый;
3xx — ленты, один раз; 2xx — медали и 4xx — значки отличия, не чаще раза за раунд.
"""

import re
from dataclasses import dataclass, field

from .config import RES_DIR

KIND_BADGE, KIND_MEDAL, KIND_RIBBON, KIND_PIN = 1, 2, 3, 4

# Типы из python/bf2/stats/constants.py игрового сервера.
ARMOR = (0, 1, 2)            # VEHICLE_TYPE_MEC, APC, TANK
AIR = (4, 10)                # TRANSP_AIR, ATTACK_AIR
TRANSPORT = (1, 4, 6)        # APC, TRANSP_AIR, FAAV
NS_VEHICLES = (14, 15)       # IFV (Goliath), HOVER_FAV (Speeder)
AA_VEHICLES = (3, 12)        # ANTI_AIR, TITAN_AA
EXPLOSIVES = (21, 23, 24, 36)  # MINE, C4, CLAYMORE, FLIPPER_MINE
SHOTGUNS = (20, 31)          # AUTO_SHOTGUN, EXPLOSIVE_ROUNDS_SHOTGUN
PISTOLS = (5, 11)            # PAC_PISTOL, EU_PISTOL
SNIPERS = (0, 6, 14)         # PAC_SNIPER, EU_SNIPER, ADV_SNIPER
NS_MAPS = (10, 11, 12)       # bridge_at_remagen, liberation_of_leipzig, port_bavaria
GM_CONQUEST, GM_TITAN = 0, 1
ARMY_EU, ARMY_PAC = 0, 1


@dataclass
class Round:
    """Итог одного игрока за раунд и обстановка раунда."""
    values: dict                # ключ -> число (как в итогах раунда + производные)
    gm: int | None = None       # 0 Conquest, 1 Titan, 2 Assault Lines
    map_id: int | None = None
    army: int | None = None     # 0 ЕС, 1 ПАК
    won: bool = False
    place: int | None = None    # 1..3 по очкам среди игроков раунда
    earned: list = field(default_factory=list)  # награды, полученные в этом раунде (по порядку)

    def v(self, *keys):
        return sum(self.values.get(k, 0) for k in keys)

    def each(self, prefix, ids):
        return sum(self.values.get(f"{prefix}-{i}", 0) for i in ids)


def _no_team_damage(r):
    return int(r.v("tkls") == 0 and r.v("tdmg") == 0 and r.v("tvdmg") == 0)


# Код показателя за раунд (тексты — AWARD_CRITERIA_<код> в локализации) -> значение.
ROUND_CODES = {
    1: lambda r: r.v("kkls-3"),                      # убийства с набором поддержки
    2: lambda r: r.v("kkls-0"),                      # разведчика
    3: lambda r: r.v("kkls-1"),                      # штурмовика
    4: lambda r: r.v("kkls-2"),                      # инженера
    5: lambda r: r.v("wkls-12"),                     # ножом
    6: lambda r: r.each("wkls", SHOTGUNS),
    7: lambda r: r.each("wkls", PISTOLS),
    8: lambda r: r.each("wkls", EXPLOSIVES),
    9: lambda r: r.each("vkls", AA_VEHICLES) + r.v("wkls-30"),   # ПВО
    11: lambda r: r.each("vkls", ARMOR),
    12: lambda r: r.each("vkls", AIR),
    14: lambda r: r.v("klls") if r.gm == GM_TITAN else 0,
    17: lambda r: r.v("klls"),
    18: lambda r: r.each("vtp", AA_VEHICLES) + r.v("wtp-30"),     # время в ПВО
    34: lambda r: r.v("cs"),
    38: lambda r: r.v("tac"),
    39: lambda r: r.v("cs") if r.gm == GM_TITAN else 0,
    40: lambda r: r.v("cs") if r.gm == GM_CONQUEST else 0,
    41: lambda r: r.v("twsc"),
    42: lambda r: r.v("rps"),
    43: lambda r: r.v("hls"),
    44: lambda r: r.v("rvs"),
    45: lambda r: r.v("resp"),
    46: lambda r: r.v("tas"),
    47: lambda r: r.v("tds"),
    48: lambda r: r.v("tcd"),
    49: lambda r: r.v("tcrd"),
    50: lambda r: r.v("slbspn"),
    59: lambda r: int("401" in r.earned),            # получил в этом раунде значок отличия 401
    60: lambda r: int("410" in r.earned),
    61: lambda r: int("402" in r.earned),
    83: _no_team_damage,
    86: lambda r: r.v("tdrps"),
    89: lambda r: r.v("klstrk"),
    93: lambda r: r.v("pdt"),
    109: lambda r: r.v("tgd"),
    110: lambda r: sum(v for k, v in r.values.items() if k.startswith("vrkls-")),
    116: lambda r: r.each("vrkls", TRANSPORT),
    120: lambda r: r.v("vtp-8"),                     # секунды в парашюте
    124: lambda r: int(r.gm == GM_TITAN and r.won),  # титан команды уцелел
    125: lambda r: int(r.place == 1),
    126: lambda r: int(r.place == 2),
    127: lambda r: int(r.place == 3),
    138: lambda r: r.v("vkls-12"),
    139: lambda r: r.each("whs", SNIPERS),            # выстрелы в голову из снайперских винтовок
    141: lambda r: r.each("vtp", ARMOR),
    142: lambda r: r.each("vtp", AIR),
    143: lambda r: r.v("tasl"),
    144: lambda r: r.v("tasm"),
    145: lambda r: r.v("tt") if r.army == ARMY_EU else 0,
    146: lambda r: r.v("tt") if r.army == ARMY_PAC else 0,
    149: lambda r: r.v("tac") if r.gm == GM_TITAN else 0,
    150: lambda r: r.v("tac") if r.gm == GM_CONQUEST else 0,
    151: lambda r: r.each("vtp", TRANSPORT),
    152: lambda r: r.v("klls") if r.map_id in NS_MAPS else 0,
    154: lambda r: r.each("vtp", NS_VEHICLES),
    156: lambda r: r.each("vkls", NS_VEHICLES),
    157: lambda r: r.v("vrkls-15"),
    162: lambda r: r.v("vkls-14"),
    # 168 (захват базы ПАК в Assault Lines) сервер не сообщает — эта награда не выдаётся
}
# Purple Heart (216): соотношение убийств к смертям не больше порога при заметном числе смертей.
PURPLE_HEART_MIN_DEATHS = 10


def kind_of(award: str) -> int:
    return int(award[0])


@dataclass
class Criterion:
    kind: int
    code: int
    keys: tuple
    value: float | None


def load(path=None) -> dict[str, list[Criterion]]:
    """award -> условия, в порядке файла."""
    path = path or RES_DIR / "awards_backend.con"
    result = {}
    for line in path.read_text(encoding="latin-1").splitlines():
        m = re.match(r"\s*awards\.setData\s+(\S+)\s+(.*)", line)
        if not m:
            continue
        crits = []
        for raw in re.findall(r'"([^"]*)"', m.group(2)):
            kind, code, key, value = (raw.split(",") + ["", "", "", ""])[:4]
            keys = tuple(k for k in key.strip().split(";") if k)
            crits.append(Criterion(int(kind), int(code), keys, float(value) if value.strip() else None))
        result[m.group(1)] = crits
    return result


def _order(award: str):
    """Значки отличия первыми (на них ссылаются медали), затем значки по уровням, ленты, медали."""
    kind = kind_of(award)
    rank = {KIND_PIN: 0, KIND_BADGE: 1, KIND_RIBBON: 2, KIND_MEDAL: 3}[kind]
    level = int(award.split("_")[1]) if "_" in award else 0
    return rank, level, award


def evaluate(criteria: dict, r: Round, career: dict, owned: dict) -> list[str]:
    """Какие награды игрок получает за этот раунд. career — статистика уже с учётом раунда,
    owned — награды до раунда (award -> что угодно)."""
    def has(award):
        return award in owned or award in r.earned

    def total(keys):
        return sum(career.get(k, 0) for k in keys)

    def ok(c: Criterion) -> bool:
        if c.kind in (1, 3):
            return total(c.keys) >= (c.value or 0)
        if c.kind == 5:
            if c.keys and re.fullmatch(r"\d{3}(_\d)?", c.keys[0]):
                return all(has(k) for k in c.keys)
            return total(c.keys) >= (c.value or 0)
        if c.kind in (9, 11):
            value = total(c.keys)
            return value > 0 if not c.value else value >= c.value
        if c.kind in (6, 10):
            if c.code == 85:  # Purple Heart
                deaths = r.v("dths")
                return deaths >= PURPLE_HEART_MIN_DEATHS and r.v("klls") / deaths <= (c.value or 0)
            fn = ROUND_CODES.get(c.code)
            if fn is None:
                return False
            value = fn(r)
            return value >= 1 if not c.value else value >= c.value
        if c.kind == 7:
            return r.v(*c.keys) >= (c.value or 0)
        return False

    for award in sorted(criteria, key=_order):
        kind = kind_of(award)
        if kind in (KIND_BADGE, KIND_RIBBON) and has(award):
            continue
        if kind == KIND_BADGE:
            base, level = award.split("_")
            if int(level) > 1 and not has(f"{base}_{int(level) - 1}"):
                continue
        if criteria[award] and all(ok(c) for c in criteria[award]):
            r.earned.append(award)
    return list(r.earned)


def xp_for(cfg, award: str) -> int:
    kind = kind_of(award)
    if kind == KIND_BADGE:
        level = int(award.split("_")[1])
        levels = cfg.award_xp_badge
        return int(levels[min(level, len(levels)) - 1]) if levels else 0
    return {KIND_MEDAL: cfg.award_xp_medal, KIND_RIBBON: cfg.award_xp_ribbon, KIND_PIN: cfg.award_xp_pin}[kind]
