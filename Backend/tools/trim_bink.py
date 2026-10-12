"""Делает из Bink-ролика (.bik) корректный файл из одного кадра.

Игре нужны файлы заставок (без них BF2142 ломается при Alt+Tab), но смотреть
их каждый раз незачем: однокадровый ролик «проигрывается» за ~0,03 с.

    .venv\\Scripts\\python.exe tools\\trim_bink.py ВХОД.bik ВЫХОД.bik
"""

import struct
import sys
from pathlib import Path


def trim_to_one_frame(data: bytes) -> bytes:
    if data[:3] != b"BIK":
        raise ValueError("это не Bink-файл")
    frames = struct.unpack_from("<I", data, 8)[0]
    tracks = struct.unpack_from("<I", data, 40)[0]
    index_pos = 44 + 12 * tracks  # на дорожку: макс. размер, частота+флаги, id
    off0, off1 = struct.unpack_from("<II", data, index_pos)
    if frames < 1:
        raise ValueError("в ролике нет кадров")
    frame0 = data[off0 & ~1:off1 & ~1]

    header = bytearray(data[:index_pos])
    new_off0 = index_pos + 8  # таблица смещений: начало кадра 0 и конец файла
    total = new_off0 + len(frame0)
    struct.pack_into("<IIII", header, 4, total - 8, 1, len(frame0), 1)  # размер, кадров, макс. кадр, кадров
    index = struct.pack("<II", new_off0 | (off0 & 1), total)
    return bytes(header) + index + frame0


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    out = trim_to_one_frame(src.read_bytes())
    dst.write_bytes(out)
    print(f"{src.name}: {src.stat().st_size:,} -> {len(out):,} байт")


if __name__ == "__main__":
    main()
