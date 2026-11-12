#!/usr/bin/env python3
"""Static checks for widget.html against the Telegram widget profile (Bot API 10.4).

    python3 tests/check_widget.py [path/to/widget.html]

Prints the raw and zlib-9 sizes and fails (exit 1) when the widget is over the limits or
uses a feature outside the profile.
"""

import re
import sys
import zlib
from pathlib import Path

RAW_LIMIT, ZLIB_LIMIT, ZLIB_AIM = 32768, 4096, 3950
GENERIC_FONTS = {"system-ui", "sans-serif", "serif", "monospace", "ui-sans-serif", "ui-serif",
                 "ui-monospace", "ui-rounded", "-apple-system", "inherit", "initial"}

# (label, regex) checked against the whole file
FORBIDDEN = [
    # canvas
    ("canvas globalCompositeOperation", r"globalCompositeOperation"),
    ("canvas shadows", r"\bshadow(Blur|Color|OffsetX|OffsetY)\b"),
    ("canvas pixel read-back", r"\b(get|put|create)ImageData\b"),
    ("canvas createPattern", r"\bcreatePattern\b"),
    ("canvas createConicGradient", r"\bcreateConicGradient\b"),
    ("canvas ctx.filter", r"\.filter\s*=(?!=)"),
    ("canvas export", r"\b(toDataURL|toBlob|captureStream)\b"),
    ("OffscreenCanvas / WebGL", r"OffscreenCanvas|getContext\(\s*['\"](webgl|bitmaprenderer)"),
    # CSS
    ("CSS text-shadow", r"text-shadow"),
    ("CSS background-clip:text", r"background-clip\s*:\s*text"),
    ("CSS height-relative units (vh)", r"\d\s*[dsl]?vh\b|\bvh\b"),
    ("CSS color-mix / modern color functions", r"color-mix|\b(oklch|oklab|lch|lab|hwb)\("),
    ("CSS @font-face / @import / @container / @layer / @property", r"@(font-face|import|container|layer|property)\b"),
    ("CSS :has / :focus / form-state selectors", r":(has|focus|focus-visible|focus-within|checked|target|placeholder-shown)\b"),
    ("CSS position:sticky", r"position\s*:\s*sticky"),
    ("CSS overflow auto/scroll", r"overflow(-x|-y)?\s*:\s*(auto|scroll)"),
    ("CSS clip-path / masks / blend modes", r"clip-path|\bmask(-image)?\s*:|mix-blend-mode|background-blend-mode"),
    ("CSS line-clamp / writing-mode", r"line-clamp|writing-mode"),
    ("CSS logical properties", r"\b(margin|padding|inset)-(inline|block)\b|\b(inline|block)-size\b"),
    ("CSS 3D transforms", r"\b(rotate[XYZ]|rotate3d|translateZ|translate3d|scale3d|scaleZ|matrix3d|perspective)\b"),
    ("CSS filters outside blur/brightness/drop-shadow", r"\b(grayscale|sepia|saturate|contrast|hue-rotate|invert)\("),
    # HTML
    ("form controls", r"<(input|select|textarea|label|form|option|fieldset)\b"),
    ("out-of-profile elements", r"<(iframe|object|embed|video|audio|dialog|progress|meter|template|link|meta)\b"),
    ("external script", r"<script[^>]+src\s*="),
    ("non-data image", r"<img[^>]+src\s*=\s*['\"](?!data:)"),
    ("data: SVG image", r"data:image/svg"),
    ("focus attributes", r"\b(tabindex|autofocus|accesskey|contenteditable|draggable)\s*="),
    # JS
    ("network: fetch", r"\bfetch\s*\("),
    ("network APIs", r"\b(XMLHttpRequest|WebSocket|EventSource|RTCPeerConnection|sendBeacon|importScripts|BroadcastChannel)\b|new\s+Worker\b"),
    ("alert / confirm / prompt / print", r"\b(alert|confirm|prompt|print)\s*\("),
    ("navigator.clipboard / share / vibrate", r"navigator\s*\.\s*(clipboard|share|vibrate|geolocation)"),
    ("navigation", r"\blocation\s*(\.\s*(href|assign|replace)|=)|\bhistory\s*\.\s*(push|replace|back|go)"),
    ("window.open", r"window\s*\.\s*open\s*\("),
    ("keyboard events", r"\bkey(down|up|press)\b"),
    ("touch events", r"\btouch(start|move|end|cancel)\b"),
    ("wheel / scroll events", r"\bon(wheel|scroll)\b|['\"](wheel|scroll)['\"]"),
    ("focus()/blur() calls", r"\.(focus|blur|select)\(\s*\)"),
    ("Blob / FileReader / createObjectURL", r"\b(Blob|FileReader|createObjectURL)\b"),
    ("custom elements / shadow DOM", r"customElements|attachShadow"),
    ("requestFullscreen", r"requestFullscreen"),
    ("TelegramWidget.sendMessage", r"\.sendMessage\b"),
    ("emoji / pictographs", "[☀-➿⬀-⯿\U0001f000-\U0001faff]"),
    ("HTML/CSS comments", r"<!--|/\*"),
]


def font_problems(src: str) -> list:
    out = []
    for m in re.finditer(r"font-family\s*:\s*([^;}]+)|\bfont\s*[:=]\s*['\"]?([^;}'\"]+)", src):
        value = (m.group(1) or m.group(2)).strip()
        if m.group(2):  # shorthand: families come after the size (e.g. "600 13px system-ui")
            parts = re.split(r"\d[\d.]*(?:px|em|rem|%|pt)(?:/[\d.]+\w*)?\s+", value, maxsplit=1)
            if len(parts) < 2:
                continue
            value = parts[1]
        for fam in (f.strip().strip("'\"") for f in value.split(",")):
            if fam and fam.lower() not in GENERIC_FONTS and not fam.startswith("var("):
                out.append(fam)
    return out


def nesting_problems(css: str) -> list:
    """CSS nesting: a rule block inside a style rule (only @-rules may contain blocks)."""
    out, stack, prelude = [], [], ""
    for ch in css:
        if ch == "{":
            if stack and not stack[-1].startswith("@"):
                out.append(prelude.strip()[:40])
            stack.append(prelude.strip())
            prelude = ""
        elif ch == "}":
            if stack:
                stack.pop()
            prelude = ""
        elif ch == ";":
            prelude = ""
        else:
            prelude += ch
    return out


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "widget.html"
    raw = path.read_bytes()
    packed = len(zlib.compress(raw, 9))
    src = raw.decode("utf-8")
    fails = []
    print(f"{path.name}: {len(raw)} bytes raw (limit {RAW_LIMIT}), {packed} bytes zlib-9 "
          f"(limit {ZLIB_LIMIT}, aim {ZLIB_AIM})")
    if len(raw) > RAW_LIMIT:
        fails.append(f"raw size {len(raw)} > {RAW_LIMIT}")
    if packed > ZLIB_LIMIT:
        fails.append(f"zlib-9 size {packed} > {ZLIB_LIMIT}")
    elif packed > ZLIB_AIM:
        print(f"  note: {packed - ZLIB_AIM} bytes over the {ZLIB_AIM} aim (still under the hard limit)")
    if "\x00" in src:
        fails.append("NUL character")
    for label, rx in FORBIDDEN:
        for m in re.finditer(rx, src):
            line = src.count("\n", 0, m.start()) + 1
            fails.append(f"{label}: {m.group(0)!r} at line {line}")
    for fam in font_problems(src):
        fails.append(f"named font family: {fam!r}")
    for css in re.findall(r"<style[^>]*>([\s\S]*?)</style>", src):
        for sel in nesting_problems(css):
            fails.append(f"CSS nesting inside {sel!r}")
        if "&" in css:
            fails.append("CSS nesting selector '&'")
    if re.search(r"touch-action\s*:\s*none", src) and not re.search(r"canvas\s*\{[^}]*touch-action\s*:\s*none", src):
        fails.append("touch-action:none is set on something other than the field (canvas)")
    for f in fails:
        print("  FAIL", f)
    print("OK" if not fails else f"{len(fails)} problem(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
