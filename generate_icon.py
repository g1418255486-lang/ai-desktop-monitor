"""Generate multi-resolution .ico file for the app (Terminal HUD palette)."""

import math
from PIL import Image, ImageDraw, ImageFont

SIZES = [16, 24, 32, 48, 64, 128, 256]

# Terminal HUD palette（与 app/theme.py 保持一致）
COLOR_BG_START = (21, 29, 25)     # BG  #151d19
COLOR_BG_END = (30, 40, 34)      # 深面板渐变
COLOR_A = (0, 230, 118)          # PRIMARY #00e676
COLOR_RING = (0, 230, 118, 70)


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "C:\\Windows\\Fonts\\seguibl.ttf",
        "C:\\Windows\\Fonts\\seguisb.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\segoeuib.ttf",
        "C:\\Windows\\Fonts\\Arialbd.ttf",
        "C:\\Windows\\Fonts\\Arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_at_size(w: int):
    img = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx = w / 2
    cy = w / 2
    outer_r = w / 2 - 1
    inner_r = outer_r - max(1, w * 0.06)

    # gradient-filled disc (dark HUD panel)
    for y in range(w):
        for x in range(w):
            dx = x - cx
            dy = y - cy
            d = math.sqrt(dx * dx + dy * dy)
            if d <= inner_r:
                t = (y / (w - 1)) if w > 1 else 0
                r = int(COLOR_BG_START[0] + (COLOR_BG_END[0] - COLOR_BG_START[0]) * t)
                g = int(COLOR_BG_START[1] + (COLOR_BG_END[1] - COLOR_BG_START[1]) * t)
                b = int(COLOR_BG_START[2] + (COLOR_BG_END[2] - COLOR_BG_START[2]) * t)
                img.putpixel((x, y), (r, g, b, 255))

    # outer ring (subtle green)
    for y in range(w):
        for x in range(w):
            dx = x - cx
            dy = y - cy
            d = math.sqrt(dx * dx + dy * dy)
            if inner_r < d <= outer_r:
                img.putpixel((x, y), COLOR_RING)

    # subtle highlight at top
    highlight_y_end = int(cy * 0.4)
    for y in range(0, max(1, highlight_y_end)):
        for x in range(w):
            dx = x - cx
            dy = y - cy
            d = math.sqrt(dx * dx + dy * dy)
            if d <= inner_r:
                alpha = int(max(0, 80 * (1 - y / highlight_y_end) * (1 - d / inner_r)))
                r, g, b, a = img.getpixel((x, y))
                img.putpixel((x, y), (
                    min(255, r + 20),
                    min(255, g + 40),
                    min(255, b + 25),
                    a,
                ))

    # "A" letter
    if w >= 24:
        font_size = int(w * 0.55)
        font = _find_font(font_size)
        bbox = draw.textbbox((0, 0), "A", font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = cx - tw / 2
        ty = cy - th / 2 - bbox[1] * 0.1
        draw.text((tx, ty), "A", fill=COLOR_A, font=font)

    return img


def main():
    import os
    os.makedirs("icons", exist_ok=True)

    images = []
    for s in SIZES:
        images.append(_draw_at_size(s))

    largest = images[-1]
    save_path = "icons/app.ico"
    largest.save(
        save_path,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
    )
    print(f"Icon saved -> {save_path}")


if __name__ == "__main__":
    main()
