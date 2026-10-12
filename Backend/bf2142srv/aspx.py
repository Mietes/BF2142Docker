"""Формат ответов статистики EA/GameSpy (*.aspx).

    O
    H<TAB>колонка1<TAB>колонка2
    D<TAB>значение1<TAB>значение2
    ...
    $<TAB>N<TAB>$

N — длина тела без символов табуляции и перевода строки.
"""


def _fmt(value) -> str:
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _finish(body: str) -> bytes:
    raw = body.encode("utf-8")
    count = len(raw.replace(b"\t", b"").replace(b"\n", b""))
    return raw + f"\n$\t{count}\t$\n".encode()


def build(*sections) -> bytes:
    """sections: пары (колонки, строки); строки — списки значений."""
    lines = ["O"]
    for headers, rows in sections:
        lines.append("H\t" + "\t".join(headers))
        for row in rows:
            lines.append("D\t" + "\t".join(_fmt(v) for v in row))
    return _finish("\n".join(lines))


def build_raw(text: str) -> bytes:
    """Готовое тело (например, многострочный config в getbackendinfo)."""
    return _finish(text)


def error(code: int = 104) -> bytes:
    return _finish(f"E\t{code}")
