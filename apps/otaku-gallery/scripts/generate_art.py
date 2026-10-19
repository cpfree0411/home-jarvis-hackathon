#!/usr/bin/env python3
"""Generate the bundled sample illustrations (original, procedural SVG, CC0 1.0).

Every picture is drawn from scratch by this script with a fixed random seed, so
the files in web/art/ are reproducible and nothing is traced from, or inspired
by identifiable third-party artwork. Run:  python3 scripts/generate_art.py
"""
import math
import random
import sys
from pathlib import Path

W, H = 1600, 900
OUT = Path(__file__).resolve().parent.parent / "web" / "art"
CREDIT = ("Original sample illustration for the OTAKU Gallery hackathon demo. Procedurally drawn by "
          "scripts/generate_art.py (authored by Claude, Anthropic). Dedicated to the public domain under CC0 1.0.")


def f(x):
    return ("%.1f" % x).rstrip("0").rstrip(".")


def svg(title, desc, body, defs=""):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img">\n'
            '<title>%s</title>\n<desc>%s %s</desc>\n<defs>%s</defs>\n%s\n</svg>\n'
            % (W, H, W, H, title, desc, CREDIT, defs, body))


def grad(id_, stops, x1=0, y1=0, x2=0, y2=1, kind="linear", extra=""):
    inner = "".join('<stop offset="%s" stop-color="%s"%s/>' % (o, c, (' stop-opacity="%s"' % a) if a is not None else "")
                    for o, c, a in [(s + (None,))[:3] if len(s) == 2 else s for s in stops])
    if kind == "linear":
        return '<linearGradient id="%s" x1="%s" y1="%s" x2="%s" y2="%s">%s</linearGradient>' % (id_, x1, y1, x2, y2, inner)
    return '<radialGradient id="%s" %s>%s</radialGradient>' % (id_, extra or 'cx="0.5" cy="0.5" r="0.5"', inner)


def blur(id_, sd):
    return '<filter id="%s" x="-50%%" y="-50%%" width="200%%" height="200%%"><feGaussianBlur stdDeviation="%s"/></filter>' % (id_, sd)


def stars(rng, n, y0, y1, colors=("#ffffff", "#cfe3ff", "#ffe9c7"), rmax=2.2):
    out = []
    for _ in range(n):
        out.append('<circle cx="%s" cy="%s" r="%s" fill="%s" opacity="%s"/>' % (
            f(rng.uniform(0, W)), f(rng.uniform(y0, y1)), f(rng.uniform(.4, rmax)), rng.choice(colors), f(rng.uniform(.3, 1))))
    return "".join(out)


def cloud(cx, cy, w, color, op=1.0, h=None, filt=""):
    h = h or w * .18
    parts = [(0, 0, w * .5, h), (-w * .28, h * .15, w * .3, h * .8), (w * .3, h * .1, w * .32, h * .85),
             (-w * .05, -h * .35, w * .28, h * .8), (w * .15, -h * .25, w * .22, h * .7)]
    inner = "".join('<ellipse cx="%s" cy="%s" rx="%s" ry="%s"/>' % (f(cx + dx), f(cy + dy), f(rx), f(ry)) for dx, dy, rx, ry in parts)
    return '<g fill="%s" opacity="%s"%s>%s</g>' % (color, op, (' filter="url(#%s)"' % filt) if filt else "", inner)


def buildings(rng, base, x0, x1, hmin, hmax, wmin, wmax, fill, win=None, win_p=.35, gap=(0, 6)):
    out, x = [], x0
    while x < x1:
        w, h = rng.uniform(wmin, wmax), rng.uniform(hmin, hmax)
        out.append('<rect x="%s" y="%s" width="%s" height="%s" fill="%s"/>' % (f(x), f(base - h), f(w), f(h + 2), fill))
        if rng.random() < .25:
            out.append('<rect x="%s" y="%s" width="%s" height="%s" fill="%s"/>' % (f(x + w * .3), f(base - h - 18), f(w * .4), 18, fill))
        if win:
            cols, rows = max(1, int(w // 16)), max(1, int(h // 22))
            for r in range(rows):
                for c in range(cols):
                    if rng.random() < win_p:
                        out.append('<rect x="%s" y="%s" width="7" height="10" fill="%s" opacity="%s"/>' % (
                            f(x + 6 + c * 16), f(base - h + 8 + r * 22), rng.choice(win), f(rng.uniform(.5, 1))))
        x += w + rng.uniform(*gap)
    return "".join(out)


def sparkle(x, y, s, color="#fff", op=1):
    d = "M%s %s L%s %s L%s %s L%s %s L%s %s L%s %s L%s %s L%s %s Z" % (
        f(x), f(y - s), f(x + s * .18), f(y - s * .18), f(x + s), f(y), f(x + s * .18), f(y + s * .18),
        f(x), f(y + s), f(x - s * .18), f(y + s * .18), f(x - s), f(y), f(x - s * .18), f(y - s * .18))
    return '<path d="%s" fill="%s" opacity="%s"/>' % (d, color, op)


def girl(x, y, s, dress, hair, rim, extra=""):
    """A simple back-view silhouette: long hair, bodice, flared skirt, legs. Origin at the feet."""
    g = ('<g transform="translate(%s %s) scale(%s)">' % (f(x), f(y), s))
    g += '<rect x="-9" y="-62" width="6" height="62" fill="%s"/><rect x="3" y="-62" width="6" height="62" fill="%s"/>' % (dress, dress)
    g += '<path d="M-13 -96 L-36 -50 Q0 -40 36 -50 L13 -96 Z" fill="%s"/>' % dress
    g += '<path d="M-13 -96 Q-17 -130 -12 -152 L12 -152 Q17 -130 13 -96 Z" fill="%s"/>' % dress
    g += '<path d="M-12 -150 L-26 -112 M12 -150 L26 -112" stroke="%s" stroke-width="7" stroke-linecap="round" fill="none"/>' % dress
    g += '<ellipse cx="0" cy="-172" rx="15" ry="17" fill="%s"/>' % hair
    g += '<path d="M-17 -176 Q-27 -130 -21 -84 Q0 -76 21 -84 Q27 -130 17 -176 Q0 -194 -17 -176 Z" fill="%s"/>' % hair
    g += '<path d="M17 -176 Q27 -130 21 -84" stroke="%s" stroke-width="2.4" fill="none" opacity=".85"/>' % rim
    g += '<path d="M-36 -50 Q0 -40 36 -50" stroke="%s" stroke-width="1.6" fill="none" opacity=".6"/>' % rim
    g += extra + "</g>"
    return g


def neon_rooftop_rain():
    rng = random.Random(11)
    defs = (grad("sky", [(0, "#0a0420"), (.5, "#2b0f55"), (.85, "#a3216b"), (1, "#ff5f8d")]) +
            blur("b8", 8) + blur("b2", 2) + blur("b20", 22) +
            grad("holo", [(0, "#22e6ff", .0), (.5, "#22e6ff", .5), (1, "#22e6ff", 0)], 0, 0, 1, 0))
    b = '<rect width="1600" height="900" fill="url(#sky)"/>' + stars(rng, 70, 0, 320)
    b += '<circle cx="1180" cy="250" r="110" fill="#ff7aa8" opacity=".35" filter="url(#b20)"/><circle cx="1180" cy="250" r="64" fill="#ffd1e0" opacity=".85"/>'
    b += buildings(rng, 640, -20, 1620, 160, 360, 60, 120, "#1a0b3d", ["#ff4fa3", "#26e0ff", "#ffd45c"], .18)
    b += buildings(rng, 700, -20, 1620, 220, 470, 70, 150, "#10072b", ["#ff4fa3", "#26e0ff", "#ffd45c", "#b69cff"], .3, (2, 12))
    # neon signs
    for (x, y, w, h, c) in [(300, 390, 120, 46, "#ff2f92"), (760, 340, 40, 150, "#22e6ff"), (1010, 420, 160, 54, "#ffd45c"), (1330, 350, 100, 40, "#8c6bff")]:
        b += ('<rect x="%d" y="%d" width="%d" height="%d" rx="6" fill="none" stroke="%s" stroke-width="5" filter="url(#b8)"/>'
              '<rect x="%d" y="%d" width="%d" height="%d" rx="6" fill="none" stroke="%s" stroke-width="2.5"/>' % (x, y, w, h, c, x, y, w, h, c))
    # hologram ring
    b += '<ellipse cx="560" cy="360" rx="130" ry="34" fill="none" stroke="#22e6ff" stroke-width="3" opacity=".8" filter="url(#b2)"/>'
    b += '<ellipse cx="560" cy="330" rx="100" ry="26" fill="none" stroke="#22e6ff" stroke-width="2" opacity=".6"/>'
    b += '<ellipse cx="560" cy="300" rx="70" ry="18" fill="none" stroke="#ff4fa3" stroke-width="2" opacity=".7"/>'
    b += '<rect x="0" y="760" width="1600" height="140" fill="#08041a"/>'
    # rooftop: fence + water tank
    b += '<rect x="0" y="720" width="1600" height="16" fill="#120a2a"/><rect x="0" y="736" width="1600" height="164" fill="#0a0620"/>'
    for x in range(0, 1600, 40):
        b += '<line x1="%d" y1="640" x2="%d" y2="736" stroke="#0a0620" stroke-width="3"/>' % (x, x)
    b += '<line x1="0" y1="660" x2="1600" y2="660" stroke="#0a0620" stroke-width="4"/><line x1="0" y1="700" x2="1600" y2="700" stroke="#0a0620" stroke-width="4"/>'
    b += '<rect x="1250" y="520" width="170" height="210" rx="10" fill="#0a0620"/><ellipse cx="1335" cy="520" rx="85" ry="16" fill="#150c34"/>'
    # puddle reflections
    b += '<ellipse cx="520" cy="830" rx="300" ry="26" fill="#ff4fa3" opacity=".25" filter="url(#b8)"/><ellipse cx="900" cy="850" rx="240" ry="20" fill="#22e6ff" opacity=".22" filter="url(#b8)"/>'
    # girl with umbrella
    b += girl(820, 800, 1.5, "#2c1763", "#1c0d45", "#ff7ab8")
    b += ('<g transform="translate(820 800) scale(1.5)"><path d="M-72 -215 Q0 -290 72 -215 Z" fill="#ff2f92"/>'
          '<path d="M-72 -215 Q0 -290 72 -215" fill="none" stroke="#ffd1e8" stroke-width="2"/><line x1="0" y1="-218" x2="0" y2="-118" stroke="#ffd1e8" stroke-width="2.5"/></g>')
    # rain
    for _ in range(260):
        x, y = rng.uniform(-100, 1650), rng.uniform(-40, 900)
        b += '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#bfe9ff" stroke-width="%s" opacity="%s"/>' % (
            f(x), f(y), f(x - 14), f(y + 46), f(rng.uniform(.8, 1.8)), f(rng.uniform(.12, .38)))
    return svg("Rain Over Neon Row", "A rainy cyberpunk-style rooftop at night with neon signs and a figure under an umbrella.", b, defs)


def sakura_station():
    rng = random.Random(23)
    defs = (grad("sky", [(0, "#6f8fe0"), (.45, "#f1c9e2"), (.8, "#ffc4a1"), (1, "#ffe0b8")]) + blur("b10", 10) + blur("b3", 3) +
            grad("sun", [(0, "#fff7dc", 1), (1, "#ffd9a8", 0)], kind="radial"))
    b = '<rect width="1600" height="900" fill="url(#sky)"/><circle cx="1050" cy="560" r="260" fill="url(#sun)"/><circle cx="1050" cy="560" r="62" fill="#fff4d6"/>'
    b += cloud(300, 180, 520, "#fff0f6", .8, filt="b10") + cloud(1260, 130, 420, "#ffe2ec", .75, filt="b10") + cloud(760, 300, 360, "#ffd8d0", .6, filt="b10")
    # distant hills and town
    b += '<path d="M0 600 Q260 520 520 590 T1100 580 T1600 560 L1600 700 L0 700 Z" fill="#b69acb" opacity=".7"/>'
    b += '<path d="M0 640 Q300 580 640 640 T1300 630 T1600 610 L1600 720 L0 720 Z" fill="#8c78b4"/>'
    b += buildings(rng, 680, 40, 1560, 30, 90, 24, 48, "#6d5a98", ["#ffe9a8"], .08, (3, 14))
    # rails in perspective
    b += '<path d="M0 900 L0 760 L1600 760 L1600 900 Z" fill="#7b6a9a"/><path d="M0 900 L0 790 L1600 790 L1600 900 Z" fill="#5e4f80"/>'
    for off in (-560, -260, 260, 560):
        b += '<line x1="%d" y1="900" x2="%d" y2="640" stroke="#3e3358" stroke-width="7"/>' % (800 + off * 1.8, 800 + off * .12)
    for i in range(10):
        y = 650 + i ** 1.7 * 5.5
        b += '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#4a3d68" stroke-width="%s"/>' % (f(800 - 30 - i * 40), f(y), f(800 + 30 + i * 40), f(y), f(1.5 + i * .8))
    # platform roof
    b += '<rect x="0" y="470" width="1600" height="22" fill="#4a3d68"/>'
    for x in (140, 560, 1000, 1440):
        b += '<rect x="%d" y="470" width="14" height="260" fill="#4a3d68"/>' % x
    # lamps
    for x in (360, 1190):
        b += '<line x1="%d" y1="520" x2="%d" y2="740" stroke="#3e3358" stroke-width="6"/><circle cx="%d" cy="516" r="12" fill="#fff0bd"/><circle cx="%d" cy="516" r="46" fill="#ffe6a8" opacity=".35" filter="url(#b10)"/>' % (x, x, x, x)
    # cherry trees
    for (tx, ty, s) in [(100, 760, 1.2), (1500, 770, 1.3), (1180, 740, .9)]:
        b += '<path d="M%d %d C%d %d %d %d %d %d" stroke="#4b3a52" stroke-width="%s" fill="none"/>' % (tx, ty, tx - 10, ty - 160 * s, tx + 30, ty - 250 * s, tx + 10, ty - 340 * s, f(18 * s))
        for _ in range(120):
            px, py = tx + rng.gauss(0, 130 * s), ty - 330 * s + rng.gauss(0, 85 * s)
            b += '<circle cx="%s" cy="%s" r="%s" fill="%s" opacity="%s"/>' % (f(px), f(py), f(rng.uniform(14, 36) * s), rng.choice(["#ffc1d6", "#ffb0cb", "#ffdbe8", "#ff9fbf"]), f(rng.uniform(.55, .95)))
    # girl on the platform
    b += girl(700, 770, 1.35, "#47345f", "#2c2038", "#ffcfe3")
    b += '<rect x="710" y="560" width="40" height="52" rx="8" fill="#e9547f"/>'
    # petals
    for _ in range(140):
        x, y = rng.uniform(0, 1600), rng.uniform(0, 900)
        b += '<ellipse cx="%s" cy="%s" rx="%s" ry="%s" transform="rotate(%d %s %s)" fill="#ffd0e0" opacity="%s"/>' % (
            f(x), f(y), f(rng.uniform(4, 8)), f(rng.uniform(2, 4)), rng.randint(0, 180), f(x), f(y), f(rng.uniform(.5, .95)))
    return svg("Petals at the Last Platform", "A quiet countryside station at dusk with cherry blossoms drifting over the tracks.", b, defs)


def moonlit_shrine():
    rng = random.Random(37)
    defs = (grad("sky", [(0, "#050a22"), (.6, "#10285a"), (1, "#2b4c85")]) + blur("b6", 6) + blur("b24", 26) + blur("b2", 2) +
            grad("moon", [(0, "#fffbe8", 1), (1, "#cfe0ff", 0)], kind="radial"))
    b = '<rect width="1600" height="900" fill="url(#sky)"/>' + stars(rng, 140, 0, 420)
    b += '<circle cx="1200" cy="230" r="300" fill="url(#moon)" opacity=".5"/><circle cx="1200" cy="230" r="96" fill="#fff7d8"/>'
    b += '<circle cx="1170" cy="210" r="14" fill="#eadfb4" opacity=".6"/><circle cx="1228" cy="262" r="20" fill="#eadfb4" opacity=".5"/><circle cx="1212" cy="190" r="9" fill="#eadfb4" opacity=".5"/>'
    b += cloud(420, 190, 480, "#45609a", .35, filt="b6") + cloud(1000, 420, 520, "#3a5590", .3, filt="b6")
    # ridges
    b += '<path d="M0 560 Q200 440 420 540 T820 520 T1250 560 T1600 500 L1600 900 L0 900 Z" fill="#0d1d44"/>'
    # cedar trees
    for x in list(range(-20, 520, 54)) + list(range(1180, 1640, 58)):
        h = rng.uniform(300, 520)
        b += '<path d="M%s %s L%s %s L%s %s Z" fill="#06102a"/>' % (f(x), 760, f(x + 34), f(760 - h), f(x + 68), 760)
    # stairs
    b += '<path d="M560 900 L1040 900 L880 540 L720 540 Z" fill="#17274f"/>'
    for i in range(9):
        y = 900 - i * 40
        half = 240 - i * 18
        b += '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#2c4274" stroke-width="3"/>' % (800 - half, y, 800 + half, y)
    # torii
    red, dark = "#d63a2e", "#8a1e18"
    b += ('<g><rect x="705" y="400" width="26" height="190" fill="%s"/><rect x="869" y="400" width="26" height="190" fill="%s"/>'
          '<rect x="690" y="440" width="220" height="16" fill="%s"/><path d="M650 392 Q800 370 950 392 L960 366 Q800 338 640 366 Z" fill="#241413"/>'
          '<rect x="660" y="392" width="280" height="14" fill="%s"/></g>' % (red, red, red, dark))
    b += '<ellipse cx="800" cy="480" rx="120" ry="90" fill="#ffb066" opacity=".12" filter="url(#b24)"/>'
    # lanterns
    for x in (610, 990):
        b += ('<g><rect x="%d" y="640" width="30" height="60" fill="#1a2750"/><rect x="%d" y="590" width="58" height="52" fill="#101c3e"/><rect x="%d" y="600" width="38" height="32" fill="#ffc46b"/>'
              '<path d="M%d 590 L%d 566 L%d 590 Z" fill="#101c3e"/><circle cx="%d" cy="616" r="52" fill="#ffc46b" opacity=".35" filter="url(#b6)"/></g>' % (x + 14, x, x + 10, x - 6, x + 29, x + 64, x + 29))
    # fox on the steps
    fx, fy = 860, 745
    b += ('<g transform="translate(%d %d) scale(1.4)" fill="#0a1228"><path d="M-30 0 Q-34 -40 -10 -58 L-14 -90 L4 -70 L16 -92 L20 -60 Q40 -40 36 0 Z"/>'
          '<path d="M30 -6 Q90 -20 96 -70 Q60 -50 34 -34 Z"/><path d="M26 -4 Q70 20 104 -16 Q72 -4 30 -22 Z"/></g>' % (fx, fy))
    b += '<path d="M%d %d l10 -6 l-2 10 Z" fill="#9fd0ff" opacity=".6"/>' % (fx + 4, fy - 118)
    # fog + fireflies
    b += '<rect x="0" y="720" width="1600" height="180" fill="#9fb8e8" opacity=".12" filter="url(#b24)"/>'
    for _ in range(46):
        x, y = rng.uniform(80, 1520), rng.uniform(380, 860)
        b += '<circle cx="%s" cy="%s" r="9" fill="#d9ff8a" opacity=".25" filter="url(#b2)"/><circle cx="%s" cy="%s" r="2.6" fill="#f6ffc2"/>' % (f(x), f(y), f(x), f(y))
    return svg("Lantern Steps", "A moonlit shrine stairway with a red torii gate, stone lanterns, fireflies and a small fox silhouette.", b, defs)


def starlight_circle():
    rng = random.Random(41)
    defs = (grad("sky", [(0, "#0b0626"), (.6, "#2b1357"), (1, "#6a2a7d")]) + blur("b4", 4) + blur("b18", 18) + blur("b40", 40) +
            grad("glow", [(0, "#ffe9a8", .9), (1, "#ff8fd1", 0)], kind="radial"))
    b = '<rect width="1600" height="900" fill="url(#sky)"/>' + stars(rng, 320, 0, 700, rmax=2.6)
    # milky way band
    b += '<g transform="rotate(-24 800 300)"><rect x="-200" y="200" width="2000" height="220" fill="#c9a8ff" opacity=".22" filter="url(#b40)"/>'
    for _ in range(300):
        b += '<circle cx="%s" cy="%s" r="%s" fill="#fff" opacity="%s"/>' % (f(rng.uniform(-100, 1700)), f(rng.gauss(300, 40)), f(rng.uniform(.4, 1.4)), f(rng.uniform(.3, .9)))
    b += '</g>'
    # magic circle
    cx, cy = 800, 330
    b += '<circle cx="%d" cy="%d" r="300" fill="url(#glow)" opacity=".55"/>' % (cx, cy)
    ring = lambda r, w, o: '<circle cx="%d" cy="%d" r="%d" fill="none" stroke="#ffe08c" stroke-width="%s" opacity="%s"/>' % (cx, cy, r, w, o)
    b += '<g filter="url(#b4)">' + ring(250, 5, .9) + ring(226, 2.5, .8) + ring(150, 3, .8) + '</g>' + ring(250, 2, 1) + ring(226, 1.2, 1) + ring(150, 1.5, 1)
    for k in range(48):
        a = k * math.tau / 48
        r1, r2 = 226, 250
        b += '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#ffe08c" stroke-width="2"/>' % (f(cx + r1 * math.cos(a)), f(cy + r1 * math.sin(a)), f(cx + r2 * math.cos(a)), f(cy + r2 * math.sin(a)))
    pts = [(cx + 226 * math.cos(math.radians(-90 + 144 * i)), cy + 226 * math.sin(math.radians(-90 + 144 * i))) for i in range(5)]
    b += '<polygon points="%s" fill="none" stroke="#ffd1f0" stroke-width="3" filter="url(#b4)"/>' % " ".join("%s,%s" % (f(x), f(y)) for x, y in pts)
    b += '<polygon points="%s" fill="none" stroke="#fff" stroke-width="1.6"/>' % " ".join("%s,%s" % (f(x), f(y)) for x, y in pts)
    for k in range(12):
        a = k * math.tau / 12
        b += '<circle cx="%s" cy="%s" r="5" fill="#fff4c4"/>' % (f(cx + 188 * math.cos(a)), f(cy + 188 * math.sin(a)))
    # hill + girl
    b += '<path d="M0 760 Q300 640 640 720 T1260 700 T1600 740 L1600 900 L0 900 Z" fill="#150a33"/><path d="M0 820 Q400 740 900 800 T1600 790 L1600 900 L0 900 Z" fill="#0d0624"/>'
    b += girl(800, 760, 1.6, "#1b0d3d", "#24104a", "#ffd1f0",
              '<path d="M18 -150 L52 -236" stroke="#1b0d3d" stroke-width="5"/><circle cx="55" cy="-244" r="11" fill="#ffe9a8"/><circle cx="55" cy="-244" r="30" fill="#ffe9a8" opacity=".4" filter="url(#b4)"/>'
              '<path d="M-14 -150 Q-110 -120 -150 -60 Q-90 -100 -10 -110 Z" fill="#ff7fc8" opacity=".9"/>')
    for _ in range(46):
        b += sparkle(rng.uniform(100, 1500), rng.uniform(80, 700), rng.uniform(6, 20), rng.choice(["#fff", "#ffe9a8", "#ffd1f0"]), f(rng.uniform(.5, 1)))
    return svg("Starlight Circle", "A silhouetted girl with a wand beneath a glowing golden magic circle and the Milky Way.", b, defs)


def steel_guardian_dawn():
    rng = random.Random(53)
    defs = (grad("sky", [(0, "#243b6b"), (.45, "#ec8a6a"), (.8, "#ffd08a"), (1, "#ffe8b8")]) + blur("b14", 14) + blur("b3", 3) +
            grad("sun", [(0, "#fffbe8", 1), (.4, "#ffe2a0", .6), (1, "#ffb870", 0)], kind="radial"))
    b = '<rect width="1600" height="900" fill="url(#sky)"/><circle cx="800" cy="430" r="420" fill="url(#sun)"/><circle cx="800" cy="430" r="90" fill="#fffbe8"/>'
    b += cloud(260, 220, 560, "#ffb59a", .55, filt="b14") + cloud(1340, 300, 520, "#ff9f86", .5, filt="b14")
    b += '<path d="M0 560 L180 430 L330 520 L520 400 L700 540 L1000 500 L1180 380 L1400 520 L1600 440 L1600 900 L0 900 Z" fill="#5a4a78" opacity=".75"/>'
    b += '<path d="M0 640 L240 540 L420 610 L640 520 L900 620 L1200 540 L1440 620 L1600 580 L1600 900 L0 900 Z" fill="#3b3560"/>'
    b += '<rect x="0" y="640" width="1600" height="260" fill="#ffd9a6" opacity=".18" filter="url(#b14)"/>'
    # mecha silhouette (polygons)
    c = "#1b1630"
    m = ('<g fill="%s">'
         '<polygon points="760,150 800,96 840,150 828,196 772,196"/><polygon points="800,92 810,40 790,40"/>'  # head + crest
         '<polygon points="730,170 700,120 760,160"/><polygon points="870,170 900,120 840,160"/>'
         '<polygon points="690,214 910,214 960,262 940,330 860,350 740,350 660,330 640,262"/>'  # shoulders+chest
         '<polygon points="650,270 560,300 540,430 610,446 650,380"/><polygon points="950,270 1040,300 1060,430 990,446 950,380"/>'  # arms
         '<polygon points="540,430 500,560 560,566 610,446"/><polygon points="1060,430 1100,560 1040,566 990,446"/>'
         '<polygon points="740,350 860,350 880,430 720,430"/>'  # waist
         '<polygon points="700,430 900,430 920,470 680,470"/>'
         '<polygon points="690,470 780,470 770,640 700,660 670,560"/><polygon points="910,470 820,470 830,640 900,660 930,560"/>'  # legs
         '<polygon points="640,660 790,640 800,690 620,700"/><polygon points="960,660 810,640 800,690 980,700"/>'  # feet
         '</g>' % c)
    m += '<polygon points="780,128 820,128 812,144 788,144" fill="#7be0ff"/><rect x="772" y="236" width="56" height="10" fill="#ff8a5c"/>'
    m += '<polyline points="690,214 910,214" stroke="#ffcf94" stroke-width="3" opacity=".8" fill="none"/>'
    b += '<g transform="translate(0 150)">' + m + '</g>'
    b += '<rect x="0" y="780" width="1600" height="120" fill="#17122c"/>'
    for _ in range(80):
        x = rng.uniform(0, 1600)
        b += '<path d="M%s 800 q4 -%s 8 0" stroke="#2d2548" stroke-width="2" fill="none"/>' % (f(x), f(rng.uniform(14, 36)))
    for _ in range(14):
        x, y = rng.uniform(160, 1440), rng.uniform(170, 330)
        b += '<path d="M%s %s q8 -8 16 0 q8 -8 16 0" stroke="#2a2040" stroke-width="2.6" fill="none"/>' % (f(x), f(y))
    return svg("Dawn Guardian", "A giant robot silhouette standing in a misty field in front of a rising sun.", b, defs)


def lighthouse_summer():
    rng = random.Random(67)
    defs = (grad("sky", [(0, "#2f86e8"), (.55, "#8fd0ff"), (1, "#e7f7ff")]) + grad("sea", [(0, "#2aa3d6"), (1, "#0d5f9e")]) +
            blur("b8", 8) + blur("b2", 2))
    b = '<rect width="1600" height="900" fill="url(#sky)"/>'
    b += cloud(300, 250, 700, "#ffffff", .95, 160) + cloud(1200, 180, 640, "#ffffff", .92, 150) + cloud(820, 380, 420, "#eaf6ff", .85, 100)
    b += cloud(1380, 420, 520, "#ffffff", .9, 120)
    b += '<rect x="0" y="560" width="1600" height="340" fill="url(#sea)"/>'
    for _ in range(190):
        x, y = rng.uniform(0, 1600), rng.uniform(570, 760)
        b += '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#e6fbff" stroke-width="%s" opacity="%s"/>' % (f(x), f(y), f(x + rng.uniform(10, 46)), f(y), f(rng.uniform(1, 3)), f(rng.uniform(.25, .8)))
    b += '<rect x="0" y="548" width="1600" height="16" fill="#ffffff" opacity=".35"/>'
    # cliff
    b += '<path d="M0 640 Q300 600 600 650 Q800 690 760 900 L0 900 Z" fill="#2d6f3f"/><path d="M0 700 Q300 680 560 730 Q700 770 640 900 L0 900 Z" fill="#245c34"/>'
    b += '<path d="M600 650 Q820 700 780 900 L640 900 Q700 760 600 650 Z" fill="#6b5a50"/>'
    # lighthouse
    lx, ly = 330, 600
    b += '<polygon points="%d,%d %d,%d %d,%d %d,%d" fill="#fff"/>' % (lx - 52, ly, lx + 52, ly, lx + 34, ly - 330, lx - 34, ly - 330)
    for i, y in enumerate((ly - 80, ly - 190)):
        b += '<polygon points="%d,%d %d,%d %d,%d %d,%d" fill="#e5483d"/>' % (lx - 44 + i * 6, y, lx + 44 - i * 6, y, lx + 40 - i * 6, y - 56, lx - 40 + i * 6, y - 56)
    b += '<rect x="%d" y="%d" width="92" height="12" fill="#2e3848"/><rect x="%d" y="%d" width="52" height="46" fill="#ffe99a"/><polygon points="%d,%d %d,%d %d,%d" fill="#e5483d"/>' % (lx - 46, ly - 342, lx - 26, ly - 388, lx - 38, ly - 388, lx, ly - 428, lx + 38, ly - 388)
    b += '<circle cx="%d" cy="%d" r="90" fill="#fff7c4" opacity=".5" filter="url(#b8)"/>' % (lx, ly - 366)
    # sunflowers
    for _ in range(24):
        x, y = rng.uniform(20, 560), rng.uniform(690, 880)
        s = rng.uniform(.8, 1.5)
        b += '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#2f7a2d" stroke-width="4"/>' % (f(x), f(y), f(x), f(y + 60 * s))
        for k in range(12):
            a = k * math.tau / 12
            b += '<ellipse cx="%s" cy="%s" rx="%s" ry="%s" transform="rotate(%s %s %s)" fill="#ffd21f"/>' % (f(x + 16 * s * math.cos(a)), f(y + 16 * s * math.sin(a)), f(11 * s), f(5 * s), f(math.degrees(a)), f(x + 16 * s * math.cos(a)), f(y + 16 * s * math.sin(a)))
        b += '<circle cx="%s" cy="%s" r="%s" fill="#6b3d17"/>' % (f(x), f(y), f(9 * s))
    # girl in straw hat with bicycle
    gx, gy = 1010, 880
    b += '<polygon points="840,790 1600,790 1600,900 800,900" fill="#b98a5c"/><polygon points="840,790 1600,790 1600,806 836,806" fill="#d9ad7a"/>'
    for px in range(860, 1600, 70):
        b += '<line x1="%d" y1="806" x2="%d" y2="900" stroke="#8a6340" stroke-width="3"/>' % (px, px - 22)
    b += girl(gx, gy, 1.4, "#fff6ea", "#5a3b2c", "#fff")
    b += '<ellipse cx="%d" cy="%d" rx="46" ry="10" fill="#f1cf7c"/><path d="M%d %d Q%d %d %d %d Z" fill="#f1cf7c"/>' % (gx, gy - 244, gx - 24, gy - 246, gx, gy - 286, gx + 24, gy - 246)
    b += '<path d="M%d %d L%d %d" stroke="#d94a4a" stroke-width="5"/>' % (gx - 24, gy - 250, gx + 24, gy - 250)
    b += '<g stroke="#2e3848" stroke-width="5" fill="none"><circle cx="1200" cy="835" r="46"/><circle cx="1340" cy="835" r="46"/><path d="M1200 835 L1260 770 L1340 835 M1260 770 L1292 770 M1290 760 L1320 760 L1340 835 M1200 835 L1262 835 L1290 770"/></g>'
    for _ in range(12):
        b += '<circle cx="%s" cy="%s" r="3" fill="#fff" opacity=".7"/>' % (f(rng.uniform(0, 1600)), f(rng.uniform(100, 540)))
    for _ in range(5):
        x, y = rng.uniform(900, 1500), rng.uniform(200, 440)
        b += '<path d="M%s %s q9 -10 18 0 q9 -10 18 0" stroke="#34506c" stroke-width="3" fill="none"/>' % (f(x), f(y))
    return svg("Long Summer Afternoon", "A bright seaside cliff with a striped lighthouse, sunflowers, towering clouds and a girl in a straw hat.", b, defs)


def floating_isles():
    rng = random.Random(79)
    defs = (grad("sky", [(0, "#6fc3ff"), (.55, "#c9ecff"), (1, "#ffe9d6")]) + blur("b10", 10) + blur("b3", 3) +
            grad("rock", [(0, "#8d7a6a"), (1, "#4e4444")]) + grad("water", [(0, "#d9f6ff", .95), (1, "#9fdcff", .2)]))
    b = '<rect width="1600" height="900" fill="url(#sky)"/>'
    b += cloud(280, 700, 700, "#ffffff", .9, 150, "b3") + cloud(1300, 760, 760, "#fff4ea", .9, 160, "b3") + cloud(760, 840, 800, "#ffffff", .95, 160, "b3")
    b += cloud(1000, 120, 500, "#ffffff", .7, 100, "b10")

    def isle(cx, cy, w, h, falls=False, castle=False, trees=6):
        s = ('<path d="M%s %s Q%s %s %s %s L%s %s Q%s %s %s %s Z" fill="url(#rock)"/>' % (
            f(cx - w / 2), f(cy), f(cx - w * .4), f(cy + h * .6), f(cx), f(cy + h), f(cx + w * .1), f(cy + h * .5),
            f(cx + w * .35), f(cy + h * .5), f(cx + w / 2), f(cy)))
        s += '<path d="M%s %s Q%s %s %s %s Q%s %s %s %s Z" fill="#59b24f"/>' % (f(cx - w / 2), f(cy), f(cx), f(cy - h * .32), f(cx + w / 2), f(cy), f(cx), f(cy + h * .12), f(cx - w / 2), f(cy))
        if falls:
            s += '<rect x="%s" y="%s" width="%s" height="%s" fill="url(#water)"/>' % (f(cx - w * .12), f(cy + h * .05), f(w * .07), f(h * 1.4))
            s += '<ellipse cx="%s" cy="%s" rx="%s" ry="10" fill="#fff" opacity=".7" filter="url(#b3)"/>' % (f(cx - w * .085), f(cy + h * 1.45), f(w * .08))
        for _ in range(trees):
            tx = cx + rng.uniform(-w * .38, w * .38)
            s += '<rect x="%s" y="%s" width="5" height="14" fill="#5b3a28"/><circle cx="%s" cy="%s" r="%s" fill="%s"/>' % (f(tx), f(cy - 10), f(tx + 2.5), f(cy - 18), f(rng.uniform(10, 18)), rng.choice(["#2f8f46", "#3ca255", "#4bb764"]))
        if castle:
            kx = cx + w * .1
            s += ('<g><rect x="%s" y="%s" width="70" height="60" fill="#f4eee4"/><rect x="%s" y="%s" width="26" height="100" fill="#f4eee4"/>'
                  '<polygon points="%s,%s %s,%s %s,%s" fill="#d6564c"/><polygon points="%s,%s %s,%s %s,%s" fill="#d6564c"/>'
                  '<rect x="%s" y="%s" width="12" height="20" fill="#7a5a50"/></g>' % (
                      f(kx - 35), f(cy - 70), f(kx + 35), f(cy - 110), f(kx - 40), f(cy - 70), f(kx), f(cy - 112), f(kx + 40), f(cy - 70),
                      f(kx + 30), f(cy - 110), f(kx + 48), f(cy - 148), f(kx + 66), f(cy - 110), f(kx - 6), f(cy - 30)))
        return s
    b += isle(1220, 260, 230, 120, trees=5) + isle(360, 330, 300, 170, falls=True, trees=8)
    b += isle(820, 470, 520, 250, castle=True, trees=10)
    # airship
    ax, ay = 1100, 520
    b += ('<g transform="translate(%d %d)"><ellipse cx="0" cy="0" rx="120" ry="52" fill="#e0574c"/><path d="M-120 0 Q0 -20 120 0" stroke="#fff" stroke-width="5" fill="none"/>'
          '<path d="M-90 40 L90 40 L70 72 L-70 72 Z" fill="#7a5238"/><line x1="-60" y1="44" x2="-50" y2="30" stroke="#333"/><line x1="60" y1="44" x2="50" y2="30" stroke="#333"/>'
          '<polygon points="120,0 160,-26 160,26" fill="#f2b84b"/><rect x="-24" y="48" width="48" height="12" fill="#ffe0a0"/></g>' % (ax, ay))
    for _ in range(9):
        x, y = rng.uniform(100, 1500), rng.uniform(100, 640)
        b += '<path d="M%s %s q8 -9 16 0 q8 -9 16 0" stroke="#4a5f82" stroke-width="2.6" fill="none"/>' % (f(x), f(y))
    for _ in range(16):
        b += sparkle(rng.uniform(40, 1560), rng.uniform(40, 700), rng.uniform(5, 12), "#fff", f(rng.uniform(.5, .9)))
    return svg("Skybound Crossing", "Floating islands with a waterfall and a small castle, and an airship drifting through pastel clouds.", b, defs)


def classroom_sunset():
    rng = random.Random(83)
    defs = (grad("wall", [(0, "#f3c799"), (1, "#d68e6a")]) + grad("floor", [(0, "#b0693e"), (1, "#6e3b26")]) +
            grad("glow", [(0, "#ffe9b0", .85), (1, "#ffb070", 0)], 0, 0, 1, 1) + blur("b6", 6) + blur("b20", 20) +
            grad("sky", [(0, "#ff9a5f"), (.5, "#ffc98a"), (1, "#ffe7b3")]))
    b = '<rect width="1600" height="900" fill="url(#wall)"/><rect x="0" y="600" width="1600" height="300" fill="url(#floor)"/>'
    for i in range(0, 1601, 80):
        b += '<line x1="%d" y1="600" x2="%d" y2="900" stroke="#4e2a1c" stroke-width="2" opacity=".5"/>' % (800 + (i - 800) * .75, i * 1.0 + (i - 800) * .6)
    for k in range(5):
        y = 600 + k ** 1.8 * 20
        b += '<line x1="0" y1="%s" x2="1600" y2="%s" stroke="#4e2a1c" stroke-width="2" opacity=".4"/>' % (f(y), f(y))
    # windows on the left wall
    for i in range(3):
        x = 60 + i * 380
        b += ('<g><rect x="%d" y="110" width="330" height="400" fill="url(#sky)"/>' % x)
        b += '<circle cx="%d" cy="360" r="64" fill="#fff4d0" opacity=".95"/>' % (x + 220)
        b += '<path d="M%d 510 L%d 440 L%d 470 L%d 410 L%d 480 L%d 510 Z" fill="#a85a47" opacity=".8"/>' % (x, x + 70, x + 120, x + 185, x + 265, x + 330)
        b += '<rect x="%d" y="110" width="330" height="400" fill="none" stroke="#6b3f2c" stroke-width="12"/><line x1="%d" y1="110" x2="%d" y2="510" stroke="#6b3f2c" stroke-width="8"/><line x1="%d" y1="310" x2="%d" y2="310" stroke="#6b3f2c" stroke-width="8"/></g>' % (x, x + 165, x + 165, x, x + 330)
        # light shaft on floor
        b += '<polygon points="%d,510 %d,510 %d,900 %d,900" fill="#ffe0a0" opacity=".26" filter="url(#b6)"/>' % (x, x + 330, x + 120 + 700, x + 700 - 240)
    # blackboard
    b += '<rect x="1210" y="150" width="340" height="230" fill="#2f4a3f" stroke="#7a5a3a" stroke-width="14"/>'
    b += '<path d="M1245 210 q40 -20 80 0 t90 0" stroke="#e9f0e4" stroke-width="3" fill="none" opacity=".8"/><text x="1240" y="290" font-family="sans-serif" font-size="30" fill="#e9f0e4" opacity=".85">See you tomorrow!</text>'
    b += '<path d="M1245 335 l60 0 M1325 335 l40 0" stroke="#e9f0e4" stroke-width="3" opacity=".6"/>'
    # desks in perspective rows
    for row, (y, s) in enumerate([(640, .8), (720, 1.0), (820, 1.3)]):
        for col in range(5):
            x = 180 + col * 300 * s + (row * 40)
            if x > 1500:
                continue
            b += ('<g transform="translate(%s %s) scale(%s)"><rect x="-70" y="-60" width="140" height="12" fill="#a8744b"/><rect x="-66" y="-48" width="6" height="52" fill="#4f3a30"/>'
                  '<rect x="60" y="-48" width="6" height="52" fill="#4f3a30"/><rect x="-44" y="-20" width="88" height="8" fill="#6f4b36"/>'
                  '<rect x="-40" y="-120" width="80" height="48" fill="#8f5f3f"/><rect x="-36" y="-72" width="6" height="76" fill="#4f3a30"/></g>' % (f(x), f(y), s))
    # girl at the window desk (back view, sitting)
    b += '<g transform="translate(505 760) scale(1.7)"><rect x="-70" y="-60" width="140" height="12" fill="#b88458"/><rect x="-66" y="-48" width="6" height="52" fill="#4f3a30"/><rect x="60" y="-48" width="6" height="52" fill="#4f3a30"/>'
    b += '<path d="M-22 -140 Q-26 -100 -16 -78 L16 -78 Q26 -100 22 -140 Z" fill="#2f3f78"/><ellipse cx="0" cy="-160" rx="17" ry="20" fill="#2a1a22"/><path d="M-20 -166 Q-24 -120 -14 -92 Q0 -84 14 -92 Q24 -120 20 -166 Q0 -184 -20 -166 Z" fill="#2a1a22"/>'
    b += '<path d="M10 -176 q26 -12 20 18" stroke="#ff6b8a" stroke-width="5" fill="none"/></g>'
    # dust motes
    for _ in range(90):
        b += '<circle cx="%s" cy="%s" r="%s" fill="#fff6d6" opacity="%s"/>' % (f(rng.uniform(40, 1560)), f(rng.uniform(120, 760)), f(rng.uniform(1, 3.2)), f(rng.uniform(.2, .8)))
    b += '<rect width="1600" height="900" fill="url(#glow)" opacity=".28"/>'
    return svg("After the Last Bell", "An empty classroom at sunset with long window light, rows of desks and one student staying behind.", b, defs)


SCENES = {
    "neon-rooftop-rain": neon_rooftop_rain, "sakura-station": sakura_station, "moonlit-shrine": moonlit_shrine,
    "starlight-circle": starlight_circle, "steel-guardian-dawn": steel_guardian_dawn,
    "lighthouse-summer": lighthouse_summer, "floating-isles": floating_isles, "classroom-sunset": classroom_sunset,
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in SCENES.items():
        data = fn()
        (OUT / (name + ".svg")).write_text(data, encoding="utf-8")
        print("wrote %s (%d KB)" % (name, len(data) // 1024), file=sys.stderr)


if __name__ == "__main__":
    main()
