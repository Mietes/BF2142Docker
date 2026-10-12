"""Общее для администрирования: правила имён, длительность банов, поиск аккаунта по имени."""

import re
import time

# Имена аккаунтов и солдат: только латиница и цифры. Другие символы ломают табличные ответы
# статистики и итоги раунда, а кириллицы нет в части игровых шрифтов.
NAME_RE = re.compile(r"[A-Za-z0-9]{3,16}")
NAME_RULE = "только латинские буквы и цифры, от 3 до 16 символов"

_UNITS = {"m": 1, "h": 60, "d": 24 * 60, "w": 7 * 24 * 60}
_DURATION_RE = re.compile(r"(\d+)([mhdw]?)")


def valid_name(name: str) -> bool:
    return bool(NAME_RE.fullmatch(name or ""))


def parse_duration(text: str):
    """'30m', '12h', '7d', '2w', '90' (минуты) -> минуты; 'perm' -> None (навсегда).
    Не похоже на длительность -> ValueError."""
    text = text.strip().lower()
    if text in ("perm", "forever", "навсегда"):
        return None
    m = _DURATION_RE.fullmatch(text)
    if not m or int(m.group(1)) <= 0:
        raise ValueError(text)
    return int(m.group(1)) * _UNITS[m.group(2) or "m"]


def describe_ban(ban) -> str:
    until = "навсегда" if ban["until"] is None else "до " + time.strftime("%Y-%m-%d %H:%M", time.localtime(ban["until"]))
    parts = [until]
    if ban["ip"]:
        parts.append(f"IP {ban['ip']}")
    if ban["reason"]:
        parts.append(f"причина: {ban['reason']}")
    if ban["by"]:
        parts.append(f"выдал {ban['by']}")
    return ", ".join(parts)


def resolve_account(db, name: str):
    """Аккаунт по имени аккаунта или имени его солдата; None, если нет ни того, ни другого."""
    account = db.account_by_name(name)
    if account is None:
        soldier = db.soldier_by_name(name)
        if soldier is not None:
            account = db.account(soldier["account_id"])
    return account
