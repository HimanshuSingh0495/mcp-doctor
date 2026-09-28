"""Capture a real `mcp-doctor demo` run and render it as a terminal PNG.

Usage: python scripts/capture_screenshot.py <venv-python> <output-png>

Asserts the captured output contains PASS lines and that the rendered PNG
has non-background pixels, so this can never silently produce a mockup.
"""

import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

BG = (13, 17, 23)          # #0d1117
FG = (201, 209, 217)       # #c9d1d9
DIM = (139, 148, 158)      # #8b949e
GREEN = (63, 185, 80)      # #3fb950
RED = (248, 81, 73)        # #f85149
YELLOW = (210, 153, 34)
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_SIZE = 15
PAD = 24
LINE_GAP = 5


def capture(mcp_doctor: str) -> str:
    proc = subprocess.run(
        [mcp_doctor, "demo"],
        capture_output=True, text=True, timeout=60,
    )
    out = proc.stdout
    assert "PASS" in out, f"demo output has no PASS lines:\n{out}\n{proc.stderr}"
    return out


def colorize(line: str):
    stripped = line.strip()
    if stripped.startswith("[PASS]"):
        return GREEN
    if stripped.startswith("[FAIL]"):
        return RED
    if stripped.startswith(("---", "Result:")):
        return YELLOW
    if stripped.startswith("warning:"):
        return YELLOW
    if line.startswith(" ") or line.startswith("\t"):
        return DIM
    return FG


def main() -> None:
    mcp_doctor, out_path = sys.argv[1], sys.argv[2]
    output = capture(mcp_doctor)
    lines = [ln.rstrip() for ln in output.splitlines()]

    # Trim a leading "demo config: ..." temp path? Keep it; it is real output.
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    ascent, descent = font.getmetrics()
    line_h = ascent + descent + LINE_GAP

    widths = [font.getbbox(ln or " ")[2] for ln in lines]
    width = max(widths) + PAD * 2
    height = line_h * len(lines) + PAD * 2

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        y = PAD + i * line_h
        draw.text((PAD, y), line, font=font, fill=colorize(line))

    # Sanity: the image must contain non-background pixels.
    pixels = img.getdata()
    assert any(px != BG for px in pixels), "rendered PNG is all background"

    img.save(out_path)
    print(f"saved {out_path} ({width}x{height})")


if __name__ == "__main__":
    main()
