"""Generuje assets/icon.ico i assets/wheel.png (bez zewnętrznych bibliotek).

Wzór: koło motocrossowe – opona z kostkami (terenowy bieżnik), srebrna obręcz,
szprychy i piasta. Ikona ma pomarańczowe tło (zaokrąglony kwadrat), logo
wheel.png jest przezroczyste. Uruchom: python assets/make_icon.py [podgląd.png]
"""
import math
import os
import struct
import sys
import zlib

SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
LOGO_SIZE = 160
SS = 4  # próbek na oś piksela (antyaliasing)


def hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


BG_TOP, BG_BOT = hex_rgb("#ff8a2a"), hex_rgb("#d94400")
TIRE = hex_rgb("#141518")
TIRE_EDGE = hex_rgb("#2a2c31")
RIM = hex_rgb("#d4d7dd")
RIM_DARK = hex_rgb("#8d929b")
SPOKE = hex_rgb("#1d1e22")
SPOKE_LOGO = hex_rgb("#b9bdc5")
HUB = hex_rgb("#1b1c20")
HUB_CAP = hex_rgb("#ff6b1a")

KNOBS = 24
SPOKES = 16


def in_rounded_square(x, y, m=0.03, r=0.22):
    if not (m <= x <= 1 - m and m <= y <= 1 - m):
        return False
    cx = min(max(x, m + r), 1 - m - r)
    cy = min(max(y, m + r), 1 - m - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def wheel(x, y, logo):
    """Kolor koła w punkcie albo None (poza kołem / prześwit między szprychami)."""
    dx, dy = x - 0.5, y - 0.5
    r = math.hypot(dx, dy)
    a = math.atan2(dy, dx)
    scale = 1.06 if logo else 1.0          # logo bez tła – koło trochę większe
    r /= scale
    if r > 0.46:
        return None
    if r >= 0.41:                          # kostki bieżnika (dwa rzędy na przemian)
        k = (a / (2 * math.pi) * KNOBS) % 2.0
        row = 0 if k < 1 else 1
        k %= 1.0
        top = 0.46 if row == 0 else 0.445
        if 0.12 < k < 0.70 and r < top:
            return TIRE_EDGE if r > top - 0.012 else TIRE
        return None
    if r >= 0.30:                          # opona
        return lerp(TIRE, TIRE_EDGE, max(0.0, (r - 0.37) / 0.035)) if r > 0.37 else TIRE
    if r >= 0.262:                         # obręcz z cieniem od środka
        return lerp(RIM_DARK, RIM, min(1.0, (r - 0.262) / 0.02))
    if r < 0.034:
        return HUB_CAP
    if r < 0.078:                          # piasta
        return HUB
    # szprychy – lekko styczne do piasty, jak w prawdziwym kole
    for i in range(SPOKES):
        base = 2 * math.pi * i / SPOKES
        off = 0.05 if i % 2 else -0.05     # krzyżowanie szprych
        ang = base + off * (0.262 - r) / 0.184 * 1.6
        d = abs((a - ang + math.pi) % (2 * math.pi) - math.pi) * r
        if d < 0.0105:
            return SPOKE_LOGO if logo else SPOKE
    return None


def sample_icon(x, y):
    if not in_rounded_square(x, y):
        return None
    c = wheel(x, y, False)
    return c if c else lerp(BG_TOP, BG_BOT, y)


def sample_logo(x, y):
    return wheel(x, y, True)


def render(size, fn):
    rows = []
    n = SS * SS
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = a = 0
            for sy in range(SS):
                for sx in range(SS):
                    c = fn((px + (sx + 0.5) / SS) / size, (py + (sy + 0.5) / SS) / size)
                    if c:
                        r += c[0]; g += c[1]; b += c[2]; a += 1
            if a:
                row += bytes((round(r / a), round(g / a), round(b / a), round(255 * a / n)))
            else:
                row += b"\0\0\0\0"
        rows.append(bytes(row))
    return rows


def png(size, rows):
    def chunk(tag, data):
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", zlib.crc32(tag + data) & 0xffffffff)
    raw = b"".join(b"\0" + r for r in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def bmp(size, rows):
    """Klasyczny wpis ICO (DIB 32 bpp) – najlepiej obsługiwany przez Eksplorator."""
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = bytearray()
    for r in reversed(rows):  # DIB zapisuje wiersze od dołu
        for i in range(0, len(r), 4):
            pixels += bytes((r[i + 2], r[i + 1], r[i], r[i + 3]))  # RGBA -> BGRA
    mask_row = ((size + 31) // 32) * 4
    return header + bytes(pixels) + bytes(mask_row * size)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    rendered = [(s, render(s, sample_icon)) for s in SIZES]
    # 256 px jako PNG (standard Windows), mniejsze jako BMP
    images = [(s, png(s, r) if s == 256 else bmp(s, r)) for s, r in rendered]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, data = b"", b""
    for s, img in images:
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(img), offset + len(data))
        data += img
    with open(os.path.join(here, "icon.ico"), "wb") as f:
        f.write(header + entries + data)
    with open(os.path.join(here, "wheel.png"), "wb") as f:
        f.write(png(LOGO_SIZE, render(LOGO_SIZE, sample_logo)))
    print("Zapisano icon.ico i wheel.png w", here)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "wb") as f:
            f.write(png(256, rendered[-1][1]))


if __name__ == "__main__":
    main()
