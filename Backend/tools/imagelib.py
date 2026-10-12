"""Минимальная работа с картинками без внешних библиотек: DDS (DXT1/3/5, ARGB), TGA, PNG.

Картинка — кортеж (w, h, px), где px — bytearray RGBA (по 4 байта на пиксель, построчно сверху вниз).
"""

import struct
import zlib


# ---------------------------------------------------------------- PNG

def read_png(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, idat, plte, trns = 8, b"", None, None
    while pos < len(data):
        ln, typ = struct.unpack_from(">I4s", data, pos)
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            assert depth == 8 and not interlace, "only 8-bit non-interlaced PNG"
        elif typ == b"PLTE":
            plte = body
        elif typ == b"tRNS":
            trns = body
        elif typ == b"IDAT":
            idat += body
    raw = zlib.decompress(idat)
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    stride = w * bpp
    rows, prev, p = [], bytearray(stride), 0
    for _ in range(h):
        ftype = raw[p]; line = bytearray(raw[p + 1:p + 1 + stride]); p += 1 + stride
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if ftype == 1: line[i] = (line[i] + a) & 255
            elif ftype == 2: line[i] = (line[i] + b) & 255
            elif ftype == 3: line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif ftype == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line); prev = line
    px = bytearray(w * h * 4)
    o = 0
    for line in rows:
        for x in range(w):
            if ctype == 6: r, g, b_, a_ = line[x * 4:x * 4 + 4]
            elif ctype == 2: r, g, b_ = line[x * 3:x * 3 + 3]; a_ = 255
            elif ctype == 0: r = g = b_ = line[x]; a_ = 255
            elif ctype == 4: r = g = b_ = line[x * 2]; a_ = line[x * 2 + 1]
            else:
                i = line[x]; r, g, b_ = plte[i * 3:i * 3 + 3]
                a_ = trns[i] if trns is not None and i < len(trns) else 255
            px[o:o + 4] = bytes((r, g, b_, a_)); o += 4
    return w, h, px


def write_png(img, alpha=True):
    w, h, px = img
    bpp = 4 if alpha else 3
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        row = px[y * w * 4:(y + 1) * w * 4]
        if alpha:
            raw += row
        else:
            for x in range(w):
                raw += row[x * 4:x * 4 + 3]

    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6 if alpha else 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


# ---------------------------------------------------------------- DDS / TGA

def _c565(c):
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def _color_block(data, p, dxt1):
    c0, c1, bits = struct.unpack_from("<HHI", data, p)
    a, b = _c565(c0), _c565(c1)
    if c0 > c1 or not dxt1:
        pal = [a + (255,), b + (255,),
               tuple((2 * x + y) // 3 for x, y in zip(a, b)) + (255,),
               tuple((x + 2 * y) // 3 for x, y in zip(a, b)) + (255,)]
    else:
        pal = [a + (255,), b + (255,), tuple((x + y) // 2 for x, y in zip(a, b)) + (255,), (0, 0, 0, 0)]
    return [pal[(bits >> (2 * i)) & 3] for i in range(16)]


def read_dds(data):
    assert data[:4] == b"DDS ", "not a DDS"
    h, w = struct.unpack_from("<II", data, 12)
    pf_flags, fourcc, rgbbits, rmask, gmask, bmask, amask = struct.unpack_from("<I4sIIIII", data, 80)
    p = 128
    px = bytearray(w * h * 4)
    if pf_flags & 0x4:
        kind = fourcc.decode()
        assert kind in ("DXT1", "DXT3", "DXT5"), kind
        for by in range(0, h, 4):
            for bx in range(0, w, 4):
                alphas = None
                if kind == "DXT5":
                    a0, a1 = data[p], data[p + 1]
                    bits = int.from_bytes(data[p + 2:p + 8], "little")
                    if a0 > a1:
                        ap = [a0, a1] + [((6 - i) * a0 + (i + 1) * a1) // 7 for i in range(6)]
                    else:
                        ap = [a0, a1] + [((4 - i) * a0 + (i + 1) * a1) // 5 for i in range(4)] + [0, 255]
                    alphas = [ap[(bits >> (3 * i)) & 7] for i in range(16)]
                    p += 8
                elif kind == "DXT3":
                    bits = int.from_bytes(data[p:p + 8], "little")
                    alphas = [((bits >> (4 * i)) & 15) * 17 for i in range(16)]
                    p += 8
                cols = _color_block(data, p, kind == "DXT1"); p += 8
                for i in range(16):
                    x, y = bx + (i & 3), by + (i >> 2)
                    if x < w and y < h:
                        r, g, b, a = cols[i]
                        if alphas is not None:
                            a = alphas[i]
                        o = (y * w + x) * 4
                        px[o:o + 4] = bytes((r, g, b, a))
        return w, h, px

    def shift(mask):
        s = 0
        while mask and not mask & 1:
            mask >>= 1; s += 1
        return s, mask
    step = rgbbits // 8
    chans = [shift(m) for m in (rmask, gmask, bmask, amask)]
    for i in range(w * h):
        v = int.from_bytes(data[p:p + step], "little"); p += step
        out = []
        for s, m in chans:
            out.append(((v >> s) & m) * 255 // m if m else 255)
        px[i * 4:i * 4 + 4] = bytes(out)
    return w, h, px


def read_tga(data):
    idlen, cmtype, itype = data[0], data[1], data[2]
    w, h, bits, desc = struct.unpack_from("<HHBB", data, 12)
    assert cmtype == 0 and itype in (2, 10), "only true-color TGA"
    step = bits // 8
    p = 18 + idlen
    pixels = []
    if itype == 2:
        for i in range(w * h):
            pixels.append(data[p:p + step]); p += step
    else:
        while len(pixels) < w * h:
            hdr = data[p]; p += 1
            n = (hdr & 127) + 1
            if hdr & 128:
                pixels.extend([data[p:p + step]] * n); p += step
            else:
                for _ in range(n):
                    pixels.append(data[p:p + step]); p += step
    px = bytearray(w * h * 4)
    top = bool(desc & 0x20)
    for i, c in enumerate(pixels):
        x, y = i % w, i // w
        if not top:
            y = h - 1 - y
        a = c[3] if step == 4 else 255
        px[(y * w + x) * 4:(y * w + x) * 4 + 4] = bytes((c[2], c[1], c[0], a))
    return w, h, px


def read_any(name, data):
    low = name.lower()
    if low.endswith(".dds"):
        return read_dds(data)
    if low.endswith(".tga"):
        return read_tga(data)
    return read_png(data)


# ---------------------------------------------------------------- операции

def new(w, h, rgba=(0, 0, 0, 0)):
    return w, h, bytearray(bytes(rgba) * (w * h))


def crop(img, x0, y0, x1, y1):
    w, h, px = img
    out = bytearray()
    for y in range(y0, y1):
        out += px[(y * w + x0) * 4:(y * w + x1) * 4]
    return x1 - x0, y1 - y0, out


def alpha_bbox(img, threshold=8):
    w, h, px = img
    xs, ys = [], []
    for y in range(h):
        row = px[y * w * 4:(y + 1) * w * 4]
        for x in range(w):
            if row[x * 4 + 3] > threshold:
                xs.append(x); ys.append(y)
    if not xs:
        return 0, 0, w, h
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def trim(img, pad=0):
    x0, y0, x1, y1 = alpha_bbox(img)
    w, h, _ = img
    return crop(img, max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad))


def resize(img, nw, nh):
    """Уменьшение/увеличение с усреднением по площади (premultiplied alpha)."""
    w, h, px = img
    out = bytearray(nw * nh * 4)
    sx, sy = w / nw, h / nh
    for oy in range(nh):
        fy0, fy1 = oy * sy, (oy + 1) * sy
        for ox in range(nw):
            fx0, fx1 = ox * sx, (ox + 1) * sx
            acc = [0.0, 0.0, 0.0, 0.0]; tot = 0.0
            y = int(fy0)
            while y < fy1 and y < h:
                wy = min(fy1, y + 1) - max(fy0, y)
                x = int(fx0)
                while x < fx1 and x < w:
                    wx = min(fx1, x + 1) - max(fx0, x)
                    wgt = wx * wy
                    o = (y * w + x) * 4
                    a = px[o + 3] / 255.0
                    acc[0] += px[o] * a * wgt; acc[1] += px[o + 1] * a * wgt; acc[2] += px[o + 2] * a * wgt
                    acc[3] += a * wgt; tot += wgt
                    x += 1
                y += 1
            o = (oy * nw + ox) * 4
            if acc[3] > 0:
                out[o] = min(255, round(acc[0] / acc[3])); out[o + 1] = min(255, round(acc[1] / acc[3]))
                out[o + 2] = min(255, round(acc[2] / acc[3]))
            out[o + 3] = min(255, round(acc[3] / tot * 255)) if tot else 0
    return nw, nh, out


def fit(img, bw, bh, margin=1):
    """Вписать картинку (обрезанную по альфе) в прозрачный холст bw×bh по центру."""
    img = trim(img)
    w, h, _ = img
    k = min((bw - 2 * margin) / w, (bh - 2 * margin) / h)
    nw, nh = max(1, round(w * k)), max(1, round(h * k))
    small = resize(img, nw, nh)
    canvas = new(bw, bh)
    paste(canvas, small, (bw - nw) // 2, (bh - nh) // 2)
    return canvas


def paste(dst, src, ox, oy):
    """Альфа-наложение src на dst в точке (ox, oy)."""
    dw, dh, dp = dst
    sw, sh, sp = src
    for y in range(sh):
        ty = oy + y
        if not 0 <= ty < dh:
            continue
        for x in range(sw):
            tx = ox + x
            if not 0 <= tx < dw:
                continue
            s = (y * sw + x) * 4; d = (ty * dw + tx) * 4
            sa = sp[s + 3] / 255.0
            if sa <= 0:
                continue
            da = dp[d + 3] / 255.0
            oa = sa + da * (1 - sa)
            for c in range(3):
                dp[d + c] = round((sp[s + c] * sa + dp[d + c] * da * (1 - sa)) / oa)
            dp[d + 3] = round(oa * 255)


def silhouette(img, rgb=(0, 0, 0)):
    w, h, px = img
    out = bytearray(px)
    for i in range(0, len(out), 4):
        out[i:i + 3] = bytes(rgb)
    return w, h, out


def tint(img, rgb):
    """Перекрасить в один цвет с сохранением яркости (для белых пиктограмм)."""
    w, h, px = img
    out = bytearray(px)
    for i in range(0, len(out), 4):
        lum = (px[i] * 30 + px[i + 1] * 59 + px[i + 2] * 11) / 25500
        out[i] = round(rgb[0] * lum); out[i + 1] = round(rgb[1] * lum); out[i + 2] = round(rgb[2] * lum)
    return w, h, out
