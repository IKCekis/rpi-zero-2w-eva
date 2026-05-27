"""
pixel_pal.py — the robot-face library, pure Python + Pillow.

Renders the same eye/mouth/brow/decoration vocabulary as the HTML kit
into a 128×32 1-bit PIL Image. Designed to be pushed straight to a
Waveshare 2.23" OLED HAT (SSD1305) over SPI on a Raspberry Pi.

Coordinates are device pixels: x ∈ [0, 128), y ∈ [0, 32).
"""

from __future__ import annotations
from PIL import Image, ImageDraw
from dataclasses import dataclass, field
from typing import Optional
import math

# Canvas dimensions
W, H = 128, 32
ON = 255
OFF = 0


# ============================================================
# Eye shapes
# Default left eye at (32, 16), right at (96, 16). r=11 → 22-px eye.
# ============================================================

def eye_open(draw, cx, cy, r=11, look_x=0, look_y=0, **_):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ON)
    draw.ellipse((cx - r + 2, cy - r + 2, cx + r - 2, cy + r - 2), fill=OFF)
    px, py = cx + look_x, cy + look_y
    draw.ellipse((px - 3, py - 3, px + 3, py + 3), fill=ON)


def eye_dot(draw, cx, cy, look_x=0, look_y=0, **_):
    px, py = cx + look_x, cy + look_y
    draw.ellipse((px - 3, py - 3, px + 3, py + 3), fill=ON)


def eye_solid(draw, cx, cy, r=11, **_):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ON)


def eye_happy(draw, cx, cy, r=11, **_):
    bbox = (cx - r, cy - r, cx + r, cy + r)
    draw.chord(bbox, 0, 180, fill=ON)
    r2 = r - 2
    draw.chord((cx - r2, cy - r2, cx + r2, cy + r2), 0, 180, fill=OFF)


def eye_sleepy(draw, cx, cy, r=11, **_):
    baseline = cy + 2
    ry = max(2, r // 2)
    bbox = (cx - r, baseline - ry, cx + r, baseline + ry)
    draw.chord(bbox, 0, 180, fill=ON)
    r2 = r - 1
    ry2 = max(1, ry - 1)
    draw.chord((cx - r2, baseline - ry2, cx + r2, baseline + ry2), 0, 180, fill=OFF)


def eye_closed(draw, cx, cy, r=11, **_):
    draw.rectangle((cx - r, cy - 1, cx + r - 1, cy + 1 - 1), fill=ON)


def eye_wide(draw, cx, cy, r=11, look_x=0, look_y=0, **_):
    eye_open(draw, cx, cy, r=r + 2, look_x=look_x, look_y=look_y)


def eye_shocked(draw, cx, cy, r=11, look_x=0, look_y=0, **_):
    R = r + 1
    draw.ellipse((cx - R, cy - R, cx + R, cy + R), fill=ON)
    draw.ellipse((cx - R + 2, cy - R + 2, cx + R - 2, cy + R - 2), fill=OFF)
    px, py = cx + look_x, cy + look_y
    draw.ellipse((px - 1, py - 1, px + 1, py + 1), fill=ON)


def eye_heart(draw, cx, cy, r=11, **_):
    half = r
    lobe = half // 2 + 1
    draw.ellipse((cx - half + 1, cy - lobe - 1, cx - lobe + 2, cy + 1), fill=ON)
    draw.ellipse((cx + lobe - 2, cy - lobe - 1, cx + half - 1, cy + 1), fill=ON)
    draw.polygon([(cx - half + 1, cy - 1), (cx + half - 1, cy - 1), (cx, cy + half)], fill=ON)


def eye_star(draw, cx, cy, r=11, **_):
    a = r
    b = max(2, r // 3)
    pts = [
        (cx, cy - a), (cx + b, cy - b),
        (cx + a, cy), (cx + b, cy + b),
        (cx, cy + a), (cx - b, cy + b),
        (cx - a, cy), (cx - b, cy - b),
    ]
    draw.polygon(pts, fill=ON)


def eye_cross(draw, cx, cy, r=11, **_):
    draw.line((cx - r, cy - r, cx + r, cy + r), fill=ON, width=2)
    draw.line((cx - r, cy + r, cx + r, cy - r), fill=ON, width=2)


def eye_spiral(draw, cx, cy, r=11, **_):
    for ring_r in (r, r - 3, r - 6, max(1, r - 9)):
        if ring_r <= 0:
            continue
        draw.ellipse((cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r), outline=ON)


def eye_angry(draw, cx, cy, r=11, flip=False, **_):
    angle_deg = -25 if flip else 25
    a = math.radians(angle_deg)
    dx, dy = math.cos(a) * r, math.sin(a) * r
    x1, y1 = cx - dx, cy - dy
    x2, y2 = cx + dx, cy + dy
    draw.line((x1, y1, x2, y2), fill=ON, width=4)


def eye_tear(draw, cx, cy, r=11, look_x=0, look_y=0, **_):
    px, py = cx + look_x, cy + look_y
    draw.ellipse((px - 3, py - 3, px + 3, py + 3), fill=ON)
    draw.rectangle((cx - 1, cy + 4, cx, cy + 9), fill=ON)
    draw.rectangle((cx - 2, cy + 8, cx + 1, cy + 11), fill=ON)


EYES = {
    "open": eye_open, "dot": eye_dot, "solid": eye_solid,
    "happy": eye_happy, "sleepy": eye_sleepy, "closed": eye_closed,
    "wide": eye_wide, "shocked": eye_shocked,
    "heart": eye_heart, "star": eye_star,
    "cross": eye_cross, "spiral": eye_spiral,
    "angry": eye_angry, "tear": eye_tear,
}


# ============================================================
# Mouth shapes (centered at cx=64, cy=29 by default)
# ============================================================

def mouth_smile(draw, cx=64, cy=29, **_):
    pts = [(cx - 4, cy), (cx, cy + 2), (cx + 4, cy)]
    draw.line(pts, fill=ON, width=1)


def mouth_smile_wide(draw, cx=64, cy=29, **_):
    pts = [(cx - 7, cy - 1), (cx - 3, cy + 2), (cx + 3, cy + 2), (cx + 7, cy - 1)]
    draw.line(pts, fill=ON, width=1)


def mouth_smile_open(draw, cx=64, cy=29, open=0.0, **_):
    w, h = 8, 2 + round(open * 2)
    draw.rectangle((cx - w // 2, cy - 1, cx + w // 2, cy - 1 + h), fill=ON)
    draw.point((cx - w // 2 - 1, cy - 2), fill=ON)
    draw.point((cx + w // 2 + 1, cy - 2), fill=ON)


def mouth_flat(draw, cx=64, cy=29, **_):
    draw.line((cx - 4, cy, cx + 4, cy), fill=ON, width=1)


def mouth_frown(draw, cx=64, cy=29, **_):
    pts = [(cx - 5, cy + 2), (cx, cy - 1), (cx + 5, cy + 2)]
    draw.line(pts, fill=ON, width=1)


def mouth_o(draw, cx=64, cy=29, **_):
    draw.ellipse((cx - 2, cy - 1, cx + 2, cy + 3), outline=ON)


def mouth_cat(draw, cx=64, cy=29, **_):
    pts = [(cx - 4, cy), (cx - 2, cy + 2), (cx, cy), (cx + 2, cy + 2), (cx + 4, cy)]
    draw.line(pts, fill=ON, width=1)


def mouth_tongue(draw, cx=64, cy=29, **_):
    pts = [(cx - 5, cy), (cx, cy + 2), (cx + 5, cy)]
    draw.line(pts, fill=ON, width=1)
    draw.rectangle((cx + 1, cy + 1, cx + 3, cy + 2), fill=ON)


def mouth_yawn(draw, cx=64, cy=29, **_):
    draw.ellipse((cx - 4, cy - 1, cx + 4, cy + 3), outline=ON)


def mouth_zigzag(draw, cx=64, cy=29, **_):
    pts = [(cx - 6, cy), (cx - 4, cy + 1), (cx - 2, cy), (cx, cy + 1),
           (cx + 2, cy), (cx + 4, cy + 1), (cx + 6, cy)]
    draw.line(pts, fill=ON, width=1)


MOUTHS = {
    "none": None, "smile": mouth_smile, "smile-wide": mouth_smile_wide,
    "smile-open": mouth_smile_open, "flat": mouth_flat, "frown": mouth_frown,
    "o": mouth_o, "cat": mouth_cat, "tongue": mouth_tongue,
    "yawn": mouth_yawn, "zigzag": mouth_zigzag,
}


# ============================================================
# Brow shapes (above eye, default cy=3)
# ============================================================

def brow_angry(draw, cx, cy=3, flip=False, **_):
    a = math.radians(-20 if flip else 20)
    half = 6
    dx, dy = math.cos(a) * half, math.sin(a) * half
    draw.line((cx - dx, cy - dy, cx + dx, cy + dy), fill=ON, width=2)


def brow_sad(draw, cx, cy=3, flip=False, **_):
    a = math.radians(20 if flip else -20)
    half = 6
    dx, dy = math.cos(a) * half, math.sin(a) * half
    draw.line((cx - dx, cy - dy, cx + dx, cy + dy), fill=ON, width=2)


def brow_raised(draw, cx, cy=3, **_):
    draw.rectangle((cx - 5, cy - 2, cx + 4, cy - 1), fill=ON)


def brow_flat(draw, cx, cy=3, **_):
    draw.line((cx - 5, cy, cx + 5, cy), fill=ON, width=1)


def brow_worried(draw, cx, cy=3, **_):
    pts = [(cx - 5, cy + 1), (cx, cy - 1), (cx + 5, cy + 1)]
    draw.line(pts, fill=ON, width=1)


BROWS = {
    "none": None, "angry": brow_angry, "sad": brow_sad,
    "raised": brow_raised, "flat": brow_flat, "worried": brow_worried,
}


# ============================================================
# Decoration glyphs — 8×8 pixel matrices
# ============================================================

DECO_MATRICES = {
    "heart": [
        "........", ".##..##.", "########", "########",
        "########", ".######.", "..####..", "...##...",
    ],
    "heart-small": [
        "........", "........", "..#..#..", ".######.",
        ".######.", "..####..", "...##...", "........",
    ],
    "z": [
        "........", "######..", "....#...", "...#....",
        "..#.....", ".#......", "######..", "........",
    ],
    "z-small": [
        "........", "........", "####....", "...#....",
        "..#.....", ".#......", "####....", "........",
    ],
    "exclaim": [
        "........", "..##....", "..##....", "..##....",
        "..##....", "........", "..##....", "..##....",
    ],
    "question": [
        ".####...", "##..##..", "....##..", "...##...",
        "..##....", "..##....", "........", "..##....",
    ],
    "music": [
        "..####..", "..####..", "..#..#..", "..#..#..",
        "..#..#..", "###.##..", "###.###.", ".#...##.",
    ],
    "sparkle": [
        "...#....", "..###...", "#..#..#.", ".#####..",
        "..###...", ".#####..", "#..#..#.", "...#....",
    ],
    "sparkle-small": [
        "........", "...#....", "..###...", ".##.##..",
        "..###...", "...#....", "........", "........",
    ],
    "tear": [
        "...##...", "...##...", "..####..", "..####..",
        ".######.", ".######.", "..####..", "..####..",
    ],
    "sweat": [
        "........", "...##...", "...##...", "..####..",
        "..####..", "..####..", "...##...", "........",
    ],
    "cloud": [
        "........", "..####..", ".######.", "########",
        "########", ".######.", "........", "........",
    ],
    "ellipsis": [
        "........", "........", "........", "........",
        "........", "........", "##.##.##", "##.##.##",
    ],
    "wave-bye": [
        "........", ".####...", ".#..#...", ".####...",
        "..####..", "...###..", "...#....", "........",
    ],
}


def draw_decoration(image, kind, x=60, y=0):
    m = DECO_MATRICES.get(kind)
    if not m:
        return
    px = image.load()
    for yy, row in enumerate(m):
        for xx, ch in enumerate(row):
            if ch == "#":
                tx, ty = x + xx, y + yy
                if 0 <= tx < W and 0 <= ty < H:
                    px[tx, ty] = ON


# ============================================================
# Wave animation — arm oscillates right of the face.
# 12 keyframes: arm swings up / down repeatedly.
# Anchor: body center at (116, 20), arm is a 10-px line.
# ============================================================

# Arm tip Y offsets per frame (0 = center, negative = up, positive = down)
_WAVE_ARM_OFFSETS = [0, -3, -6, -9, -6, -3, 0, 3, 6, 9, 6, 3]


def draw_wave_frame(image: Image.Image, frame: int, expr_name: str = "happy") -> None:
    """Render one frame of the goodbye-wave animation.

    The pal shows its happy expression and a tiny arm waves from the right
    side of the display area.

    Parameters
    ----------
    frame : 0–11, loops through _WAVE_ARM_OFFSETS.
    """
    draw_face(image, expr_name)
    draw = ImageDraw.Draw(image)

    # Arm: shoulder fixed at (120, 20), elbow at (122, 22), tip oscillates.
    shoulder_x, shoulder_y = 120, 20
    tip_y = 14 + _WAVE_ARM_OFFSETS[frame % 12]

    # Shoulder → elbow
    draw.line((shoulder_x, shoulder_y, 122, 22), fill=ON, width=2)
    # Elbow → tip (hand)
    draw.line((122, 22, 126, tip_y), fill=ON, width=2)
    # Small dot = hand
    draw.ellipse((124, tip_y - 1, 127, tip_y + 2), fill=ON)


# ============================================================
# Music animation — Eva bobs up/down, notes float right-side.
# Right of right eye (x≥108) is clear for notes/screen.
# ============================================================

_MUSIC_BOB = [0, 0, -1, -1, -2, -2, -1, -1, 0, 0, 1, 1, 1, 1, 0, 0]
_MUSIC_NOTE_SPECS = [(109, 0), (119, 10)]  # (x_anchor, phase_offset)


def draw_music_frame(image: Image.Image, frame: int) -> None:
    """Render one frame of the music-listening animation (looping).

    Eva sings and bobs while two quarter-notes float upward on the right.
    frame: any int, loops internally.
    """
    cy_offset = _MUSIC_BOB[frame % 16]
    draw_face(image, "singing", cy=16 + cy_offset)

    draw = ImageDraw.Draw(image)
    for nx, phase in _MUSIC_NOTE_SPECS:
        # Note scrolls from y=22 up to y=2 over 20 frames
        note_y = 22 - ((frame + phase) % 20)
        if 2 <= note_y <= 22:
            draw.ellipse((nx, note_y + 4, nx + 3, note_y + 6), fill=ON)   # head
            draw.line((nx + 3, note_y, nx + 3, note_y + 5), fill=ON, width=1)  # stem
            draw.line((nx + 3, note_y, nx + 5, note_y + 2), fill=ON, width=1)  # flag


# ============================================================
# Video animation — Eva watches a tiny TV on the right.
# ============================================================

_VIDEO_BOB = [0, 0, 0, 0, -1, -1, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0]


def draw_video_frame(image: Image.Image, frame: int) -> None:
    """Render one frame of the video/cinema animation.

    Eva looks right toward a tiny animated TV screen.
    frame: any int, loops internally.
    """
    # Expression classes resolved at call-time so forward refs are fine.
    phase = frame % 40
    if phase < 3:
        expr = "excited"
    elif phase < 6:
        expr = "happy"
    else:
        # Open eyes looking right + smile — created inline to avoid forward-ref
        expr = Expression(
            left_eye=EyeSpec("open", lx=2),
            right_eye=EyeSpec("open", lx=2),
            mouth=MouthSpec("smile"),
        )

    cy_offset = _VIDEO_BOB[frame % 16] // 2
    draw_face(image, expr, cy=16 + cy_offset)

    draw = ImageDraw.Draw(image)
    # Small TV screen (x=110..126, y=6..26 clears the right eye at x=85..107)
    sx1, sy1, sx2, sy2 = 110, 6, 126, 26
    draw.rectangle((sx1, sy1, sx2, sy2), outline=ON)
    scan_offset = (frame // 2) % 3
    for y in range(sy1 + 2, sy2 - 1, 3):
        if ((y - sy1) // 3 + scan_offset) % 3 == 0:
            draw.line((sx1 + 2, y, sx2 - 2, y), fill=ON, width=1)
    # Antenna
    cx_tv = (sx1 + sx2) // 2
    draw.line((cx_tv, sy1, cx_tv - 2, sy1 - 4), fill=ON, width=1)
    draw.line((cx_tv, sy1, cx_tv + 2, sy1 - 4), fill=ON, width=1)


# ============================================================
# PIN display — show pairing code on OLED
# ============================================================

def draw_pin_frame(image: Image.Image, pin: str, frame: int) -> None:
    """Pairing PIN: blinking border + label + spaced digits."""
    from PIL import ImageFont
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default(size=10)
    except TypeError:
        font = ImageFont.load_default()

    # Border blinks 15 on / 15 off
    if (frame // 15) % 2 == 0:
        draw.rectangle((0, 0, W - 1, H - 1), outline=ON)

    draw.text((4, 2), "ESLESTIR:", fill=ON, font=font)

    spaced = " ".join(pin)
    try:
        bbox = draw.textbbox((0, 0), spaced, font=font)
        tw = bbox[2] - bbox[0]
    except AttributeError:
        tw = len(spaced) * 6
    draw.text((max(2, (W - tw) // 2), 18), spaced, fill=ON, font=font)


# ============================================================
# Expression presets
# ============================================================

@dataclass
class EyeSpec:
    shape: str = "open"
    look_x: int = 0
    look_y: int = 0


@dataclass
class MouthSpec:
    shape: str = "none"
    open: float = 0.0


@dataclass
class BrowSpec:
    shape: str = "none"


@dataclass
class DecorationSpec:
    kind: str
    x: int = 60
    y: int = 0


@dataclass
class Expression:
    left_eye: EyeSpec = field(default_factory=lambda: EyeSpec("open"))
    right_eye: EyeSpec = field(default_factory=lambda: EyeSpec("open"))
    mouth: MouthSpec = field(default_factory=lambda: MouthSpec("none"))
    left_brow: BrowSpec = field(default_factory=lambda: BrowSpec("none"))
    right_brow: BrowSpec = field(default_factory=lambda: BrowSpec("none"))
    decorations: list = field(default_factory=list)
    desc: str = ""


def _e(s, lx=0, ly=0): return EyeSpec(s, lx, ly)
def _m(s, o=0.0):      return MouthSpec(s, o)
def _b(s):             return BrowSpec(s)
def _d(k, x=60, y=0):  return DecorationSpec(k, x, y)


EXPRESSIONS = {
    "neutral":   Expression(_e("open"), _e("open"), _m("none"), desc="Looking forward."),
    "idle":      Expression(_e("open", ly=1), _e("open", ly=1), _m("flat"), desc="Chilling."),
    "happy":     Expression(_e("happy"), _e("happy"), _m("smile"), desc="Eye-arcs, soft smile."),
    "giggle":    Expression(_e("happy"), _e("happy"), _m("smile-wide"), desc="Bigger smile."),
    "excited":   Expression(_e("star"), _e("star"), _m("smile-wide"),
                            decorations=[_d("sparkle-small", 8, 0), _d("sparkle-small", 116, 0)],
                            desc="Star eyes."),
    "love":      Expression(_e("heart"), _e("heart"), _m("smile"),
                            decorations=[_d("heart-small", 60, 0)],
                            desc="Heart eyes."),
    "singing":   Expression(_e("happy"), _e("happy"), _m("smile-open", 1.0),
                            decorations=[_d("music", 100, 0)],
                            desc="Open mouth, music note."),
    "wink":      Expression(_e("happy"), _e("open"), _m("smile"), desc="Cheeky."),
    "sleepy":    Expression(_e("sleepy"), _e("sleepy"), _m("none"), desc="Drowsy."),
    "sleeping":  Expression(_e("closed"), _e("closed"), _m("none"),
                            decorations=[_d("z", 96, 0)],
                            desc="Sleeping with Z."),
    "yawn":      Expression(_e("sleepy"), _e("sleepy"), _m("yawn"),
                            decorations=[_d("z-small", 100, 0)],
                            desc="Big yawn."),
    "sad":       Expression(_e("dot", ly=2), _e("dot", ly=2), _m("frown"),
                            left_brow=_b("sad"), right_brow=_b("sad"),
                            desc="Quiet sad."),
    "cry":       Expression(_e("tear"), _e("tear"), _m("frown"),
                            left_brow=_b("sad"), right_brow=_b("sad"),
                            desc="Crying."),
    "angry":     Expression(_e("angry"), _e("angry"), _m("frown"), desc="Mad."),
    "mad":       Expression(_e("solid"), _e("solid"), _m("frown"),
                            left_brow=_b("angry"), right_brow=_b("angry"),
                            decorations=[_d("exclaim", 60, 0)],
                            desc="Furious."),
    "surprised": Expression(_e("wide"), _e("wide"), _m("o"),
                            left_brow=_b("raised"), right_brow=_b("raised"),
                            decorations=[_d("exclaim", 60, 0)],
                            desc="Wide open!"),
    "shocked":   Expression(_e("shocked"), _e("shocked"), _m("o"), desc="Tiny pupils."),
    "curious":   Expression(_e("open", lx=2), _e("open", lx=2), _m("flat"),
                            decorations=[_d("question", 100, 0)],
                            desc="Sideways with ?"),
    "dizzy":     Expression(_e("spiral"), _e("spiral"), _m("zigzag"), desc="Spinning."),
    "dead":      Expression(_e("cross"), _e("cross"), _m("flat"), desc="X eyes."),
    "bored":     Expression(_e("sleepy", ly=2), _e("sleepy", ly=2), _m("flat"),
                            decorations=[_d("ellipsis", 60, 0)],
                            desc="Slow blink."),
    "hungry":    Expression(_e("dot", ly=1), _e("dot", ly=1), _m("smile-open", 0.5),
                            decorations=[_d("sweat", 24, 0)],
                            desc="Looking at food."),
    "silly":     Expression(_e("happy"), _e("open"), _m("tongue"), desc="Wink + tongue."),
    "smug":      Expression(_e("sleepy"), _e("sleepy"), _m("cat"), desc="Cat smile."),
    "suspicious":Expression(_e("sleepy", lx=2), _e("sleepy", lx=2), _m("flat"),
                            desc="Narrowed sideways."),
}


# ============================================================
# Face composition + blink overlay
# ============================================================

def draw_face(image: Image.Image, expr_name_or_obj,
              left_cx: int = 32, right_cx: int = 96,
              cy: int = 16, r: int = 11,
              blink: float = 0.0,
              global_look=(0, 0)) -> None:
    expr = EXPRESSIONS[expr_name_or_obj] if isinstance(expr_name_or_obj, str) else expr_name_or_obj
    draw = ImageDraw.Draw(image)

    def resolve(e: EyeSpec, fallback):
        lx = e.look_x if e.look_x else fallback[0]
        ly = e.look_y if e.look_y else fallback[1]
        return lx, ly

    l_lx, l_ly = resolve(expr.left_eye, global_look)
    r_lx, r_ly = resolve(expr.right_eye, global_look)

    def draw_eye(side, cx, eye_spec, flip):
        shape = eye_spec.shape
        if blink > 0.85 and shape != "closed":
            shape = "closed"
        fn = EYES.get(shape, eye_open)
        kwargs = dict(cx=cx, cy=cy, r=r, flip=flip)
        if shape in ("open", "dot", "wide", "shocked", "tear"):
            kwargs["look_x"], kwargs["look_y"] = (l_lx, l_ly) if side == "left" else (r_lx, r_ly)
        fn(draw, **kwargs)

    draw_eye("left", left_cx, expr.left_eye, flip=False)
    draw_eye("right", right_cx, expr.right_eye, flip=True)

    if expr.left_brow.shape != "none":
        BROWS[expr.left_brow.shape](draw, cx=left_cx, flip=False)
    if expr.right_brow.shape != "none":
        BROWS[expr.right_brow.shape](draw, cx=right_cx, flip=True)

    if expr.mouth.shape != "none":
        fn = MOUTHS[expr.mouth.shape]
        kwargs = dict(cx=(left_cx + right_cx) // 2, cy=29)
        if expr.mouth.shape == "smile-open":
            kwargs["open"] = expr.mouth.open
        fn(draw, **kwargs)

    for dspec in expr.decorations:
        draw_decoration(image, dspec.kind, dspec.x, dspec.y)


def blank_canvas() -> Image.Image:
    return Image.new("1", (W, H), OFF)


# ============================================================
# CLI: python pixel_pal.py happy out.png
# ============================================================

if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "happy"
    out = sys.argv[2] if len(sys.argv) > 2 else f"{name}.png"
    img = blank_canvas()
    draw_face(img, name)
    img.resize((W * 8, H * 8), Image.NEAREST).save(out)
    print(f"Saved {out} ({name})")
