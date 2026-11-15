"""6 konceptów ikony MX Sync + arkusz podglądu w małych rozmiarach."""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.dirname(os.path.abspath(__file__))
S = 1024                      # rysujemy duże, potem skalujemy (antyaliasing)
C = S / 2
ORANGE = (255, 106, 0)
ORANGE_HI = (255, 140, 40)
ORANGE_LO = (214, 68, 0)
DARK_HI = (38, 40, 46)
DARK_LO = (14, 15, 18)
BLACK = (16, 17, 20)
WHITE = (245, 245, 247)
FONT = "C:/Windows/Fonts/ariblk.ttf"


def base(top, bot):
    """Zaokrąglony kwadrat z pionowym gradientem."""
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bot)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([24, 24, S - 24, S - 24], radius=220, fill=255)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    return img


def circle(d, cx, cy, r, fill):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def rot(px, py, a, cx=C, cy=C):
    s, c = math.sin(a), math.cos(a)
    return cx + px * c - py * s, cy + px * s + py * c


def knobby_tire(d, r_out, r_in, knobs, knob_w, knob_h, color, hole, rim=None, rim_w=0):
    """Opona z kostkami (bieżnik terenowy: kostki na przemian wysokie i niskie) + obręcz."""
    for i in range(knobs):
        a = 2 * math.pi * i / knobs
        w = knob_w / 2
        h = knob_h if i % 2 == 0 else knob_h * 0.55
        pts = [(-w, -(r_out - 4)), (w, -(r_out - 4)), (w * 0.85, -(r_out + h)), (-w * 0.85, -(r_out + h))]
        d.polygon([rot(x, y, a) for x, y in pts], fill=color)
    circle(d, C, C, r_out, color)
    if rim:
        circle(d, C, C, r_in, rim)
        circle(d, C, C, r_in - rim_w, hole)
    else:
        circle(d, C, C, r_in, hole)


def arc_arrow(d, r, start, end, width, color, head=1.0):
    """Łuk ze strzałką na końcu (kąty w stopniach, zgodnie z ruchem wskazówek zegara)."""
    R = r + width / 2
    d.arc([C - R, C - R, C + R, C + R], start, end, fill=color, width=width)
    a = math.radians(end)
    hx, hy = C + r * math.cos(a), C + r * math.sin(a)
    tx, ty = -math.sin(a), math.cos(a)          # kierunek ruchu
    nx, ny = math.cos(a), math.sin(a)           # na zewnątrz
    L, W = width * 1.25 * head, width * 1.05 * head
    pts = [(hx + tx * L, hy + ty * L), (hx + nx * W - tx * 4, hy + ny * W - ty * 4),
           (hx - nx * W - tx * 4, hy - ny * W - ty * 4)]
    d.polygon(pts, fill=color)


def sync_arrows(d, r, width, color, head=1.0):
    arc_arrow(d, r, 200, 330, width, color, head)
    arc_arrow(d, r, 20, 150, width, color, head)


def text_center(d, text, size, color, cy=C, dy=0):
    f = ImageFont.truetype(FONT, size)
    l, t, rr, b = d.textbbox((0, 0), text, font=f)
    d.text((C - (l + rr) / 2, cy - (t + b) / 2 + dy), text, font=f, fill=color)


# ---------- 6 konceptów ----------

def icon1():
    """Opona + strzałki synchronizacji (ciemne tło)."""
    img = base(DARK_HI, DARK_LO)
    d = ImageDraw.Draw(img)
    knobby_tire(d, 330, 250, 22, 62, 58, WHITE, (24, 25, 30), rim=ORANGE, rim_w=26)
    sync_arrows(d, 135, 52, ORANGE, 1.1)
    return img


def icon2():
    """„MX” + okrągła strzałka (pomarańczowe tło)."""
    img = base(ORANGE_HI, ORANGE_LO)
    d = ImageDraw.Draw(img)
    sync_arrows(d, 345, 46, BLACK, 1.0)
    text_center(d, "MX", 330, BLACK, dy=-10)
    return img


def icon3():
    """Rój P2P: trzy połączone węzły w oponie."""
    img = base(DARK_HI, DARK_LO)
    d = ImageDraw.Draw(img)
    knobby_tire(d, 335, 270, 24, 56, 52, ORANGE, (22, 23, 28), rim=WHITE, rim_w=18)
    nodes = [rot(0, -140, math.radians(a)) for a in (0, 120, 240)]
    for i in range(3):
        d.line([nodes[i], nodes[(i + 1) % 3]], fill=WHITE, width=34)
    for x, y in nodes:
        circle(d, x, y, 62, WHITE)
        circle(d, x, y, 34, ORANGE)
    return img


def icon4():
    """Opona + strzałka pobierania (pomarańczowe tło)."""
    img = base(ORANGE_HI, ORANGE_LO)
    d = ImageDraw.Draw(img)
    knobby_tire(d, 320, 215, 22, 64, 62, BLACK, (255, 124, 24), rim=WHITE, rim_w=22)
    d.rectangle([C - 44, C - 130, C + 44, C + 15], fill=BLACK)
    d.polygon([(C - 115, C + 5), (C + 115, C + 5), (C, C + 130)], fill=BLACK)
    return img


def icon5():
    """Bieżnik w pętli: dwie strzałki z kostkami opony (ciemne tło)."""
    img = base(DARK_HI, DARK_LO)
    d = ImageDraw.Draw(img)
    r, w = 250, 120
    for seg in ((200, 325), (20, 145)):
        for k in range(7):
            a = math.radians(seg[0] + 4 + k * (seg[1] - seg[0] - 22) / 6)
            h = 58 if k % 2 == 0 else 34
            pts = [(-30, -(r + w / 2 - 10)), (30, -(r + w / 2 - 10)), (25, -(r + w / 2 + h)), (-25, -(r + w / 2 + h))]
            d.polygon([rot(x, y, a + math.pi / 2) for x, y in pts], fill=ORANGE)
        arc_arrow(d, r, seg[0], seg[1], w, ORANGE, 0.95)
    circle(d, C, C, 78, WHITE)
    return img


def icon6():
    """Paczka modów: skrzynka + plakietka synchronizacji."""
    img = base(ORANGE_HI, ORANGE_LO)
    d = ImageDraw.Draw(img)
    cx, cy, a, h = C - 20, C - 10, 270, 300            # izometryczny sześcian
    top = [(cx, cy - a * 0.95), (cx + a, cy - a * 0.45), (cx, cy + a * 0.05), (cx - a, cy - a * 0.45)]
    left = [(cx - a, cy - a * 0.45), (cx, cy + a * 0.05), (cx, cy + a * 0.05 + h * 0.85), (cx - a, cy - a * 0.45 + h * 0.85)]
    right = [(cx + a, cy - a * 0.45), (cx, cy + a * 0.05), (cx, cy + a * 0.05 + h * 0.85), (cx + a, cy - a * 0.45 + h * 0.85)]
    d.polygon(left, fill=(30, 31, 36))
    d.polygon(right, fill=BLACK)
    d.polygon(top, fill=(56, 58, 66))
    d.line([(cx - a / 2, cy - a * 0.70), (cx + a / 2, cy - a * 0.20)], fill=ORANGE, width=34)   # taśma
    bx, by, br = C + 215, C + 215, 175
    circle(d, bx, by, br + 26, ORANGE_LO)
    circle(d, bx, by, br, WHITE)
    sub = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sync_arrows(ImageDraw.Draw(sub), 80, 34, ORANGE_LO, 1.0)
    sub = sub.crop((C - 160, C - 160, C + 160, C + 160))
    img.alpha_composite(sub, (int(bx - 160), int(by - 160)))
    return img


ICONS = [(icon1, "1 · Opona + sync"), (icon2, "2 · MX + sync"), (icon3, "3 · Rój P2P"),
         (icon4, "4 · Opona + pobieranie"), (icon5, "5 · Bieżnik-pętla"), (icon6, "6 · Paczka modów")]


def sheet(imgs):
    """Arkusz: każda ikona w 256/64/32/16 px na ciemnym i jasnym pasku zadań."""
    sizes = (256, 64, 32, 16)
    row_h, pad = 300, 30
    W = 1500
    out = Image.new("RGB", (W, row_h * len(imgs) + 70), (30, 31, 34))
    d = ImageDraw.Draw(out)
    f = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 30)
    fs = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 22)
    d.text((pad, 18), "MX Sync – koncepty ikony (256 / 64 / 32 / 16 px, pasek ciemny i jasny)", font=f, fill=WHITE)
    for i, (img, name) in enumerate(imgs):
        y = 70 + i * row_h
        d.text((pad, y + 4), name, font=fs, fill=(200, 200, 205))
        x = pad
        for s in sizes:
            small = img.resize((s, s), Image.LANCZOS)
            out.paste(small, (x, y + 36), small)
            x += max(s, 40) + 30
        for bg in ((32, 32, 32), (238, 238, 238)):     # pasek zadań Windows 11
            d.rectangle([x, y + 120, x + 330, y + 200], fill=bg)
            xx = x + 20
            for s in (48, 32, 24, 16):
                small = img.resize((s, s), Image.LANCZOS)
                out.paste(small, (xx, y + 160 - s // 2), small)
                xx += s + 30
            x += 360
    return out


if __name__ == "__main__":
    done = []
    for fn, name in ICONS:
        big = fn()
        img = big.resize((512, 512), Image.LANCZOS)
        img.save(os.path.join(OUT, f"ikona{name[0]}.png"))
        done.append((big, name))
    sheet(done).save(os.path.join(OUT, "podglad.png"))
    print("ok")
