"""Generuje assets/icon.ico i assets/wheel.png (wymaga Pillow – tylko do generowania, nie do aplikacji).

Wzór „bieżnik-pętla” (koncept nr 5): dwie pomarańczowe strzałki synchronizacji z kostkami
terenowej opony na zewnętrznej krawędzi i biała piasta w środku, na ciemnym zaokrąglonym kwadracie.
Rozmiary do 24 px dostają wersję uproszczoną (bez kostek, grubsze strzałki) – w 16 px bieżnik
byłby tylko szumem. wheel.png = to samo logo bez tła (ekran startowy).
Uruchom: python assets/make_icon.py [podgląd.png]
"""
import math
import os
import struct
import sys
import zlib

from PIL import Image, ImageDraw

SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
SIMPLE_MAX = 24             # do tylu px włącznie wersja uproszczona
LOGO_SIZE = 160
S = 1024                    # rysujemy w 1024 px i skalujemy (antyaliasing)
C = S / 2

ORANGE = (255, 106, 0)
WHITE = (245, 245, 247)
DARK_TOP, DARK_BOT = (38, 40, 46), (14, 15, 18)


def _rot(px, py, a):
    s, c = math.sin(a), math.cos(a)
    return C + px * c - py * s, C + px * s + py * c


def _arc_arrow(d, r, start, end, width, color, head):
    """Łuk o środku grubości na promieniu r ze strzałką na końcu (stopnie, zgodnie z zegarem)."""
    R = r + width / 2                   # PIL rysuje grubość łuku do środka prostokąta
    d.arc([C - R, C - R, C + R, C + R], start, end, fill=color, width=width)
    a = math.radians(end)
    hx, hy = C + r * math.cos(a), C + r * math.sin(a)
    tx, ty = -math.sin(a), math.cos(a)  # kierunek ruchu
    nx, ny = math.cos(a), math.sin(a)   # na zewnątrz
    L, W = width * 1.25 * head, width * 1.05 * head
    d.polygon([(hx + tx * L, hy + ty * L), (hx + nx * W - tx * 4, hy + ny * W - ty * 4),
               (hx - nx * W - tx * 4, hy - ny * W - ty * 4)], fill=color)


def _background(img):
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(DARK_TOP, DARK_BOT)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([24, 24, S - 24, S - 24], radius=220, fill=255)
    img.paste(grad, (0, 0), mask)


def draw(simple=False, background=True):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    if background:
        _background(img)
    d = ImageDraw.Draw(img)
    if simple:
        r, w, head, hub = 245, 175, 0.85, 105
    else:
        r, w, head, hub = 250, 120, 0.95, 78
    for start, end in ((200, 325), (20, 145)):
        if not simple:
            for k in range(7):          # kostki bieżnika: na przemian wysokie i niskie
                a = math.radians(start + 4 + k * (end - start - 22) / 6) + math.pi / 2
                h = 58 if k % 2 == 0 else 34
                base, top = r + w / 2 - 10, r + w / 2 + h
                pts = [(-30, -base), (30, -base), (25, -top), (-25, -top)]
                d.polygon([_rot(x, y, a) for x, y in pts], fill=ORANGE)
        _arc_arrow(d, r, start, end, w, ORANGE, head)
    d.ellipse([C - hub, C - hub, C + hub, C + hub], fill=WHITE)
    return img


def _rows(img):
    img = img.convert("RGBA")
    size = img.width
    raw = img.tobytes()
    return [raw[y * size * 4:(y + 1) * size * 4] for y in range(size)]


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
    full, simple = draw(), draw(simple=True)
    rendered = [(s, _rows((simple if s <= SIMPLE_MAX else full).resize((s, s), Image.LANCZOS))) for s in SIZES]
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
    draw(background=False).resize((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS).save(os.path.join(here, "wheel.png"))
    print("Zapisano icon.ico i wheel.png w", here)
    if len(sys.argv) > 1:
        full.resize((256, 256), Image.LANCZOS).save(sys.argv[1])


if __name__ == "__main__":
    main()
