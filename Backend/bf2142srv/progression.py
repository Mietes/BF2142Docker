"""Правила прокачки: звания и дерево анлоков."""

from .config import Config

# Очки опыта (crpt), нужные для звания: индекс = звание.
# Совпадает с mods/bf2142/Settings/RankSettings.con игры.
RANK_POINTS = [
    0, 40, 80, 120, 200, 330, 520, 750, 1050, 1400,
    1800, 2250, 2850, 3550, 4400, 5300, 6250, 7250, 8250, 9300,
    10400, 11550, 12700, 14000, 15300, 16700, 18300, 20100, 22100, 24200,
    26400, 28800, 31500, 34200, 37100, 40200, 43300, 46900, 50500, 54100,
    57700,
]
MAX_NORMAL_RANK = len(RANK_POINTS) - 1  # 40; звания 41-43 — особые (топ рейтинга)

# Дерево анлоков: (kit, tree) -> число предметов в ветке.
# kit 1-4 — разведчик/штурмовик/инженер/поддержка, kit 5 — общие (снаряжение
# игрока и гаджеты командира отделения). ID анлока = f"{kit}{tree}{уровень}".
TREES: dict[tuple[int, int], int] = {
    (1, 1): 5, (1, 2): 5,
    (2, 1): 5, (2, 2): 5,
    (3, 1): 5, (3, 2): 5,
    (4, 1): 5, (4, 2): 5,
    (5, 1): 6, (5, 2): 4,
}


def rank_for_points(points: float) -> int:
    rank = 0
    for r, need in enumerate(RANK_POINTS):
        if points >= need:
            rank = r
    return rank


def all_unlocks(cfg: Config) -> dict[tuple[int, int], int]:
    result = dict(TREES)
    if not cfg.squad_gadgets:
        result[(5, 2)] = 1
    return result


def unlock_ids(levels: dict[tuple[int, int], int]) -> list[str]:
    return [f"{kit}{tree}{lvl}" for (kit, tree), lvl in sorted(levels.items()) if lvl > 0]


def earned_credits(cfg: Config, rank: int) -> int:
    """Стартовые очки + очки за каждое достигнутое звание по расписанию из конфига."""
    total = cfg.start_credits
    for first, last, per_rank in cfg.credits_schedule:
        reached = min(rank, last) - first + 1
        if reached > 0:
            total += reached * per_rank
    return total


# Спецзвания по месту в недельном топе: место -> звание.
SPECIAL_RANKS = [(1, 43), (3, 42), (10, 41)]


def special_rank(place: int) -> int | None:
    for last_place, rank in SPECIAL_RANKS:
        if place <= last_place:
            return rank
    return None


def spent_credits(levels: dict[tuple[int, int], int]) -> int:
    return sum(levels.values())


def parse_unlock_id(uid: str) -> tuple[int, int, int] | None:
    if len(uid) != 3 or not uid.isdigit():
        return None
    kit, tree, level = (int(c) for c in uid)
    if (kit, tree) not in TREES or not 1 <= level <= TREES[(kit, tree)]:
        return None
    return kit, tree, level
