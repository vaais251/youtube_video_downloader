"""Generate packaging/app.ico — a download-themed app icon.

Run with:  uv run --with pillow python packaging/make_icon.py

Draws a red rounded tile with a white "download" glyph (down arrow into a tray)
and saves a multi-resolution .ico (16/32/48/64/128/256).
"""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
RED = (229, 57, 53, 255)        # #e53935
RED_DARK = (198, 40, 40, 255)   # subtle bottom shade
WHITE = (255, 255, 255, 255)


def render(size: int = SIZE) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def px(v: float) -> float:
        return v / 256 * s

    # rounded background tile
    d.rounded_rectangle(
        [px(8), px(8), px(248), px(248)],
        radius=px(52),
        fill=RED,
    )
    # a hint of depth along the bottom
    d.rounded_rectangle(
        [px(8), px(210), px(248), px(248)],
        radius=px(52),
        fill=RED_DARK,
    )
    d.rounded_rectangle(
        [px(8), px(8), px(248), px(232)],
        radius=px(52),
        fill=RED,
    )

    # download arrow: stem + arrowhead
    d.rounded_rectangle(
        [px(113), px(62), px(143), px(150)],
        radius=px(10),
        fill=WHITE,
    )
    d.polygon(
        [(px(86), px(138)), (px(170), px(138)), (px(128), px(198))],
        fill=WHITE,
    )
    # tray / baseline
    d.rounded_rectangle(
        [px(78), px(196), px(178), px(216)],
        radius=px(9),
        fill=WHITE,
    )
    return img


def main() -> None:
    out = Path(__file__).with_name("app.ico")
    master = render(SIZE)
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(out, format="ICO", sizes=sizes)
    # also a PNG preview for convenience
    master.save(Path(__file__).with_name("app_icon_preview.png"), format="PNG")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
