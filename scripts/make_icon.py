"""Generate the J.A.R.V.I.S. application / tray icon.

Run with the project runtime:
    .\\runtime\\python.exe scripts\\make_icon.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SIZE = 1024
SCALE = 2  # supersample for smooth edges


def build() -> Image.Image:
    canvas = SIZE * SCALE
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    center = canvas / 2
    unit = canvas / 1024

    def circle(radius: float, outline=None, fill=None, width: float = 1) -> None:
        r = radius * unit
        draw.ellipse(
            (center - r, center - r, center + r, center + r),
            outline=outline,
            fill=fill,
            width=max(1, int(width * unit)),
        )

    # Dark glass disc with a soft cyan rim.
    circle(492, fill=(2, 8, 13, 255), outline=(6, 22, 30, 255), width=8)
    for radius, alpha, width in ((492, 190, 5), (470, 80, 2)):
        circle(radius, outline=(111, 232, 255, alpha), width=width)

    # Outer tick ring.
    tick_count = 36
    for index in range(tick_count):
        angle = (index / tick_count) * math.tau
        inner = 424
        outer = 448 if index % 3 == 0 else 438
        x1 = center + math.cos(angle) * inner * unit
        y1 = center + math.sin(angle) * inner * unit
        x2 = center + math.cos(angle) * outer * unit
        y2 = center + math.sin(angle) * outer * unit
        draw.line(
            (x1, y1, x2, y2),
            fill=(111, 232, 255, 210 if index % 3 == 0 else 120),
            width=max(1, int((6 if index % 3 == 0 else 3) * unit)),
        )

    # Offset arcs: reactor stator rings.
    for start, end, radius, color, width in (
        (-38, 128, 372, (255, 199, 107, 235), 10),
        (146, 320, 372, (255, 199, 107, 90), 5),
        (52, 218, 330, (111, 232, 255, 190), 6),
        (232, 388, 330, (111, 232, 255, 90), 3),
        (0, 360, 284, (60, 180, 205, 160), 4),
    ):
        r = radius * unit
        draw.arc(
            (center - r, center - r, center + r, center + r),
            start=start,
            end=end,
            fill=color,
            width=max(1, int(width * unit)),
        )

    # Hexagonal coil housing.
    hexagon = []
    for index in range(6):
        angle = math.radians(60 * index - 30)
        hexagon.append((center + math.cos(angle) * 246 * unit, center + math.sin(angle) * 246 * unit))
    draw.line(hexagon + [hexagon[0]], fill=(111, 232, 255, 110), width=max(1, int(3 * unit)))

    # Core glow.
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for radius, alpha in ((190, 35), (150, 75), (112, 150)):
        r = radius * unit
        glow_draw.ellipse(
            (center - r, center - r, center + r, center + r),
            fill=(100, 228, 255, alpha),
        )
    glow = glow.filter(ImageFilter.GaussianBlur(26 * unit))
    image = Image.alpha_composite(image, glow)
    draw = ImageDraw.Draw(image)

    # Gold inner seal and white-hot core.
    circle(150, outline=(255, 199, 107, 220), width=4)
    circle(132, outline=(255, 199, 107, 110), width=2)
    circle(96, fill=(170, 245, 255, 255), outline=(240, 255, 255, 255), width=3)
    circle(56, fill=(245, 255, 255, 255))
    circle(22, fill=(255, 255, 255, 255))

    # Four cardinal prongs.
    for angle in (0, 90, 180, 270):
        radians = math.radians(angle)
        x1 = center + math.cos(radians) * 190 * unit
        y1 = center + math.sin(radians) * 190 * unit
        x2 = center + math.cos(radians) * 252 * unit
        y2 = center + math.sin(radians) * 252 * unit
        draw.line(
            (x1, y1, x2, y2),
            fill=(255, 199, 107, 230),
            width=max(1, int(8 * unit)),
        )

    return image.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    icon = build()
    icon.save(ASSETS / "jarvis.png")
    icon.save(
        ASSETS / "jarvis.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Wrote {ASSETS / 'jarvis.ico'} and {ASSETS / 'jarvis.png'}")


if __name__ == "__main__":
    main()
