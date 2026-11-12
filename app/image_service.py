import os
import io
import json
import time
import re
import math
import functools
import collections
import requests
from requests.adapters import HTTPAdapter
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

_IMG_HTTP_SESSION = requests.Session()
_img_adapter = HTTPAdapter(pool_connections=25, pool_maxsize=25)
_IMG_HTTP_SESSION.mount("https://", _img_adapter)
_IMG_HTTP_SESSION.mount("http://", _img_adapter)

@functools.lru_cache(maxsize=256)
def load_font(name: str, size: int):
    # 1. Project bundled fonts in app/fonts/
    bundled = os.path.join(os.path.dirname(__file__), "fonts", name)
    if os.path.exists(bundled):
        try:
            return ImageFont.truetype(bundled, size)
        except Exception:
            pass
    # 2. Windows system fonts
    win_p = os.path.join("C:\\Windows\\Fonts", name)
    if os.path.exists(win_p):
        try:
            return ImageFont.truetype(win_p, size)
        except Exception:
            pass
    # 3. Linux system fonts
    for ldir in ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype", "/usr/share/fonts"]:
        lp = os.path.join(ldir, name)
        if os.path.exists(lp):
            try:
                return ImageFont.truetype(lp, size)
            except Exception:
                pass
    return ImageFont.load_default()


try:
    import ctypes
    from ctypes import wintypes
    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32
    HAS_GDI = True
except Exception:
    HAS_GDI = False

_THAI_UPPER_VOWELS = set("\u0e31\u0e34\u0e35\u0e36\u0e37")   # ั ิ ี ึ ื
_THAI_TOP_MARKS = set("\u0e48\u0e49\u0e4a\u0e4b\u0e4c")        # ่ ้ ๊ ๋ ์


def _thai_split_stacked(text):
    """Pillow without libraqm has no GPOS mark stacking, so a tone mark that follows an upper vowel
    (e.g. จี้ นิ้ว ที่ เกี่ยว) collides with the vowel and disappears.
    Returns (stripped_text, [(index_in_stripped, mark_char)]) with those tone marks pulled out so they can be
    drawn separately, raised above the vowel."""
    out = []
    marks = []
    n = len(text)
    for i, ch in enumerate(text):
        after_upper_vowel = bool(out) and out[-1] in _THAI_UPPER_VOWELS
        before_sara_am = (i + 1 < n and text[i + 1] == "\u0e33")   # น้ำ ก๊ำ : tone sits above the nikhahit
        if ch in _THAI_TOP_MARKS and (after_upper_vowel or before_sara_am):
            marks.append((len(out), ch))
        else:
            out.append(ch)
    return "".join(out), marks


def _draw_thai_text(draw, xy, text, font, fill, anchor="ls", lift_ratio=0.2):
    """draw.text() replacement that renders Thai stacked tone marks correctly without a shaping engine."""
    stripped, marks = _thai_split_stacked(text)
    draw.text(xy, stripped, font=font, fill=fill, anchor=anchor)
    if marks:
        lift = font.size * lift_ratio
        for idx, mk in marks:
            pen = font.getlength(stripped[:idx])
            draw.text((xy[0] + pen, xy[1] - lift), mk, font=font, fill=fill, anchor=anchor)


PROMPT_FILES = {
    "regular": "Prompt-Regular.ttf",
    "medium": "Prompt-Medium.ttf",
    "semibold": "Prompt-SemiBold.ttf",
    "bold": "Prompt-Bold.ttf",
}


def _text_alpha_curve(p):
    """Razor-sharp S-curve for text edges: eliminates outer blur halo (<38 -> 0) and solidifies stroke core (>188 -> 255)."""
    if p < 38:
        return 0
    if p > 188:
        return 255
    t = (p - 38.0) / (188.0 - 38.0)
    v = t * t * (3.0 - 2.0 * t)
    return int(255 * (v ** 0.78))


_TEXT_LUT = [_text_alpha_curve(i) for i in range(256)]


def measure_hq(text, weight="semibold", size=30):
    """Width in logical 1200p px of text rendered with the Prompt font (same on Windows & Linux)."""
    f = load_font(PROMPT_FILES[weight], int(round(size * 4)))
    return f.getlength(text) / 4.0


def draw_hq(canvas, text, x, baseline, weight="semibold", size=30, color=(0, 0, 0)):
    """Draw Thai/Latin text with the Prompt font: Ultra-HD supersampled + UnsharpMask + Steep S-Curve LUT.
    (x, baseline, size) are in logical 1200p coordinates and automatically scale to canvas resolution (e.g. 2400x2400)."""
    if not text:
        return 0
    hd_scale = canvas.width / 1200.0
    real_x = x * hd_scale
    real_baseline = baseline * hd_scale
    real_size = max(8, int(round(size * hd_scale)))

    S = 3 if hd_scale >= 2.0 else 4
    f = load_font(PROMPT_FILES[weight], real_size * S)
    stripped_t, _mk = _thai_split_stacked(text)
    bb = f.getbbox(stripped_t, anchor="ls")
    if _mk:
        bb = (bb[0], min(bb[1], bb[1] - int(real_size * 0.35 * S)), bb[2], bb[3])
    pad = 8
    ox = ((-bb[0]) // S + pad + 1) * S
    oy = ((-bb[1]) // S + pad + 1) * S
    w = ox + (bb[2] // S + pad + 2) * S
    h = oy + (bb[3] // S + pad + 2) * S
    layer = Image.new("L", (w, h), 0)
    _draw_thai_text(ImageDraw.Draw(layer), (ox, oy), text, f, 255, anchor="ls")
    down = layer.resize((w // S, h // S), Image.Resampling.BICUBIC)
    down = down.filter(ImageFilter.UnsharpMask(radius=0.65, percent=155, threshold=2))
    a = down.point(_TEXT_LUT)
    tl = Image.new("RGBA", a.size, (color[0], color[1], color[2], 0))
    tl.putalpha(a)
    canvas.paste(tl, (int(round(real_x)) - ox // S, int(round(real_baseline)) - oy // S), tl)
    return (f.getlength(text) / S) / hd_scale


def fit_hq(text, weight, max_size, min_size, max_w):
    """Largest font size (<= max_size) whose rendered width fits max_w; returns (size, width)."""
    for sz in range(max_size, min_size - 1, -1):
        w = measure_hq(text, weight, sz)
        if w <= max_w:
            return sz, w
    return min_size, measure_hq(text, weight, min_size)


def split_two_lines(text):
    """Split text into 2 balanced lines at a space (prefers a space before '(')."""
    if "(" in text and text.index("(") > 0:
        i = text.index("(")
        return text[:i].strip(), text[i:].strip()
    words = text.split(" ")
    if len(words) < 2:
        return text, ""
    best = min(range(1, len(words)), key=lambda k: abs(len(" ".join(words[:k])) - len(" ".join(words[k:]))))
    return " ".join(words[:best]), " ".join(words[best:])


TEXT_SS = 4  # text supersampling factor (render at 4x then downsample => razor-sharp edges)


def draw_razor_thai(canvas, text, x, y, font_name="Leelawadee UI", font_size=44, bold=True, color=(0, 0, 0)):
    if not text:
        return 0, 0

    scale = TEXT_SS

    if not HAS_GDI:
        # Linux / Render path: supersampled FreeType rendering (4x) -> LANCZOS downsample -> solid alpha curve
        font_hi = load_font("leelawdb.ttf" if bold else "leelawad.ttf", font_size * scale)
        font_1x = load_font("leelawdb.ttf" if bold else "leelawad.ttf", font_size)
        pad = 8
        tmp = Image.new("L", (8, 8), 0)
        bb = ImageDraw.Draw(tmp).textbbox((0, 0), _thai_split_stacked(text)[0], font=font_hi)
        w4 = bb[2] + pad * 2 * scale
        h4 = bb[3] + pad * 2 * scale
        w4 += (-w4) % scale
        h4 += (-h4) % scale
        layer_hi = Image.new("L", (w4, h4), 0)
        _draw_thai_text(ImageDraw.Draw(layer_hi), (pad * scale, pad * scale), text, font_hi, 255, anchor="la")
        alpha_1x = layer_hi.resize((w4 // scale, h4 // scale), Image.Resampling.LANCZOS).point(_TEXT_LUT)
        text_layer = Image.new("RGBA", alpha_1x.size, (color[0], color[1], color[2], 0))
        text_layer.putalpha(alpha_1x)
        canvas.paste(text_layer, (x - pad, y - pad), text_layer)
        b = font_1x.getbbox(text)
        return b[2] - b[0], b[3] - b[1]

    sz_hi = font_size * scale
    weight = 700 if bold else 400

    hdc_screen = user32.GetDC(0)
    hdc = gdi32.CreateCompatibleDC(hdc_screen)

    hfont = gdi32.CreateFontW(-sz_hi, 0, 0, 0, weight, 0, 0, 0, 222, 0, 0, 4, 0, font_name)
    old_font = gdi32.SelectObject(hdc, hfont)

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]
    size = SIZE()
    gdi32.GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(size))

    pad_top = int(sz_hi * 0.52)
    pad_bot = int(sz_hi * 0.42)
    pad_left = 5 * scale
    w = size.cx + 20 * scale + pad_left
    h = size.cy + pad_top + pad_bot
    w += (-w) % scale
    h += (-h) % scale
    pad_top -= pad_top % scale  # keep vertical offset an exact multiple of the scale

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    ppvBits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(ppvBits), 0, 0)
    old_bmp = gdi32.SelectObject(hdc, hbmp)

    hbrush = gdi32.CreateSolidBrush(0x00000000)
    rect = wintypes.RECT(0, 0, w, h)
    user32.FillRect(hdc, ctypes.byref(rect), hbrush)
    gdi32.DeleteObject(hbrush)

    gdi32.SetBkMode(hdc, 1)
    gdi32.SetTextColor(hdc, 0x00FFFFFF)

    text_rect = wintypes.RECT(pad_left, pad_top, w, h)
    user32.DrawTextW(hdc, text, len(text), ctypes.byref(text_rect), 0x00000100 | 0x00000800)

    buf = ctypes.string_at(ppvBits.value, w * h * 4)
    raw_hi = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("L")

    gdi32.SelectObject(hdc, old_font)
    gdi32.SelectObject(hdc, old_bmp)
    gdi32.DeleteObject(hfont)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc)
    user32.ReleaseDC(0, hdc_screen)

    # Downsample 4x -> 1x with LANCZOS, then apply solid alpha curve (crisp + dark strokes)
    alpha_1x = raw_hi.resize((w // scale, h // scale), Image.Resampling.LANCZOS).point(_TEXT_LUT)

    text_layer = Image.new("RGBA", alpha_1x.size, (color[0], color[1], color[2], 0))
    text_layer.putalpha(alpha_1x)

    canvas.paste(text_layer, (x - 5, y - pad_top // scale), text_layer)
    return size.cx // scale, size.cy // scale

def measure_thai_text(text, font_name="Leelawadee UI", font_size=36, bold=True):
    if not HAS_GDI:
        font = load_font("leelawdb.ttf" if bold else "leelawad.ttf", font_size)
        b = font.getbbox(text)
        return b[2] - b[0], b[3] - b[1]

    hdc_screen = user32.GetDC(0)
    hdc = gdi32.CreateCompatibleDC(hdc_screen)
    weight = 700 if bold else 400
    hfont = gdi32.CreateFontW(-font_size, 0, 0, 0, weight, 0, 0, 0, 222, 0, 0, 4, 0, font_name)
    old_font = gdi32.SelectObject(hdc, hfont)

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]
    size = SIZE()
    gdi32.GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(size))

    gdi32.SelectObject(hdc, old_font)
    gdi32.DeleteObject(hfont)
    gdi32.DeleteDC(hdc)
    user32.ReleaseDC(0, hdc_screen)
    return size.cx, size.cy

def remove_white_bg(img, threshold=235):
    """Accurately removes white background using 8-directional border floodfill,
    filtering out compression dust specks so blister packs & white products crop cleanly."""
    img = img.convert('RGBA')
    w, h = img.size
    pixels = img.load()
    visited = set()
    queue = collections.deque()
    # Seed all 4 outer borders
    for x in range(w):
        queue.append((x, 0)); queue.append((x, h - 1))
        visited.add((x, 0)); visited.add((x, h - 1))
    for y in range(h):
        queue.append((0, y)); queue.append((w - 1, y))
        visited.add((0, y)); visited.add((w - 1, y))

    neighbors = [(1,0), (-1,0), (0,1), (0,-1), (1,1), (-1,-1), (1,-1), (-1,1)]
    while queue:
        x, y = queue.popleft()
        r, g, b, a = pixels[x, y]
        if r >= threshold and g >= threshold and b >= threshold:
            pixels[x, y] = (r, g, b, 0)
            for dx, dy in neighbors:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                    visited.add((nx, ny))
                    nr, ng, nb, na = pixels[nx, ny]
                    if nr >= threshold and ng >= threshold and nb >= threshold:
                        queue.append((nx, ny))

    # Clean isolated noise specks from alpha mask before computing bounding box
    alpha = img.split()[-1]
    alpha_clean = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    bbox = alpha_clean.getbbox()
    if bbox:
        return img.crop(bbox)
    bbox_raw = img.getbbox()
    if bbox_raw:
        return img.crop(bbox_raw)
    return img

# Shopee overlays its "ส่งฟรี" (free shipping) + "ส่วนลด" (discount) badges on the bottom-left corner of the cover.
# Measured on a 1200x1200 cover: badges occupy x 0..~700, y ~1030..1200. Keep every important element out of it.
SHOPEE_BADGE_ZONE = (0, 1030, 705, 1200)
COVER_SAFE_BOTTOM = 1012   # product / text must end above this line (x < SHOPEE_BADGE_ZONE[2])
COVER_SAFE_TOP = 135       # keep clear of the shop header


def nonwhite_bbox(img, threshold=238):
    """Bounding box (l, t, r, b) of non-white pixels of an image (None if blank)."""
    g = img.convert('L').point(lambda v: 255 if v < threshold else 0)
    return g.getbbox()


def resize_hq(img, size):
    """High-quality resize: LANCZOS (+ reducing_gap off) for crisp, alias-free scaling."""
    if img.size == tuple(size):
        return img.copy()
    return img.resize(tuple(size), Image.Resampling.LANCZOS)


def enhance_product(img, sharp=1.0, contrast=1.07, color=1.08):
    """Studio-style enhancement on RGB channels only (alpha untouched):
    sharpen edges (unsharp mask), boost contrast and color so tools look rich and glossy.
    Also anti-aliases the cut-out edge so the silhouette is smooth (no jagged steps)."""
    img = img.convert('RGBA')
    r, g, b, a = img.split()
    rgb = Image.merge('RGB', (r, g, b))
    rgb = ImageEnhance.Contrast(rgb).enhance(contrast)
    rgb = ImageEnhance.Color(rgb).enhance(color)
    rgb = rgb.filter(ImageFilter.UnsharpMask(radius=1.2, percent=int(70 * sharp), threshold=4))
    # soften only the alpha edge (0.6px) for a smooth, natural cut-out outline
    a = a.filter(ImageFilter.GaussianBlur(0.5))
    out = rgb.convert('RGBA')
    out.putalpha(a)
    return out


def make_contact_shadow(prod_rgba, opacity=0.30):
    """Thin contact shadow that only exists directly under the lowest pixels of the product.
    Shape is derived from the product's own silhouette (no long gray bar).
    Returns (shadow_rgba, offset_y_from_product_bottom)."""
    alpha = prod_rgba.split()[-1]
    w, h = alpha.size
    band_h = max(6, int(h * 0.035))
    band = alpha.crop((0, h - band_h, w, h))
    # collapse the bottom band into a flat footprint
    foot_h = 9
    foot = band.resize((w, foot_h), Image.Resampling.BILINEAR)
    foot = foot.point(lambda v: 255 if v > 90 else 0)
    pad = 14
    layer = Image.new('L', (w + pad * 2, foot_h + pad * 2), 0)
    layer.paste(foot, (pad, pad))
    layer = layer.filter(ImageFilter.GaussianBlur(4.5))
    layer = layer.point(lambda v: int(v * opacity))
    shadow = Image.new('RGBA', layer.size, (30, 30, 30, 0))
    shadow.putalpha(layer)
    return shadow, pad


def draw_aa_rounded_rect(canvas, box, radius, fill=None, outline=None, width=1):
    """Anti-aliased 4x supersampled rounded rectangle. Scales coordinates automatically with canvas resolution."""
    hd_scale = canvas.width / 1200.0
    x0 = int(round(box[0] * hd_scale))
    y0 = int(round(box[1] * hd_scale))
    x1 = int(round(box[2] * hd_scale))
    y1 = int(round(box[3] * hd_scale))
    w = x1 - x0
    h = y1 - y0
    if w <= 0 or h <= 0:
        return
    S = 3 if hd_scale >= 2.0 else 4
    pad = 4
    im = Image.new('RGBA', ((w + pad * 2) * S, (h + pad * 2) * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r_px = int(round(radius * hd_scale * S))
    w_px = int(round(width * hd_scale * S)) if outline else 0
    d.rounded_rectangle(
        [pad * S, pad * S, (pad + w) * S - 1, (pad + h) * S - 1],
        radius=r_px,
        fill=fill,
        outline=outline,
        width=w_px
    )
    down = im.resize((w + pad * 2, h + pad * 2), Image.Resampling.LANCZOS)
    canvas.paste(down, (x0 - pad, y0 - pad), down)


def draw_smooth_hexagon(canvas, cx, cy, radius, fill_color, icon_str=None):
    """Draws an anti-aliased hexagon and optional crisp vector icon inside it (scales with canvas resolution)."""
    hd_scale = canvas.width / 1200.0
    real_cx = int(round(cx * hd_scale))
    real_cy = int(round(cy * hd_scale))
    real_r = int(round(radius * hd_scale))
    S = 4
    box_r = int(real_r * 1.15)
    sz = box_r * 2 * S
    im = Image.new('RGBA', (sz, sz), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    hcx = sz / 2.0
    hcy = sz / 2.0
    r_s = real_r * S
    pts = []
    for i in range(6):
        angle = math.radians(30 + i * 60)
        pts.append((hcx + r_s * 0.92 * math.cos(angle), hcy + r_s * 0.92 * math.sin(angle)))
    d.polygon(pts, fill=fill_color)

    if icon_str is not None:
        white = (255, 255, 255, 255)
        ic = str(icon_str or '⚡').strip()
        if '📏' in ic or '📐' in ic:
            # Crisp vector angled ruler with tick marks
            angle = math.radians(-45)
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            def _rot(x, y):
                return (hcx + x * cos_a - y * sin_a, hcy + x * sin_a + y * cos_a)
            rw, rh = r_s * 0.92, r_s * 0.36
            rect_pts = [_rot(-rw/2, -rh/2), _rot(rw/2, -rh/2), _rot(rw/2, rh/2), _rot(-rw/2, rh/2)]
            d.polygon(rect_pts, fill=white)
            for t_i in range(-3, 4):
                tx = t_i * (rw / 8.0)
                th = rh * (0.55 if t_i % 2 == 0 else 0.36)
                d.line([_rot(tx, -rh/2), _rot(tx, -rh/2 + th)], fill=fill_color, width=max(2, int(r_s * 0.07)))
        elif '🔘' in ic or '⚙' in ic:
            # Crisp concentric precision rings
            r_out = r_s * 0.50
            r_mid = r_s * 0.34
            r_in = r_s * 0.20
            d.ellipse([hcx - r_out, hcy - r_out, hcx + r_out, hcy + r_out], fill=white)
            d.ellipse([hcx - r_mid, hcy - r_mid, hcx + r_mid, hcy + r_mid], fill=fill_color)
            d.ellipse([hcx - r_in, hcy - r_in, hcx + r_in, hcy + r_in], fill=white)
        elif '⏱' in ic or '🔄' in ic:
            # Crisp vector stopwatch / gauge
            r_out = r_s * 0.46
            r_in = r_s * 0.32
            oy = r_s * 0.04
            d.ellipse([hcx - r_out, hcy - r_out + oy, hcx + r_out, hcy + r_out + oy], fill=white)
            d.ellipse([hcx - r_in, hcy - r_in + oy, hcx + r_in, hcy + r_in + oy], fill=fill_color)
            bw, bh = r_s * 0.22, r_s * 0.10
            d.rectangle([hcx - bw/2, hcy - r_out - bh*0.7, hcx + bw/2, hcy - r_out + bh*0.5], fill=white)
            d.line([(hcx, hcy + oy), (hcx, hcy - r_s*0.16)], fill=white, width=max(2, int(r_s * 0.09)))
            d.line([(hcx, hcy + oy), (hcx + r_s*0.16, hcy + oy)], fill=white, width=max(2, int(r_s * 0.09)))
        elif '🛡' in ic or '✔' in ic or '✅' in ic:
            # Crisp mini checkmark
            chk = [
                (hcx - r_s * 0.28, hcy + r_s * 0.02),
                (hcx - r_s * 0.06, hcy + r_s * 0.24),
                (hcx + r_s * 0.32, hcy - r_s * 0.22)
            ]
            d.line(chk, fill=white, width=max(3, int(r_s * 0.14)), joint='curve')
        else:
            # Crisp high-voltage lightning bolt
            bolt = [
                (hcx + r_s * 0.08, hcy - r_s * 0.52),
                (hcx - r_s * 0.28, hcy + r_s * 0.04),
                (hcx - r_s * 0.02, hcy + r_s * 0.04),
                (hcx - r_s * 0.12, hcy + r_s * 0.52),
                (hcx + r_s * 0.28, hcy - r_s * 0.06),
                (hcx + r_s * 0.02, hcy - r_s * 0.06),
            ]
            d.polygon(bolt, fill=white)

    down = im.resize((box_r * 2, box_r * 2), Image.Resampling.LANCZOS)
    canvas.paste(down, (real_cx - box_r, real_cy - box_r), down)


def draw_vector_shield(canvas, cx, cy, size=52, fill_color=(239, 28, 37)):
    hd_scale = canvas.width / 1200.0
    real_cx = int(round(cx * hd_scale))
    real_cy = int(round(cy * hd_scale))
    real_size = int(round(size * hd_scale))
    scale = 4
    sz = real_size * scale
    im = Image.new('RGBA', (sz, sz), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    w = sz * 0.82
    h = sz * 0.96
    x0 = (sz - w) / 2
    y0 = (sz - h) / 2
    x1 = x0 + w
    y1 = y0 + h

    pts = [
        (x0, y0),
        (x1, y0),
        (x1, y0 + h * 0.54),
        (sz / 2, y1),
        (x0, y0 + h * 0.54)
    ]
    d.polygon(pts, fill=fill_color)

    chk = [
        (sz * 0.35, sz * 0.46),
        (sz * 0.47, sz * 0.59),
        (sz * 0.69, sz * 0.33)
    ]
    d.line(chk, fill=(255, 255, 255, 255), width=int(scale * 4.5 * hd_scale), joint='curve')

    down = im.resize((real_size, real_size), Image.Resampling.LANCZOS)
    canvas.paste(down, (real_cx - real_size // 2, real_cy - real_size // 2), down)

def get_official_brand_logo(brand_name):
    if not brand_name:
        return None
    b_clean = re.sub(r'[^a-zA-Z0-9]', '', str(brand_name)).upper()
    official_dir = os.path.abspath("assets/logos/official")
    candidates = [
        os.path.join(official_dir, f"{str(brand_name).lower()}_official_clean.png"),
        os.path.join(official_dir, f"{b_clean}.png"),
        os.path.join(official_dir, f"{str(brand_name).upper()}.png"),
        os.path.join(official_dir, f"{str(brand_name).lower()}.png"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

_HERO_PRODUCT_CACHE = collections.OrderedDict()

def _get_prepared_hero_product(raw_img_path_or_url, hd_s):
    """Returns cached (resized_prod, shadow_img, pos_x, pos_y, sh_x, sh_y) so editing cover text re-renders in <0.15s."""
    cache_key = (str(raw_img_path_or_url).strip(), int(hd_s))
    if cache_key in _HERO_PRODUCT_CACHE:
        _HERO_PRODUCT_CACHE.move_to_end(cache_key)
        return _HERO_PRODUCT_CACHE[cache_key]

    raw_im = fetch_image_safe(raw_img_path_or_url)
    prod_img = remove_white_bg(raw_im)
    if not prod_img:
        return None

    bbox = prod_img.getbbox()
    if bbox:
        pad = 4
        x1 = max(0, bbox[0] - pad)
        y1 = max(0, bbox[1] - pad)
        x2 = min(prod_img.width, bbox[2] + pad)
        y2 = min(prod_img.height, bbox[3] + pad)
        prod_crop = prod_img.crop((x1, y1, x2, y2))
    else:
        prod_crop = prod_img

    cw, ch = prod_crop.size
    box_left = 368 * hd_s
    box_right = 1164 * hd_s
    box_top = 140 * hd_s
    box_bottom = 985 * hd_s

    box_w = box_right - box_left
    box_h = box_bottom - box_top

    scale = min(box_w / cw, box_h / ch)
    tgt_w = int(cw * scale)
    tgt_h = int(ch * scale)

    pos_x = box_left + (box_w - tgt_w) // 2
    pos_y = box_top + (box_h - tgt_h) // 2

    resized_prod = resize_hq(prod_crop, (tgt_w, tgt_h))
    up = max(tgt_w / max(cw, 1), tgt_h / max(ch, 1))
    adaptive_sharp = 1.0 if up <= 1.0 else max(0.45, 1.2 / up)
    resized_prod = enhance_product(resized_prod, sharp=adaptive_sharp)
    shadow_img, sh_x, sh_y = None, 0, 0
    try:
        shadow_img, sh_pad = make_contact_shadow(resized_prod)
        sh_x = pos_x - sh_pad
        sh_y = pos_y + tgt_h - sh_pad - 2 * hd_s
    except Exception as e:
        print(f"Contact shadow skipped: {e}")

    res_tuple = (resized_prod, shadow_img, pos_x, pos_y, sh_x, sh_y)
    _HERO_PRODUCT_CACHE[cache_key] = res_tuple
    while len(_HERO_PRODUCT_CACHE) > 25:
        _HERO_PRODUCT_CACHE.popitem(last=False)
    return res_tuple

def generate_auto_spec_cover(
    raw_img_path_or_url,
    output_path,
    brand=None,
    sku="",
    badge_text=None,
    custom_footer=None,
    shop_name="MEGATOOL",
    shop_subtitle="เมก้า ทูล",
    overwrite=True,
    custom_model=None,
    custom_category=None,
    custom_hero_pills=None,
    custom_spec_cards=None,
    custom_trust_s1=None,
    custom_trust_s2=None
):
    """
    Auto-Spec Product Cover Template (Ultra-HD 2400x2400 Human Designer Architecture):
    - 2400x2400px (2x Ultra-HD) official shop background framing
    - Manufacturer brand logo (Makita, POLO, 3M, Dongcheng, Jasic, etc.)
    - Category Title + Model Pill + Highlight Tags with razor-sharp supersampled typography
    - 4 Authentic Spec Cards with vector hexagons and vector icons
    - Compact Trust & Warranty Guarantee Card
    - HERO PRODUCT: Auto-cropped to actual silhouette, scaled to maximum possible size
    """
    HD_S = 2
    canvas_size = 1200 * HD_S
    is_bigpower = bool(shop_name and ('bigpower' in shop_name.lower() or 'big power' in shop_name.lower() or 'shop2' in shop_name.lower() or 'shop_2' in shop_name.lower()))
    official_shop_name = "BIGPOWER TOOLS" if is_bigpower else "MEGATOOL"

    RED = (239, 28, 37, 255)
    TOOL_NAVY = (15, 62, 104, 255)
    theme_color = TOOL_NAVY if is_bigpower else RED
    theme_rgb = (theme_color[0], theme_color[1], theme_color[2])

    canvas = generate_cover(
        "",
        None,
        badge_text=badge_text,
        shop_name=official_shop_name,
        overwrite=True,
        template_type="standard",
        return_image=True
    )
    draw = ImageDraw.Draw(canvas)

    from app.ktw_service import get_product_detail, detect_brand_from_sku
    detail = None
    if sku:
        try:
            detail = get_product_detail(sku)
        except Exception as e:
            print(f"Error fetching detail for {sku}: {e}")

    detected_brand = brand or (detail.get('brand') if detail else None) or detect_brand_from_sku(sku) or "MAKITA"
    defaults = get_auto_cover_defaults(sku, detail=detail, shop_name=official_shop_name)

    # 1. Category title (Customizable)
    if custom_category and str(custom_category).strip():
        category_title = str(custom_category).strip()
    else:
        category_title = defaults.get("category_title", "เครื่องมือช่างคุณภาพ")

    # 2. Model Name (Customizable)
    if custom_model and str(custom_model).strip():
        model_code = str(custom_model).strip()
        model_name = f"รุ่น {model_code}" if not model_code.startswith("รุ่น") else model_code
    else:
        model_name = defaults.get("model_name", "รุ่นยอดนิยม")

    # 3. Spec Cards (Customizable with Deduplication Fallback)
    if custom_spec_cards and isinstance(custom_spec_cards, list) and len(custom_spec_cards) > 0:
        spec_cards = []
        for sp in custom_spec_cards[:4]:
            if isinstance(sp, dict) and sp.get('label') and sp.get('val'):
                spec_cards.append({
                    "icon": sp.get('icon', '⚡'),
                    "label": str(sp.get('label')).strip(),
                    "val": str(sp.get('val')).strip()
                })
        if not spec_cards:
            spec_cards = defaults.get("spec_cards", [])
    else:
        spec_cards = defaults.get("spec_cards", [])

    # 4. Hero Highlights (Sub-Pill Badges Customizable)
    if custom_hero_pills and isinstance(custom_hero_pills, list) and len(custom_hero_pills) > 0:
        hero_pills = [str(p).strip() for p in custom_hero_pills if str(p).strip()][:2]
    else:
        hero_pills = defaults.get("hero_pills", ["สินค้ารับประกันของแท้ 100%"])

    # 5. Trust Card lines (Customizable)
    trust_s1 = str(custom_trust_s1).strip() if (custom_trust_s1 and str(custom_trust_s1).strip()) else defaults.get("trust_s1", "จัดส่งด่วนจากไทย 100%")
    trust_s2 = str(custom_trust_s2).strip() if (custom_trust_s2 and str(custom_trust_s2).strip()) else defaults.get("trust_s2", "สต็อกไทย ได้รับของรวดเร็ว")

    # --- HERO PRODUCT PLACEMENT (Human Designer Logic: Maximum Hero Size, Auto-Cropped, Zero Overlap, Cached) ---
    try:
        hero_layer = _get_prepared_hero_product(raw_img_path_or_url, HD_S)
        if hero_layer:
            resized_prod, shadow_img, pos_x, pos_y, sh_x, sh_y = hero_layer
            if shadow_img is not None:
                canvas.paste(shadow_img, (sh_x, sh_y), shadow_img)
            canvas.paste(resized_prod, (pos_x, pos_y), resized_prod)
    except Exception as e:
        print(f"Error loading product image: {e}")

    # Official Brand Logo ONLY: Optical Sizing Standard (Auto-Crop + Perceived Visual Weight)
    brand_logo_p = get_official_brand_logo(detected_brand)
    if brand_logo_p and os.path.exists(brand_logo_p):
        try:
            b_img = Image.open(brand_logo_p).convert('RGBA')
            alpha_b = b_img.split()[-1]
            b_bbox = alpha_b.getbbox()
            if b_bbox:
                b_img = b_img.crop(b_bbox)
            bw, bh = b_img.size
            ratio = bw / max(bh, 1)

            max_box_w = 275 * HD_S
            max_box_h = (82 if ratio >= 1.6 else 88) * HD_S
            target_area = (16500 if ratio >= 1.6 else 12500) * (HD_S * HD_S)
            scale_area = math.sqrt(target_area / (bw * bh))
            b_scale = min(scale_area, max_box_w / bw, max_box_h / bh)

            if bh * b_scale < 55 * HD_S and bw * ((55 * HD_S) / bh) <= max_box_w:
                b_scale = (55 * HD_S) / bh

            tgt_bw = max(1, int(bw * b_scale))
            tgt_bh = max(1, int(bh * b_scale))
            brand_logo = b_img.resize((tgt_bw, tgt_bh), Image.Resampling.LANCZOS)

            logo_y = 40 * HD_S + (82 * HD_S - tgt_bh) // 2
            canvas.paste(brand_logo, (52 * HD_S, logo_y), brand_logo)
        except Exception as e:
            print(f"Error placing brand logo: {e}")

    if is_bigpower:
        TEXT_INK = (10, 15, 28)
        TEXT_LABEL = (15, 23, 42)
        trust_s1_color = theme_rgb
        trust_s2_color = (15, 23, 42)
    else:
        # Shop 1: MEGATOOL - 100% Solid Pure Jet-Black typography for maximum sharpness & contrast
        TEXT_INK = (0, 0, 0)
        TEXT_LABEL = (0, 0, 0)
        trust_s1_color = (0, 0, 0)
        trust_s2_color = (0, 0, 0)

    DIVIDER_COLOR = (196, 202, 212, 255)
    WHITE = (255, 255, 255, 255)
    COL_L = 52
    COL_R = 354   # left text column hard limit (product starts at x >= 368)
    max_text_w = COL_R - COL_L

    # --- Title (category) ---
    t_sz, _tw = fit_hq(category_title, "bold", 44, 30, max_text_w)
    draw_hq(canvas, category_title, COL_L, 188, "bold", t_sz, TEXT_INK)

    # --- Model pill ---
    pill_top = 214
    pill_h = 62
    m_sz, m_w = fit_hq(model_name, "bold", 34, 18, max_text_w - 32)
    pill_w = min(max_text_w, int(m_w) + 32)
    draw_aa_rounded_rect(canvas, [COL_L, pill_top, COL_L + pill_w, pill_top + pill_h], radius=12, fill=theme_color)
    draw_hq(canvas, model_name, COL_L + (pill_w - m_w) / 2.0, pill_top + pill_h // 2 + int(m_sz * 0.36), "bold", m_sz, (255, 255, 255))

    # --- Highlight sub-pills (Max 2 compact badges, strictly <= max_text_w, never overlapping product) ---
    curr_y = pill_top + pill_h + 16
    sub_bg = (238, 244, 252, 255) if is_bigpower else (255, 238, 239, 255)
    sub_border = (170, 194, 224, 255) if is_bigpower else (250, 165, 168, 255)

    clean_pills = []
    for hp in hero_pills[:2]:
        hp_clean = hp.strip()
        if ',' in hp_clean and len(hp_clean) > 24:
            hp_clean = hp_clean.split(',')[0].strip()
        if len(hp_clean) > 26:
            hp_clean = hp_clean[:25].rstrip(' ,-/')
        clean_pills.append(hp_clean)

    for hp in clean_pills:
        hp_sz, hp_w = fit_hq(hp, "bold", 21, 17, max_text_w - 26)
        ph = 38
        bw_ = min(max_text_w, int(hp_w) + 26)
        draw_aa_rounded_rect(canvas, [COL_L, curr_y, COL_L + bw_, curr_y + ph], radius=8, fill=sub_bg, outline=sub_border, width=2)
        draw_hq(canvas, hp, COL_L + (bw_ - hp_w) / 2.0, curr_y + ph // 2 + int(hp_sz * 0.36), "bold", hp_sz, TEXT_INK)
        curr_y += ph + 8

    # --- Spec rows (Ultra-Crisp Standardized Typography & Vector Icons) ---
    spec_top = curr_y + 16
    n_rows = max(1, len(spec_cards[:4]))
    trust_card_h = 84
    bottom_limit = COVER_SAFE_BOTTOM - 4
    avail = bottom_limit - spec_top - trust_card_h - 18
    spec_row_h = max(96, min(136, avail // n_rows))

    hex_radius = 26
    hex_center_x = COL_L + hex_radius
    hex_fill = (18, 56, 88, 255) if is_bigpower else (215, 25, 33, 255)
    text_x = hex_center_x + hex_radius + 14
    val_max_w = COL_R - text_x

    # Standardized consistent font sizes across all specs (SemiBold labels + Bold values)
    STD_LABEL_SZ = 21
    STD_VAL_SZ = 29
    STD_VAL_2LINE_SZ = 23

    for idx, sp in enumerate(spec_cards[:4]):
        r_y = spec_top + idx * spec_row_h
        h_cy = r_y + spec_row_h // 2 - 4

        draw_smooth_hexagon(canvas, hex_center_x, h_cy, hex_radius, fill_color=hex_fill, icon_str=sp.get('icon', '⚡'))

        lbl = sp.get('label', '')
        val = sp.get('val', '')
        if 'รอบ/นาที' in val and val.count('รอบ/นาที') > 1:
            speeds = [s.strip() for s in val.split(',') if s.strip()]
            if len(speeds) >= 2:
                val = f"{speeds[0]} / {speeds[-1]}"

        l_sz, _ = fit_hq(lbl, "semibold", STD_LABEL_SZ, 17, val_max_w)

        v_sz, v_w = fit_hq(val, "bold", STD_VAL_SZ, 24, val_max_w)
        if v_w <= val_max_w and v_sz >= 24:
            draw_hq(canvas, lbl, text_x, h_cy - 8, "semibold", l_sz, TEXT_LABEL)
            draw_hq(canvas, val, text_x, h_cy + 30, "bold", v_sz, TEXT_INK)
        else:
            ln1, ln2 = split_two_lines(val)
            draw_hq(canvas, lbl, text_x, h_cy - 22, "semibold", l_sz, TEXT_LABEL)
            draw_hq(canvas, ln1, text_x, h_cy + 6, "bold", STD_VAL_2LINE_SZ, TEXT_INK)
            if ln2:
                draw_hq(canvas, ln2, text_x, h_cy + 6 + int(STD_VAL_2LINE_SZ * 1.25), "bold", STD_VAL_2LINE_SZ, TEXT_INK)

        div_y = r_y + spec_row_h - 2
        draw.line([(COL_L * HD_S, div_y * HD_S), (COL_R * HD_S, div_y * HD_S)], fill=DIVIDER_COLOR, width=2 * HD_S)

    # --- Trust card ---
    trust_card_y = spec_top + n_rows * spec_row_h + 22
    trust_card_w = COL_R + 12 - COL_L
    card_bg = (247, 250, 253, 255) if is_bigpower else (255, 246, 246, 255)
    card_outline = (206, 218, 234, 255) if is_bigpower else (250, 205, 207, 255)
    draw_aa_rounded_rect(canvas, [COL_L, trust_card_y, COL_L + trust_card_w, trust_card_y + trust_card_h], radius=12, fill=card_bg, outline=card_outline, width=2)

    shield_cx = COL_L + 30
    shield_cy = trust_card_y + trust_card_h // 2
    draw_vector_shield(canvas, shield_cx, shield_cy, size=40, fill_color=theme_rgb)

    trust_txt_x = COL_L + 62
    tr_max_w = COL_L + trust_card_w - 14 - trust_txt_x
    s1_sz, _ = fit_hq(trust_s1, "bold", 22, 16, tr_max_w)
    s2_sz, _ = fit_hq(trust_s2, "semibold", 19, 14, tr_max_w)
    draw_hq(canvas, trust_s1, trust_txt_x, trust_card_y + 37, "bold", s1_sz, trust_s1_color)
    draw_hq(canvas, trust_s2, trust_txt_x, trust_card_y + 65, "semibold", s2_sz, trust_s2_color)

    final_rgb = canvas.convert('RGB')
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    final_rgb.save(output_path, "JPEG", quality=98, subsampling=0, optimize=True)
    return output_path


def generate_cover(
    raw_img_path_or_url,
    output_path,
    brand=None,
    sku="",
    badge_text=None,
    custom_footer=None,
    shop_name="MEGATOOL",
    shop_subtitle="เมก้า ทูล",
    overwrite=True,
    template_type="standard",
    custom_model=None,
    custom_category=None,
    custom_hero_pills=None,
    custom_spec_cards=None,
    custom_trust_s1=None,
    custom_trust_s2=None,
    return_image=False
):
    if template_type == "auto_spec":
        return generate_auto_spec_cover(
            raw_img_path_or_url=raw_img_path_or_url,
            output_path=output_path,
            brand=brand,
            sku=sku,
            badge_text=badge_text,
            custom_footer=custom_footer,
            shop_name=shop_name,
            shop_subtitle=shop_subtitle,
            overwrite=overwrite,
            custom_model=custom_model,
            custom_category=custom_category,
            custom_hero_pills=custom_hero_pills,
            custom_spec_cards=custom_spec_cards,
            custom_trust_s1=custom_trust_s1,
            custom_trust_s2=custom_trust_s2
        )
    if not return_image and not overwrite and output_path and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        return output_path

    HD_S = 2
    RED = (239, 28, 37, 255) # #EF1C25 (MEGATOOL Red)
    TOOL_NAVY = (15, 62, 104, 255) # #0F3E68 (BigPower Tools Navy)
    POWER_ORANGE = (245, 130, 32, 255) # #F58220 (Tool City Orange)
    WHITE = (255, 255, 255, 255)
    canvas_size = 1200 * HD_S

    is_bigpower = bool(shop_name and ('bigpower' in shop_name.lower() or 'big power' in shop_name.lower() or 'shop2' in shop_name.lower() or 'shop_2' in shop_name.lower()))
    is_mega = not is_bigpower and (not shop_name or 'mega' in shop_name.lower() or 'zonix' in shop_name.lower() or 'shop1' in shop_name.lower() or 'shop_1' in shop_name.lower())

    theme_color = TOOL_NAVY if is_bigpower else RED

    # 1. Canvas
    canvas = Image.new('RGBA', (canvas_size, canvas_size), WHITE)
    draw = ImageDraw.Draw(canvas)

    # 2. Load Product Image (if provided)
    raw_img = None
    if raw_img_path_or_url:
        if raw_img_path_or_url.startswith('http'):
            try:
                r = requests.get(raw_img_path_or_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
                if r.status_code == 200 and len(r.content) > 100:
                    raw_img = Image.open(io.BytesIO(r.content)).convert('RGBA')
            except Exception:
                raw_img = None
        elif os.path.exists(raw_img_path_or_url):
            try:
                raw_img = Image.open(raw_img_path_or_url).convert('RGBA')
            except Exception:
                raw_img = None

    if raw_img is not None:
        w, h = raw_img.size
        scale = min(canvas_size / w, canvas_size / h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        px = (canvas_size - new_w) // 2
        py = (canvas_size - new_h) // 2

        bb = nonwhite_bbox(raw_img)
        if bb:
            k = new_w / float(w)
            gx0, gy0 = px + bb[0] * k, py + bb[1] * k
            gx1, gy1 = px + bb[2] * k, py + bb[3] * k
            if gx0 < SHOPEE_BADGE_ZONE[2] * HD_S and gy1 > COVER_SAFE_BOTTOM * HD_S:
                bh = gy1 - gy0
                f = min(1.0, ((COVER_SAFE_BOTTOM - COVER_SAFE_TOP) * HD_S) / max(bh, 1))
                if f < 1.0:
                    new_w = max(1, int(new_w * f))
                    new_h = max(1, int(new_h * f))
                    k2 = new_w / float(w)
                    cx = (gx0 + gx1) / 2.0
                    px = int(cx - ((bb[0] + bb[2]) / 2.0) * k2)
                    py = int(COVER_SAFE_BOTTOM * HD_S - bb[3] * k2)
                else:
                    py = int(py - (gy1 - COVER_SAFE_BOTTOM * HD_S))
        resized_raw = resize_hq(raw_img, (new_w, new_h))
        resized_raw = enhance_product(resized_raw, sharp=0.8, contrast=1.05, color=1.05)
        canvas.paste(resized_raw, (px, py), resized_raw if resized_raw.mode == 'RGBA' else None)

    # 4. Outer Red Frame (on top of image)
    border_w = 22 * HD_S
    draw.rectangle([(0, 0), (canvas_size - 1, canvas_size - 1)], outline=theme_color, width=border_w)

    # 4. Top-Right: Shop Logo (MEGATOOL Red vs BigPower Tools Navy)
    if is_bigpower:
        f_prefix = load_font('arialbd.ttf', 72 * HD_S)
        f_tool = load_font('ariblk.ttf', 72 * HD_S)

        part_prefix = "BIGPOWER "
        char_t, char_o1, char_o2, char_l, char_s = 'T', 'O', 'O', 'L', 'S'

        w_prefix = draw.textbbox((0, 0), part_prefix, font=f_prefix)[2]
        w_t = draw.textbbox((0, 0), char_t, font=f_tool)[2]
        w_o1 = draw.textbbox((0, 0), char_o1, font=f_tool)[2]
        w_o2 = draw.textbbox((0, 0), char_o2, font=f_tool)[2]
        w_l = draw.textbbox((0, 0), char_l, font=f_tool)[2]
        w_s = draw.textbbox((0, 0), char_s, font=f_tool)[2]

        total_w = w_prefix + w_t + w_o1 + w_o2 + w_l + w_s
        margin_right = 36 * HD_S
        margin_top = 30 * HD_S

        x_start = canvas_size - margin_right - total_w
        y_text = margin_top

        draw.text((x_start, y_text), part_prefix, fill=theme_color, font=f_prefix)
        xt = x_start + w_prefix
        draw.text((xt, y_text), char_t, fill=theme_color, font=f_tool)
        xo1 = xt + w_t
        draw.text((xo1, y_text), char_o1, fill=theme_color, font=f_tool)
        xo2 = xo1 + w_o1
        draw.text((xo2, y_text), char_o2, fill=theme_color, font=f_tool)
        xl = xo2 + w_o2
        draw.text((xl, y_text), char_l, fill=theme_color, font=f_tool)
        xs = xl + w_l
        draw.text((xs, y_text), char_s, fill=theme_color, font=f_tool)

        o1_box = draw.textbbox((xo1, y_text), char_o1, font=f_tool)
        o2_box = draw.textbbox((xo2, y_text), char_o2, font=f_tool)
        arc_left = o1_box[0] + 2 * HD_S
        arc_right = o2_box[2] - 2 * HD_S
        arc_top = o1_box[3] - 8 * HD_S
        arc_bot = o1_box[3] + 22 * HD_S
        draw.arc([arc_left, arc_top, arc_right, arc_bot], start=12, end=168, fill=POWER_ORANGE, width=6 * HD_S)
    elif is_mega:
        f_prefix = load_font('arialbd.ttf', 84 * HD_S)
        f_tool = load_font('ariblk.ttf', 84 * HD_S)

        is_all_caps = not shop_name or shop_name.isupper() or 'MEGATOOL' in (shop_name or '')
        if is_all_caps:
            part_prefix = 'MEGA'
            char_t, char_o1, char_o2, char_l = 'T', 'O', 'O', 'L'
        else:
            part_prefix = 'Mega'
            char_t, char_o1, char_o2, char_l = 't', 'o', 'o', 'l'

        w_prefix = draw.textbbox((0, 0), part_prefix, font=f_prefix)[2]
        w_t = draw.textbbox((0, 0), char_t, font=f_tool)[2]
        w_o1 = draw.textbbox((0, 0), char_o1, font=f_tool)[2]
        w_o2 = draw.textbbox((0, 0), char_o2, font=f_tool)[2]
        w_l = draw.textbbox((0, 0), char_l, font=f_tool)[2]

        total_w = w_prefix + w_t + w_o1 + w_o2 + w_l
        margin_right = 32 * HD_S
        margin_top = 28 * HD_S

        x_start = canvas_size - margin_right - total_w
        y_text = margin_top

        draw.text((x_start, y_text), part_prefix, fill=RED, font=f_prefix)
        xt = x_start + w_prefix
        draw.text((xt, y_text), char_t, fill=RED, font=f_tool)
        xo1 = xt + w_t
        draw.text((xo1, y_text), char_o1, fill=RED, font=f_tool)
        xo2 = xo1 + w_o1
        draw.text((xo2, y_text), char_o2, fill=RED, font=f_tool)
        xl = xo2 + w_o2
        draw.text((xl, y_text), char_l, fill=RED, font=f_tool)

        o1_box = draw.textbbox((xo1, y_text), char_o1, font=f_tool)
        o2_box = draw.textbbox((xo2, y_text), char_o2, font=f_tool)
        arc_left = o1_box[0] + 6 * HD_S
        arc_right = o2_box[2] - 6 * HD_S
        arc_top = o1_box[3] - 16 * HD_S
        arc_bot = o1_box[3] + 16 * HD_S
        draw.arc([arc_left, arc_top, arc_right, arc_bot], start=10, end=170, fill=RED, width=7 * HD_S)
    else:
        f_shop_main = load_font('arialbd.ttf', 76 * HD_S)
        margin_right = 32 * HD_S
        margin_top = 28 * HD_S
        title_text = shop_name.strip().rstrip('.')
        main_bbox = draw.textbbox((0, 0), title_text, font=f_shop_main)
        main_w = main_bbox[2] - main_bbox[0]
        x_main = canvas_size - margin_right - main_w
        draw.text((x_main, margin_top), title_text, fill=RED, font=f_shop_main)

    # 5. Bottom-Right: Slanted Red Ribbon Banner
    banner_h = 120 * HD_S
    y_top = canvas_size - banner_h
    y_bot = canvas_size

    x_slant_bot = 620 * HD_S
    x_slant_top = 685 * HD_S

    draw.polygon([
        (x_slant_bot, y_bot),
        (canvas_size, y_bot),
        (canvas_size, y_top),
        (x_slant_top, y_top)
    ], fill=theme_color)

    display_banner_text = badge_text if (badge_text and badge_text != 'ของแท้ 100%') else "มีสต็อกพร้อมส่งทันที"

    f_banner = load_font('tahomabd.ttf', 46 * HD_S)
    text_center_x = (x_slant_top + canvas_size - border_w) // 2
    text_center_y = y_top + (banner_h // 2) - 4 * HD_S
    draw.text((text_center_x, text_center_y), display_banner_text, fill=WHITE, font=f_banner, anchor='mm')

    # 6. Above Banner: 'ของแท้  100%'
    f_badge_thai = load_font('tahomabd.ttf', 54 * HD_S)
    f_badge_num = load_font('arialbd.ttf', 62 * HD_S)

    badge_y = y_top - 22 * HD_S

    num_str = "100%"
    thai_str = "ของแท้"

    num_box = draw.textbbox((0, 0), num_str, font=f_badge_num)
    num_w = num_box[2] - num_box[0]

    thai_box = draw.textbbox((0, 0), thai_str, font=f_badge_thai)
    thai_w = thai_box[2] - thai_box[0]

    num_x = canvas_size - 45 * HD_S - num_w
    thai_x = num_x - 30 * HD_S - thai_w

    draw.text((thai_x, badge_y), thai_str, fill=theme_color, font=f_badge_thai, anchor='ls')
    draw.text((num_x, badge_y), num_str, fill=theme_color, font=f_badge_num, anchor='ls')

    line_w = 4 * HD_S
    draw.line([(num_x - 4 * HD_S, badge_y - 64 * HD_S), (num_x + num_w + 4 * HD_S, badge_y - 64 * HD_S)], fill=theme_color, width=line_w)
    draw.line([(num_x - 4 * HD_S, badge_y + 8 * HD_S), (num_x + num_w + 4 * HD_S, badge_y + 8 * HD_S)], fill=theme_color, width=line_w)

    if return_image:
        return canvas

    # 7. Save
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    final_img = canvas.convert('RGB')
    final_img.save(output_path, 'JPEG', quality=98, subsampling=0, optimize=True)
    return output_path

import threading

CDN_CACHE_PATH = "app/static/covers/cdn_cache.json"
_CACHE_LOCK = threading.Lock()
_MEM_CACHE = {}

def _init_cdn_cache():
    global _MEM_CACHE
    if os.path.exists(CDN_CACHE_PATH):
        try:
            with open(CDN_CACHE_PATH, 'r', encoding='utf-8') as f:
                _MEM_CACHE = json.load(f)
        except Exception:
            _MEM_CACHE = {}

_init_cdn_cache()

def _save_cdn_cache_threadsafe(key, url):
    global _MEM_CACHE
    with _CACHE_LOCK:
        _MEM_CACHE[key] = url
        try:
            os.makedirs(os.path.dirname(os.path.abspath(CDN_CACHE_PATH)), exist_ok=True)
            with open(CDN_CACHE_PATH, 'w', encoding='utf-8') as f:
                json.dump(_MEM_CACHE, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("Error saving cdn cache:", e)

def upload_to_cdn(image_path, max_retries=2, force=False):
    """
    Uploads image to Freeimage.host (Cloudflare-backed iili.io CDN)
    with thread-safe persistent caching and automatic retries.
    Shopee's crawler requires global Cloudflare-backed URLs with Access-Control-Allow-Origin: *.
    """
    if not os.path.exists(image_path):
        print(f"upload_to_cdn: File not found: {image_path}")
        return None

    # Check in-memory cache first (instant 0.0001s)
    cache_key = os.path.basename(image_path)
    if not force:
        with _CACHE_LOCK:
            if cache_key in _MEM_CACHE and _MEM_CACHE[cache_key] and 'iili.io' in _MEM_CACHE[cache_key]:
                cached_url = _MEM_CACHE[cache_key]
                # Skip known expired or invalid test prefix
                if not cached_url.startswith('https://iili.io/njU'):
                    return cached_url

    url = 'https://freeimage.host/api/1/upload'
    api_key = '6d207e02198a847aa98d0a2a901485a5'

    
    for attempt in range(max_retries):
        try:
            with open(image_path, 'rb') as f:
                r = _IMG_HTTP_SESSION.post(
                    url,
                    data={'key': api_key, 'action': 'upload', 'format': 'json'},
                    files={'source': f},
                    timeout=15
                )
                if r.status_code == 200:
                    data = r.json()
                    res_url = data.get('image', {}).get('url')
                    if res_url and 'iili.io' in res_url:
                        _save_cdn_cache_threadsafe(cache_key, res_url)
                        return res_url
        except Exception as e:
            print(f"Freeimage upload attempt {attempt+1} failed:", e)
        time.sleep(1)

    return None




# ==============================================================================
# FEATURE 1: MULTI-IMAGE COLLAGE BUILDER ("อุปกรณ์ในกล่องครบชุด / What's in the box")
# ==============================================================================

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
    'Referer': 'https://shop.ktw.co.th/'
}

_RAW_IMG_CACHE = collections.OrderedDict()

def fetch_image_safe(url_or_path):
    if not url_or_path:
        raise ValueError("Empty image path or url")
    
    # 1. Clean path prefixes
    if str(url_or_path).startswith('/ktwcommercewebservices/v2'):
        url_or_path = str(url_or_path).replace('/ktwcommercewebservices/v2', '')
        
    # 2. Local static files on disk
    if str(url_or_path).startswith('/static/'):
        disk_p = f"app{url_or_path}".split('?')[0]
        if os.path.exists(disk_p):
            return Image.open(disk_p).convert('RGBA')
    elif str(url_or_path).startswith('static/'):
        disk_p = f"app/{url_or_path}".split('?')[0]
        if os.path.exists(disk_p):
            return Image.open(disk_p).convert('RGBA')
    elif os.path.exists(str(url_or_path)):
        return Image.open(str(url_or_path)).convert('RGBA')

    # 3. KTW root-relative URLs
    if str(url_or_path).startswith('/'):
        url_or_path = f"https://shop.ktw.co.th{url_or_path}"

    # 4. Web URLs with in-memory LRU cache, connection pooling, and retries
    if str(url_or_path).startswith('http'):
        cache_key = str(url_or_path).strip()
        if cache_key in _RAW_IMG_CACHE:
            _RAW_IMG_CACHE.move_to_end(cache_key)
            return _RAW_IMG_CACHE[cache_key].copy()

        last_err = None
        for attempt in range(2):
            try:
                resp = _IMG_HTTP_SESSION.get(url_or_path, headers=BROWSER_HEADERS, timeout=15)
                if resp.status_code == 200 and len(resp.content) > 100:
                    im_rgba = Image.open(io.BytesIO(resp.content)).convert('RGBA')
                    _RAW_IMG_CACHE[cache_key] = im_rgba
                    while len(_RAW_IMG_CACHE) > 40:
                        _RAW_IMG_CACHE.popitem(last=False)
                    return im_rgba.copy()
            except Exception as e:
                last_err = e
                time.sleep(0.5)
        if last_err:
            raise last_err
        raise ValueError(f"HTTP fetch failed for {url_or_path} (status {resp.status_code if 'resp' in locals() else 'unknown'})")

    # Fallback to local open
    return Image.open(str(url_or_path)).convert('RGBA')

def trim_white_space(im, threshold=245):
    """Trims excess whitespace borders around product images to maximize fill"""
    if im.mode != 'RGBA':
        im = im.convert('RGBA')
    gray = im.convert('L')
    bw = gray.point(lambda x: 255 if x < threshold else 0, mode='1')
    crop_box = bw.getbbox()
    if crop_box:
        pad = 8
        w, h = im.size
        x1 = max(0, crop_box[0] - pad)
        y1 = max(0, crop_box[1] - pad)
        x2 = min(w, crop_box[2] + pad)
        y2 = min(h, crop_box[3] + pad)
        return im.crop((x1, y1, x2, y2))
    return im

def smart_split_title(title: str) -> list:
    """
    Intelligently splits long Thai text into 2 balanced lines:
    1. Explicit \n or | delimiter
    2. Space near middle
    3. Natural Thai phrase/keyword boundary
    4. Middle character split fallback
    """
    title = str(title or "").strip()
    if not title:
        return []
    if "\n" in title:
        return [l.strip() for l in title.split("\n") if l.strip()][:2]
    if "|" in title:
        return [l.strip() for l in title.split("|") if l.strip()][:2]
    if " " in title:
        words = title.split(" ")
        mid = len(title) / 2
        best_diff = 999
        best_idx = 1
        curr_len = 0
        for i in range(len(words) - 1):
            curr_len += len(words[i]) + 1
            diff = abs(curr_len - mid)
            if diff < best_diff:
                best_diff = diff
                best_idx = i + 1
        l1 = " ".join(words[:best_idx]).strip()
        l2 = " ".join(words[best_idx:]).strip()
        return [l1, l2]
    keywords = ["ครบชุด", "พร้อมใช้งาน", "ในกล่อง", "พร้อม", "อุปกรณ์", "แถมฟรี", "ของแท้", "ประกัน", "รับประกัน", "ชุด", "กล่อง"]
    candidates = []
    for kw in keywords:
        pos = 0
        while True:
            idx = title.find(kw, pos)
            if idx == -1:
                break
            if 5 <= idx <= len(title) - 4:
                candidates.append(idx)
            pos = idx + len(kw)
    if candidates:
        mid = len(title) / 2
        candidates.sort(key=lambda x: abs(x - mid))
        split_pt = candidates[0]
        return [title[:split_pt].strip(), title[split_pt:].strip()]
    mid = len(title) // 2
    return [title[:mid].strip(), title[mid:].strip()]


def generate_collage(
    image_urls,
    output_path,
    title="",
    badge_text="มีสต็อกพร้อมส่งทันที",
    shop_name="MEGATOOL",
    model_text="",
    font_size=38,
    position="top-left",
    text_color="#FFFFFF",
    badge_style="solid"
):
    """
    Combines 2 to 4 product images directly inside the official MEGATOOL shop template:
    - 1200x1200px Clean White background
    - Solid Red Outer Border (#EF1C25, 22px)
    - Top-Right: MEGATOOL official red logo (with curved smile under OO)
    - Top-Left: Collage Title badge pill (e.g. 📦 อุปกรณ์มาตรฐานในกล่องครบชุด)
    - Center Safe Area: 2-4 photos with numbered red circle badges ① ② ③ ④
    - Bottom-Right: 'ของแท้ 100%' + Slanted Red Ribbon 'มีสต็อกพร้อมส่งทันที'
    - Card slots strictly avoid overlapping with the logo and ribbon!
    """
    CANVAS_SIZE = 1200
    RED = (239, 28, 37, 255)
    TOOL_NAVY = (15, 62, 104, 255)
    POWER_ORANGE = (245, 130, 32, 255)
    WHITE = (255, 255, 255, 255)

    is_bigpower = bool(shop_name and ('bigpower' in shop_name.lower() or 'big power' in shop_name.lower() or 'shop2' in shop_name.lower() or 'shop_2' in shop_name.lower()))
    is_mega = not is_bigpower and (not shop_name or 'mega' in shop_name.lower() or 'zonix' in shop_name.lower() or 'shop1' in shop_name.lower() or 'shop_1' in shop_name.lower())
    theme_color = TOOL_NAVY if is_bigpower else RED

    def _parse_rgba(color_val, default=(255, 255, 255, 255)):
        if not color_val:
            return default
        if isinstance(color_val, (tuple, list)):
            if len(color_val) == 3:
                return (color_val[0], color_val[1], color_val[2], 255)
            return tuple(color_val)
        try:
            from PIL import ImageColor
            rgb = ImageColor.getrgb(str(color_val).strip())
            if len(rgb) == 3:
                return (rgb[0], rgb[1], rgb[2], 255)
            return rgb
        except Exception:
            return default

    TEXT_COLOR = _parse_rgba(text_color, WHITE)
    b_style = (badge_style or "solid").lower().strip()
    if b_style not in ("solid", "white", "outline", "none", "transparent"):
        b_style = "solid"
    if b_style == "outline":
        b_style = "white"
    elif b_style == "transparent":
        b_style = "none"

    THEME_COLOR = _parse_rgba(text_color, RED)
    tr, tg, tb = THEME_COLOR[:3]
    tlum = 0.299 * tr + 0.587 * tg + 0.114 * tb
    is_pure_white = (tr > 240 and tg > 240 and tb > 240)

    if is_pure_white:
        solid_model_fill = RED
        solid_model_text = WHITE
        accent_color = RED
    else:
        solid_model_fill = THEME_COLOR
        solid_model_text = WHITE if tlum < 165 else (15, 23, 42, 255)
        accent_color = THEME_COLOR

    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), WHITE)
    draw = ImageDraw.Draw(canvas)

    # 1. Load images
    loaded_imgs = []
    for u in image_urls[:4]:
        try:
            raw_im = fetch_image_safe(u)
            loaded_imgs.append(raw_im)
        except Exception as e:
            print("Error loading image for collage:", e)

    if not loaded_imgs:
        raise ValueError("ไม่สามารถดาวน์โหลดรูปภาพได้ กรุณาลองใหม่อีกครั้ง")

    count = len(loaded_imgs)

    # 2. Render Product Image(s)
    if count == 1:
        # Single image mode: EXACT identical scaling & centered framing as generate_cover (zero offset, zero shift!)
        img = loaded_imgs[0]
        im_w, im_h = img.size
        scale = min(CANVAS_SIZE / im_w, CANVAS_SIZE / im_h)
        new_w = int(im_w * scale)
        new_h = int(im_h * scale)
        resized_im = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        px = (CANVAS_SIZE - new_w) // 2
        py = (CANVAS_SIZE - new_h) // 2
        canvas.paste(resized_im, (px, py), resized_im if resized_im.mode == "RGBA" else None)
    else:
        # Multi-image collage mode (2-4 images): trim excess margins and arrange in grid slots
        trimmed_imgs = [trim_white_space(im) for im in loaded_imgs]
        slots = []
        gap = 20

        if count == 2:
            w_each = 530
            slots.append([45, 145, 45 + w_each, 1140])       # Left: large tool
            slots.append([45 + w_each + gap, 145, 1155, 920]) # Right: accessories (safe above ribbon)

        elif count == 3:
            w_left = 530
            h_right_each = 365
            slots.append([45, 145, 45 + w_left, 1140])                                              # Left full height
            slots.append([45 + w_left + gap, 145, 1155, 145 + h_right_each])                        # Top right
            slots.append([45 + w_left + gap, 145 + h_right_each + gap, 1155, 145 + (h_right_each * 2) + gap]) # Middle right

        else: # 4 images
            slots.append([45, 145, 585, 620])   # Slot 1: Top-Left
            slots.append([605, 145, 1155, 520])  # Slot 2: Top-Right
            slots.append([45, 640, 585, 1140])  # Slot 3: Bottom-Left
            slots.append([605, 540, 1155, 915])  # Slot 4: Bottom-Right

        font_num = load_font("tahomabd.ttf", 26)

        for idx, (slot, img) in enumerate(zip(slots, trimmed_imgs)):
            sx1, sy1, sx2, sy2 = slot
            draw.rounded_rectangle([sx1, sy1, sx2, sy2], radius=16, fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), width=2)
            pad = 20

            avail_w = (sx2 - sx1) - (pad * 2)
            avail_h = (sy2 - sy1) - (pad * 2)

            im_w, im_h = img.size
            scale = min(avail_w / im_w, avail_h / im_h)
            new_w = max(10, int(im_w * scale))
            new_h = max(10, int(im_h * scale))
            resized_im = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            px = sx1 + (sx2 - sx1 - new_w) // 2
            py = sy1 + (sy2 - sy1 - new_h) // 2
            canvas.paste(resized_im, (px, py), resized_im)

            # Number Circle Badge
            badge_r = 20
            bx = sx1 + 16
            by = sy1 + 16
            draw.ellipse([bx, by, bx + (badge_r * 2), by + (badge_r * 2)], fill=RED)
            num_str = str(idx + 1)
            nb = font_num.getbbox(num_str)
            nw = nb[2] - nb[0]
            nh = nb[3] - nb[1]
            draw.text((bx + badge_r - nw // 2, by + badge_r - nh // 2 - 2), num_str, font=font_num, fill=WHITE)

    # 4. Collage Title Badge Pill
    # Strip emojis and leading symbols that cause square tofu boxes
    clean_model = re.sub(r'[𐀀-􏿿]|[☀-➿]', '', str(model_text or '')).strip()
    clean_title = re.sub(r'[𐀀-􏿿]|[☀-➿]', '', str(title or '')).strip()

    pos = (position or "top-left").lower().strip()
    if pos not in ("top-left", "top-right", "bottom-left", "center"):
        pos = "top-left"

    base_sz = int(font_size or 38)
    base_sz = max(24, min(80, base_sz))

    if pos in ("top-left", "top-right"):
        max_total_w = 640
    elif pos == "bottom-left":
        max_total_w = 555
    else:
        max_total_w = 950
    SLATE = (15, 23, 42, 255)

    if clean_model and clean_title:
        # CASE 1: Both Model + Title -> Two-tone pill (Red on left + Slate on right)
        f_t_check = load_font("leelawdb.ttf", max(22, int(base_sz * 0.72)))
        f_m_check = load_font("leelawdb.ttf", base_sz)
        wm_check = (f_m_check.getbbox(clean_model)[2] - f_m_check.getbbox(clean_model)[0]) + 44
        wt_check = (f_t_check.getbbox(clean_title)[2] - f_t_check.getbbox(clean_title)[0]) + 40

        if ("\n" in clean_title) or ("|" in clean_title) or (wm_check + wt_check > max_total_w):
            lines = smart_split_title(clean_title)
        else:
            lines = [clean_title]

        is_multiline = len(lines) > 1

        sz_m = base_sz
        sz_t = max(18, int(base_sz * (0.68 if is_multiline else 0.75)))
        f_m = load_font("leelawdb.ttf", sz_m)
        f_t = load_font("leelawdb.ttf", sz_t)

        while True:
            bm = f_m.getbbox(clean_model)
            wm = bm[2] - bm[0]
            pad_m = max(16, int(sz_m * 0.48))
            w_left = wm + (pad_m * 2)

            line_boxes = [f_t.getbbox(l) for l in lines]
            wt = max((b[2] - b[0]) for b in line_boxes) if line_boxes else 0
            pad_t = max(16, int(sz_t * 0.55))
            w_right = wt + (pad_t * 2)

            total_w = w_left + w_right
            if total_w <= max_total_w or (sz_m <= 22 and sz_t <= 15):
                break
            if sz_m > 22:
                sz_m -= 1
            if sz_t > 15:
                sz_t -= 1
            f_m = load_font("leelawdb.ttf", sz_m)
            f_t = load_font("leelawdb.ttf", sz_t)

        if total_w > max_total_w:
            ratio = max_total_w / total_w
            w_left = int(w_left * ratio)
            w_right = max_total_w - w_left
            total_w = max_total_w

        ht_line = max((b[3] - b[1]) for b in line_boxes) if line_boxes else 20
        line_gap = max(4, int(sz_t * 0.2))
        total_lines_h = (ht_line * len(lines)) + (line_gap * (len(lines) - 1))

        pill_h = max(78, total_lines_h + 30) if is_multiline else max(52, int(sz_m * 1.55))

        if pos == "top-left":
            pill_x1 = 45
            pill_y1 = 36 if is_multiline else 39
            pill_x2 = min(pill_x1 + total_w, 645)
            total_w = pill_x2 - pill_x1
            w_right = total_w - w_left
        elif pos == "top-right":
            total_w = min(total_w, max_total_w)
            pill_x1 = max(540, CANVAS_SIZE - 45 - total_w)
            pill_y1 = 36 if is_multiline else 39
            pill_x2 = CANVAS_SIZE - 45
            total_w = pill_x2 - pill_x1
            w_right = total_w - w_left
        elif pos == "bottom-left":
            pill_x1 = 45
            pill_y1 = CANVAS_SIZE - 42 - pill_h
            pill_x2 = pill_x1 + total_w
        elif pos == "center":
            pill_x1 = (CANVAS_SIZE - total_w) // 2
            pill_y1 = (CANVAS_SIZE - pill_h) // 2
            pill_x2 = pill_x1 + total_w

        pill_y2 = pill_y1 + pill_h

        hm = bm[3] - bm[1]
        start_ty = pill_y1 + (pill_h - total_lines_h) // 2

        if b_style == "solid":
            if pos in ("center", "bottom-left"):
                draw.rounded_rectangle([pill_x1 + 3, pill_y1 + 4, pill_x2 + 3, pill_y2 + 4], radius=16, fill=(0, 0, 0, 70))
            draw.rounded_rectangle([pill_x1, pill_y1, pill_x2, pill_y2], radius=16, fill=SLATE)
            draw.rounded_rectangle([pill_x1, pill_y1, pill_x1 + w_left, pill_y2], radius=16, fill=solid_model_fill)
            draw.rectangle([pill_x1 + w_left - 16, pill_y1, pill_x1 + w_left, pill_y2], fill=solid_model_fill)

            tx_m = pill_x1 + (w_left - wm) // 2
            ty_m = pill_y1 + (pill_h - hm) // 2 - bm[1]
            draw.text((tx_m, ty_m), clean_model, font=f_m, fill=solid_model_text)

            curr_y = start_ty
            for i, l in enumerate(lines):
                b = line_boxes[i]
                lw = b[2] - b[0]
                lx = pill_x1 + w_left + (w_right - lw) // 2
                draw.text((lx, curr_y - b[1]), l, font=f_t, fill=WHITE)
                curr_y += ht_line + line_gap

        elif b_style == "white":
            if pos in ("center", "bottom-left"):
                draw.rounded_rectangle([pill_x1 + 3, pill_y1 + 4, pill_x2 + 3, pill_y2 + 4], radius=16, fill=(0, 0, 0, 35))
            draw.rounded_rectangle([pill_x1, pill_y1, pill_x2, pill_y2], radius=16, fill=WHITE, outline=accent_color, width=3)
            draw.line([(pill_x1 + w_left, pill_y1 + 8), (pill_x1 + w_left, pill_y2 - 8)], fill=(203, 213, 225, 255), width=2)

            tx_m = pill_x1 + (w_left - wm) // 2
            ty_m = pill_y1 + (pill_h - hm) // 2 - bm[1]
            draw.text((tx_m, ty_m), clean_model, font=f_m, fill=accent_color)

            curr_y = start_ty
            for i, l in enumerate(lines):
                b = line_boxes[i]
                lw = b[2] - b[0]
                lx = pill_x1 + w_left + (w_right - lw) // 2
                draw.text((lx, curr_y - b[1]), l, font=f_t, fill=SLATE)
                curr_y += ht_line + line_gap

        else:  # b_style == "none"
            tx_m = pill_x1
            ty_m = pill_y1 + (pill_h - hm) // 2 - bm[1]
            draw.text((tx_m, ty_m), clean_model, font=f_m, fill=accent_color)

            curr_y = start_ty
            for i, l in enumerate(lines):
                b = line_boxes[i]
                lw = b[2] - b[0]
                lx = pill_x1 + w_left + 16
                draw.text((lx, curr_y - b[1]), l, font=f_t, fill=SLATE)
                curr_y += ht_line + line_gap

    elif clean_model and not clean_title:
        # CASE 2: Only Model -> Single bold Red pill!
        sz_m = base_sz
        f_m = load_font("leelawdb.ttf", sz_m)
        while True:
            bm = f_m.getbbox(clean_model)
            wm = bm[2] - bm[0]
            pad_m = max(18, int(sz_m * 0.55))
            total_w = wm + (pad_m * 2)
            if total_w <= max_total_w or sz_m <= 20:
                break
            sz_m -= 1
            f_m = load_font("leelawdb.ttf", sz_m)

        total_w = min(total_w, max_total_w)
        pill_h = max(52, int(sz_m * 1.55))

        if pos == "top-left":
            pill_x1 = 45
            pill_y1 = 39
            pill_x2 = min(pill_x1 + total_w, 645)
            total_w = pill_x2 - pill_x1
        elif pos == "top-right":
            total_w = min(total_w, max_total_w)
            pill_x1 = max(540, CANVAS_SIZE - 45 - total_w)
            pill_y1 = 39
            pill_x2 = CANVAS_SIZE - 45
        elif pos == "bottom-left":
            pill_x1 = 45
            pill_y1 = CANVAS_SIZE - 42 - pill_h
            pill_x2 = pill_x1 + total_w
        elif pos == "center":
            pill_x1 = (CANVAS_SIZE - total_w) // 2
            pill_y1 = (CANVAS_SIZE - pill_h) // 2
            pill_x2 = pill_x1 + total_w

        pill_y2 = pill_y1 + pill_h

        hm = bm[3] - bm[1]
        ty_m = pill_y1 + (pill_h - hm) // 2 - bm[1]

        if b_style == "solid":
            if pos in ("center", "bottom-left"):
                draw.rounded_rectangle([pill_x1 + 3, pill_y1 + 4, pill_x2 + 3, pill_y2 + 4], radius=16, fill=(0, 0, 0, 70))
            draw.rounded_rectangle([pill_x1, pill_y1, pill_x2, pill_y2], radius=16, fill=solid_model_fill)
            tx_m = pill_x1 + (total_w - wm) // 2
            draw.text((tx_m, ty_m), clean_model, font=f_m, fill=solid_model_text)

        elif b_style == "white":
            if pos in ("center", "bottom-left"):
                draw.rounded_rectangle([pill_x1 + 3, pill_y1 + 4, pill_x2 + 3, pill_y2 + 4], radius=16, fill=(0, 0, 0, 35))
            draw.rounded_rectangle([pill_x1, pill_y1, pill_x2, pill_y2], radius=16, fill=WHITE, outline=accent_color, width=3)
            tx_m = pill_x1 + (total_w - wm) // 2
            draw.text((tx_m, ty_m), clean_model, font=f_m, fill=accent_color)

        else:  # b_style == "none"
            tx_m = pill_x1
            draw.text((tx_m, ty_m), clean_model, font=f_m, fill=accent_color)

    elif not clean_model and clean_title:
        # CASE 3: Only Title -> Single solid Slate pill!
        f_t_check = load_font("leelawdb.ttf", max(22, int(base_sz * 0.82)))
        wt_check = (f_t_check.getbbox(clean_title)[2] - f_t_check.getbbox(clean_title)[0]) + 44
        if ("\n" in clean_title) or ("|" in clean_title) or (wt_check > max_total_w):
            lines = smart_split_title(clean_title)
        else:
            lines = [clean_title]

        is_multiline = len(lines) > 1
        sz_t = max(20, int(base_sz * (0.70 if is_multiline else 0.82)))
        f_t = load_font("leelawdb.ttf", sz_t)

        while True:
            line_boxes = [f_t.getbbox(l) for l in lines]
            wt = max((b[2] - b[0]) for b in line_boxes) if line_boxes else 0
            pad_t = max(18, int(sz_t * 0.58))
            pill_w = wt + (pad_t * 2)
            if pill_w <= max_total_w or sz_t <= 16:
                break
            sz_t -= 1
            f_t = load_font("leelawdb.ttf", sz_t)

        if pill_w > max_total_w:
            pill_w = max_total_w

        ht_line = max((b[3] - b[1]) for b in line_boxes) if line_boxes else 20
        line_gap = max(4, int(sz_t * 0.2))
        total_lines_h = (ht_line * len(lines)) + (line_gap * (len(lines) - 1))
        pill_h = max(72, total_lines_h + 28) if is_multiline else max(52, int(sz_t * 1.6))

        if pos == "top-left":
            pill_x1 = 45
            pill_y1 = 36 if is_multiline else 39
            pill_x2 = min(pill_x1 + pill_w, 645)
            pill_w = pill_x2 - pill_x1
        elif pos == "top-right":
            pill_w = min(pill_w, max_total_w)
            pill_x1 = max(540, CANVAS_SIZE - 45 - pill_w)
            pill_y1 = 36 if is_multiline else 39
            pill_x2 = CANVAS_SIZE - 45
        elif pos == "bottom-left":
            pill_x1 = 45
            pill_y1 = CANVAS_SIZE - 42 - pill_h
            pill_x2 = pill_x1 + pill_w
        elif pos == "center":
            pill_x1 = (CANVAS_SIZE - pill_w) // 2
            pill_y1 = (CANVAS_SIZE - pill_h) // 2
            pill_x2 = pill_x1 + pill_w

        pill_y2 = pill_y1 + pill_h

        start_ty = pill_y1 + (pill_h - total_lines_h) // 2
        if b_style == "solid":
            if pos in ("center", "bottom-left"):
                draw.rounded_rectangle([pill_x1 + 3, pill_y1 + 4, pill_x2 + 3, pill_y2 + 4], radius=16, fill=(0, 0, 0, 70))
            draw.rounded_rectangle([pill_x1, pill_y1, pill_x2, pill_y2], radius=16, fill=SLATE if is_pure_white else solid_model_fill)
            curr_y = start_ty
            for i, l in enumerate(lines):
                b = line_boxes[i]
                lw = b[2] - b[0]
                lx = pill_x1 + (pill_w - lw) // 2
                draw.text((lx, curr_y - b[1]), l, font=f_t, fill=WHITE if is_pure_white else solid_model_text)
                curr_y += ht_line + line_gap

        elif b_style == "white":
            if pos in ("center", "bottom-left"):
                draw.rounded_rectangle([pill_x1 + 3, pill_y1 + 4, pill_x2 + 3, pill_y2 + 4], radius=16, fill=(0, 0, 0, 35))
            draw.rounded_rectangle([pill_x1, pill_y1, pill_x2, pill_y2], radius=16, fill=WHITE, outline=accent_color, width=3)
            curr_y = start_ty
            for i, l in enumerate(lines):
                b = line_boxes[i]
                lw = b[2] - b[0]
                lx = pill_x1 + (pill_w - lw) // 2
                draw.text((lx, curr_y - b[1]), l, font=f_t, fill=accent_color)
                curr_y += ht_line + line_gap

        else:  # b_style == "none"
            curr_y = start_ty
            for i, l in enumerate(lines):
                b = line_boxes[i]
                lw = b[2] - b[0]
                lx = pill_x1
                draw.text((lx, curr_y - b[1]), l, font=f_t, fill=accent_color)
                curr_y += ht_line + line_gap

    else:
        # CASE 4: Neither Model nor Title -> Clean canvas without any pill!
        pass

    # 5. Shop Logo & Outer Border (MEGATOOL Red vs BigPower Tools Navy)
    border_w = 22
    margin_top = 30 if is_bigpower else 28

    if is_bigpower:
        f_prefix = load_font('arialbd.ttf', 72)
        f_tool = load_font('ariblk.ttf', 72)
        part_prefix = "BIGPOWER "
        char_t, char_o1, char_o2, char_l, char_s = 'T', 'O', 'O', 'L', 'S'
        w_prefix = draw.textbbox((0, 0), part_prefix, font=f_prefix)[2]
        w_t = draw.textbbox((0, 0), char_t, font=f_tool)[2]
        w_o1 = draw.textbbox((0, 0), char_o1, font=f_tool)[2]
        w_o2 = draw.textbbox((0, 0), char_o2, font=f_tool)[2]
        w_l = draw.textbbox((0, 0), char_l, font=f_tool)[2]
        w_s = draw.textbbox((0, 0), char_s, font=f_tool)[2]
        total_w = w_prefix + w_t + w_o1 + w_o2 + w_l + w_s
        x_start = 36 if pos == "top-right" else (CANVAS_SIZE - 36 - total_w)
        y_text = margin_top

        draw.text((x_start, y_text), part_prefix, fill=theme_color, font=f_prefix)
        xt = x_start + w_prefix
        draw.text((xt, y_text), char_t, fill=theme_color, font=f_tool)
        xo1 = xt + w_t
        draw.text((xo1, y_text), char_o1, fill=theme_color, font=f_tool)
        xo2 = xo1 + w_o1
        draw.text((xo2, y_text), char_o2, fill=theme_color, font=f_tool)
        xl = xo2 + w_o2
        draw.text((xl, y_text), char_l, fill=theme_color, font=f_tool)
        xs = xl + w_l
        draw.text((xs, y_text), char_s, fill=theme_color, font=f_tool)

        o1_box = draw.textbbox((xo1, y_text), char_o1, font=f_tool)
        o2_box = draw.textbbox((xo2, y_text), char_o2, font=f_tool)
        arc_left = o1_box[0] + 2
        arc_right = o2_box[2] - 2
        arc_top = o1_box[3] - 8
        arc_bot = o1_box[3] + 22
        draw.arc([arc_left, arc_top, arc_right, arc_bot], start=12, end=168, fill=POWER_ORANGE, width=6)
    else:
        f_prefix = load_font('arialbd.ttf', 84)
        f_tool = load_font('ariblk.ttf', 84)
        part_prefix = 'MEGA'
        char_t, char_o1, char_o2, char_l = 'T', 'O', 'O', 'L'
        w_prefix = draw.textbbox((0, 0), part_prefix, font=f_prefix)[2]
        w_t = draw.textbbox((0, 0), char_t, font=f_tool)[2]
        w_o1 = draw.textbbox((0, 0), char_o1, font=f_tool)[2]
        w_o2 = draw.textbbox((0, 0), char_o2, font=f_tool)[2]
        w_l = draw.textbbox((0, 0), char_l, font=f_tool)[2]
        total_w = w_prefix + w_t + w_o1 + w_o2 + w_l
        x_start = 32 if pos == "top-right" else (CANVAS_SIZE - 32 - total_w)
        y_text = margin_top

        draw.text((x_start, y_text), part_prefix, fill=RED, font=f_prefix)
        xt = x_start + w_prefix
        draw.text((xt, y_text), char_t, fill=RED, font=f_tool)
        xo1 = xt + w_t
        draw.text((xo1, y_text), char_o1, fill=RED, font=f_tool)
        xo2 = xo1 + w_o1
        draw.text((xo2, y_text), char_o2, fill=RED, font=f_tool)
        xl = xo2 + w_o2
        draw.text((xl, y_text), char_l, fill=RED, font=f_tool)

        o1_box = draw.textbbox((xo1, y_text), char_o1, font=f_tool)
        o2_box = draw.textbbox((xo2, y_text), char_o2, font=f_tool)
        arc_left = o1_box[0] + 6
        arc_right = o2_box[2] - 6
        arc_top = o1_box[3] - 16
        arc_bot = o1_box[3] + 16
        draw.arc([arc_left, arc_top, arc_right, arc_bot], start=10, end=170, fill=RED, width=7)

    # 6. Bottom-Right: Slanted Ribbon Banner
    banner_h = 120
    y_top = CANVAS_SIZE - banner_h
    y_bot = CANVAS_SIZE
    x_slant_bot = 620
    x_slant_top = 685

    draw.polygon([
        (x_slant_bot, y_bot),
        (CANVAS_SIZE, y_bot),
        (CANVAS_SIZE, y_top),
        (x_slant_top, y_top)
    ], fill=theme_color)

    display_banner_text = badge_text or "มีสต็อกพร้อมส่งทันที"
    f_banner = load_font('tahomabd.ttf', 46)
    text_center_x = (x_slant_top + CANVAS_SIZE - border_w) // 2
    text_center_y = y_top + (banner_h // 2) - 4
    draw.text((text_center_x, text_center_y), display_banner_text, fill=WHITE, font=f_banner, anchor='mm')

    # 7. Above Banner: 'ของแท้ 100%'
    f_badge_thai = load_font('tahomabd.ttf', 54)
    f_badge_num = load_font('arialbd.ttf', 62)
    badge_y = y_top - 22

    num_str = "100%"
    thai_str = "ของแท้"

    num_box = draw.textbbox((0, 0), num_str, font=f_badge_num)
    num_w = num_box[2] - num_box[0]
    thai_box = draw.textbbox((0, 0), thai_str, font=f_badge_thai)
    thai_w = thai_box[2] - thai_box[0]

    num_x = CANVAS_SIZE - 45 - num_w
    thai_x = num_x - 30 - thai_w

    draw.text((thai_x, badge_y), thai_str, fill=theme_color, font=f_badge_thai, anchor='ls')
    draw.text((num_x, badge_y), num_str, fill=theme_color, font=f_badge_num, anchor='ls')

    draw.line([(num_x - 4, badge_y - 64), (num_x + num_w + 4, badge_y - 64)], fill=theme_color, width=4)
    draw.line([(num_x - 4, badge_y + 8), (num_x + num_w + 4, badge_y + 8)], fill=theme_color, width=4)

    # 8. Outer Border
    draw.rectangle([(0, 0), (CANVAS_SIZE - 1, CANVAS_SIZE - 1)], outline=theme_color, width=border_w)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    canvas.convert('RGB').save(output_path, "JPEG", quality=98, subsampling=0, optimize=True)
    return output_path


# ==============================================================================
# PERSISTENT COLLAGE STORAGE PER SKU
# ==============================================================================

COLLAGES_DATA_FILE = "app/data/product_collages.json"

def _load_collages_db() -> dict:
    if os.path.exists(COLLAGES_DATA_FILE):
        try:
            with open(COLLAGES_DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print("Error loading product_collages.json:", e)
    return {}

def _save_collages_db(data: dict):
    os.makedirs(os.path.dirname(COLLAGES_DATA_FILE), exist_ok=True)
    try:
        with open(COLLAGES_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Error saving product_collages.json:", e)

def save_custom_product_image(sku: str, image_url: str, cdn_url: str = None):
    """
    Saves a generated collage or custom image record for a SKU permanently.
    """
    if not sku or not image_url:
        return
    db = _load_collages_db()
    if sku not in db:
        db[sku] = []
    
    target_fname = image_url.split('/')[-1].split('?')[0]
    exists = False
    for item in db[sku]:
        if isinstance(item, dict):
            u = item.get("url", "")
            c = item.get("cdn_url", "")
            if target_fname in u or (cdn_url and cdn_url == c):
                exists = True
                if cdn_url and not item.get("cdn_url"):
                    item["cdn_url"] = cdn_url
                break
        elif isinstance(item, str) and (target_fname in item or item == image_url):
            exists = True
            break
            
    if not exists:
        from datetime import datetime
        entry = {
            "url": image_url,
            "cdn_url": cdn_url or image_url,
            "created_at": datetime.now().isoformat()
        }
        db[sku].append(entry)
        _save_collages_db(db)

def get_custom_product_images(sku: str) -> list:
    """
    Returns list of all saved collage/custom image URLs for this SKU.
    Merges records from product_collages.json and scans app/static/covers/collage_{sku}_*.jpg
    Guarantees valid permanent CDN URLs or verified existing disk files.
    """
    if not sku:
        return []
    db = _load_collages_db()
    urls = []
    
    # 1. From JSON db
    if sku in db:
        for item in db[sku]:
            if isinstance(item, dict):
                cdn_u = item.get("cdn_url")
                local_u = item.get("url")
                u = cdn_u if (cdn_u and cdn_u.startswith('http')) else local_u
            else:
                u = str(item)
            if u and u not in urls:
                urls.append(u)

    # 2. Filter out duplicates and dead relative paths
    valid_urls = []
    for u in urls:
        if not u or u in valid_urls:
            continue
        if u.startswith('/static/covers/'):
            fname = u.split('/static/covers/')[-1].split('?')[0]
            if not os.path.exists(os.path.join("app/static/covers", fname)):
                continue
        valid_urls.append(u)

    return valid_urls

def delete_custom_product_image(sku: str, image_url: str) -> bool:
    """
    Permanently deletes a custom collage image across all SKUs from JSON db, disk, and cache.
    """
    if not image_url:
        return False
    db = _load_collages_db()
    removed = False
    target_clean = image_url.strip()
    target_fname = target_clean.split('/')[-1].split('?')[0]
    
    # 1. Remove from product_collages.json across ALL SKUs
    for k in list(db.keys()):
        new_list = []
        for item in db[k]:
            u = item.get("url", "") if isinstance(item, dict) else str(item)
            c = item.get("cdn_url", "") if isinstance(item, dict) else ""
            if (target_clean == u) or (target_clean == c) or (target_fname in u) or (target_fname in c):
                removed = True
            else:
                new_list.append(item)
        if len(new_list) != len(db[k]):
            db[k] = new_list
            removed = True
    _save_collages_db(db)
        
    # 2. Find associated local filenames (e.g. from cdn_cache.json)
    local_fnames_to_delete = []
    if target_fname.startswith("collage_") and target_fname.endswith(".jpg"):
        local_fnames_to_delete.append(target_fname)
        
    cdn_cache_path = "app/static/covers/cdn_cache.json"
    if os.path.exists(cdn_cache_path):
        try:
            with open(cdn_cache_path, "r", encoding="utf-8") as f:
                c_cache = json.load(f)
            updated_cache = False
            for k, v in list(c_cache.items()):
                if (target_clean == v) or (target_fname in v) or (target_fname == k):
                    local_fnames_to_delete.append(k)
                    del c_cache[k]
                    updated_cache = True
            if updated_cache:
                with open(cdn_cache_path, "w", encoding="utf-8") as f:
                    json.dump(c_cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print("Error cleaning cdn_cache.json:", e)

    # 3. Clean memory cache
    with _CACHE_LOCK:
        for k in list(_MEM_CACHE.keys()):
            v = _MEM_CACHE.get(k, "")
            if (target_clean == v) or (target_fname in v) or (target_fname == k):
                del _MEM_CACHE[k]

    # 4. Delete physical file from disk
    covers_dir = "app/static/covers"
    for l_fname in set(local_fnames_to_delete):
        disk_p = os.path.join(covers_dir, l_fname)
        if os.path.exists(disk_p):
            try:
                os.remove(disk_p)
                removed = True
            except Exception as e:
                print("Error removing collage file:", e)
                
    return removed


# ==============================================================================
# FEATURE 2: AUTO SPEC COMPARISON MATRIX CARD
# ==============================================================================

def extract_model_label(name, sku, detail=None):
    clean_name = re.sub(r'\[.*?\]', '', name or '').strip()
    norm_name = clean_name.replace('สวิทซ์', 'สวิทช์').replace('สวิตซ์', 'สวิทช์').replace('สวิตช์', 'สวิทช์')
    
    summary = (detail.get('summary') if detail else '') or ''
    keywords = (detail.get('keywords') if detail else []) or []
    
    UNIT_WORDS = {'MM', 'CM', 'M', 'KG', 'G', 'W', 'V', 'HP', 'L', 'BAR', 'PSI', 'PC', 'PCS', 'SET', 'INCH', 'ใหม่'}

    model_code = None

    # 1. Check summary / name for explicit 'รุ่น ...'
    for src in [name, summary]:
        if not src:
            continue
        m_explicit = re.search(r'(?:รุ่น|โมเดล|Model)\s*[:\-]?\s*([A-Za-z0-9\+]+(?:[\-\.\_\+\/][A-Za-z0-9\+]+)*(?:\s+[A-Za-z0-9\+]+)?)', src, re.IGNORECASE)
        if m_explicit:
            cand = m_explicit.group(1).strip().rstrip('.,-()[]')
            if cand.upper() not in UNIT_WORDS and len(cand) >= 2 and not cand.startswith('000'):
                model_code = cand
                break

    if not model_code:
        # Strip leading packaging and size specifications (e.g. 4-32 MM, 10 มม., 1/2", 12", 24T, etc.)
        core_text = re.sub(r'^\s*[\(\[]\s*(?:แพ็ค|กล่อง|ชุด|แถม|pack|box|set).*?[\)\]]\s*', '', norm_name, flags=re.IGNORECASE).strip()
        core_text = re.sub(r'^\s*\d+(?:[\.\-\/]\d+)?\s*(?:MM|มม\.?|นิ้ว|\"|CM|ซม\.?|M|เมตร|T)\b\s*', '', core_text, flags=re.IGNORECASE).strip()

        # 2. Check if name starts with a model code (e.g. K-101, 8119-2PE, M0910B, VOM351, MIG160D+, TD001GZ02)
        m_lead = re.match(r'^([A-Za-z0-9]+(?:[\-\_\+\/][A-Za-z0-9]+)+|[A-Za-z]{1,4}[0-9]+[A-Za-z0-9\+\/]*|[0-9]{2,}[A-Za-z]+[A-Za-z0-9\-\+\/]*)', core_text)
        if m_lead and m_lead.group(1).strip().upper() not in UNIT_WORDS:
            model_code = m_lead.group(1).strip()

    if not model_code:
        # 3. Check for English/Series model phrase in name (e.g. STEP DRILL HSSทอง, TEMFLEX 150, SANDFLEX)
        m_series = re.search(r'\b([A-Z]{2,}(?:\s+[A-Z0-9\-\+\/]+)+(?:ทอง|เงิน|ดำ|แดง|เหลือง|ขาว|น้ำเงิน|เขียว)?)\b', core_text)
        if m_series:
            cand = m_series.group(1).strip()
            tokens = [t for t in cand.split() if t.upper() not in UNIT_WORDS]
            if len(tokens) >= 1:
                model_code = ' '.join(tokens)

    if not model_code and keywords:
        # 4. Check keywords for recognized series name (e.g. 'Step Drill HSS')
        for kw in keywords:
            if kw and re.search(r'^[A-Za-z]{2,}(?:\s+[A-Za-z0-9\-\+]+)+$', kw):
                if any(w.lower() in clean_name.lower() for w in kw.split()):
                    model_code = kw.upper()
                    break

    if not model_code and sku:
        # 5. Check SKU suffix if it is alphanumeric (e.g. D021-DSM23100B -> DSM23-100B, P011-WARRIOR90 -> WARRIOR-90)
        sku_parts = sku.split('-')
        if len(sku_parts) >= 2:
            sku_suffix = sku_parts[-1].strip()
            if re.search(r'[A-Za-z]', sku_suffix) and re.search(r'[0-9]', sku_suffix):
                m_dsm = re.match(r'^([A-Za-z]+\d+)(\d{3}[A-Za-z]*)$', sku_suffix)
                if m_dsm:
                    model_code = f'{m_dsm.group(1)}-{m_dsm.group(2)}'
                else:
                    model_code = sku_suffix

    if not model_code:
        words = norm_name.split()
        sku_code = sku.split('-')[-1] if '-' in sku else sku
        model_code = words[0] if words else sku_code

    # Strip supplier prefix if present (e.g. P171-, M011-)
    model_code = re.sub(r'^[A-Z]\d+[-_]', '', model_code, flags=re.IGNORECASE).strip()

    sub = ""
    # 1. Switch differentiator (e.g. สวิทช์ท้าย, สวิทช์สไลด์) - high priority differentiator!
    if 'สวิทช์ท้าย' in norm_name or ('ท้าย' in norm_name and any(q in norm_name for q in ['สวิ', 'switch'])):
        sub = "สวิทช์ท้าย"
    elif 'สวิทช์สไลด์' in norm_name or ('สไลด์' in norm_name and any(q in norm_name for q in ['สวิ', 'switch'])):
        sub = "สวิทช์สไลด์"
    elif 'สวิทช์ข้าง' in norm_name:
        sub = "สวิทช์ข้าง"
    elif 'สวิทช์ไก' in norm_name or 'ไกปืน' in norm_name:
        sub = "สวิทช์ไกปืน"
    else:
        bar_m = re.search(r'(\d+\s*บาร์)', norm_name)
        watt_m = re.search(r'(\d+\s*[wWวัตต์]+)', norm_name)
        volt_m = re.search(r'(\d+\s*[vVโวลต์]+)', norm_name)
        inch_m = re.search(r'(\d+(?:/\d+)?\s*(?:นิ้ว|\"))', norm_name)
        mm_m = re.search(r'(\d+(?:[\.\-]\d+)?\s*(?:มม\.?|MM))', norm_name)
        pack_m = re.search(r'(\d+\s*(?:ม้วน|ชิ้น|ดอก|แพ็ค|ชุด))', norm_name)
        
        if bar_m:
            sub = f"แรงดัน {bar_m.group(1)}"
        elif watt_m:
            sub = f"กำลังไฟ {watt_m.group(1)}"
        elif volt_m:
            sub = f"ระบบ {volt_m.group(1)}"
        elif inch_m:
            sub = f"ขนาด {inch_m.group(1)}"
        elif mm_m:
            sub = f"ขนาด {mm_m.group(1)}"
        elif pack_m:
            sub = f"บรรจุ {pack_m.group(1)}"
        elif len(norm_name.split()) > 1:
            words = norm_name.split()
            sub = " ".join(words[1:3]).strip('()[]')
            if len(sub) > 14:
                sub = sub[:12] + "..."
                
    return model_code, sub.strip('()[]')

def clean_warranty(w):
    if not w:
        return "ของแท้ 100% ประกันศูนย์"
    w = str(w).strip()
    if 'motor' in w.lower() or 'มอเตอร์' in w:
        m = re.search(r'(\d+)\s*(?:ปี|year)', w, re.IGNORECASE)
        if m:
            return f"ประกันมอเตอร์ {m.group(1)} ปี"
        m = re.search(r'(\d+)\s*(?:เดือน|month)', w, re.IGNORECASE)
        if m:
            return f"ประกันมอเตอร์ {m.group(1)} เดือน"
        return "ประกันมอเตอร์ 1 ปี"
    m = re.search(r'(\d+)\s*(?:ปี|year)', w, re.IGNORECASE)
    if m:
        return f"ประกันศูนย์ {m.group(1)} ปี"
    m = re.search(r'(\d+)\s*(?:เดือน|month)', w, re.IGNORECASE)
    if m:
        return f"ประกันศูนย์ {m.group(1)} เดือน"
    if len(w) <= 24:
        return w
    return "ของแท้ 100% ประกันศูนย์"

def extract_key_specs(detail):
    specs = {}
    if not detail:
        return specs
        
    # 1. From SAP Classifications (Makita & SAP items)
    classifs = detail.get('classifications', []) or []
    for c in classifs:
        for f in c.get('features', []):
            name = f.get('name') or f.get('description') or ''
            code = f.get('code', '')
            vals = f.get('featureValues', [])
            val_str = ', '.join([v.get('value', '') for v in vals if v.get('value')])
            if name and val_str and val_str != '-':
                if 'current_range' in code or 'กระแสไฟเชื่อม' in name:
                    specs['กระแสไฟเชื่อม'] = val_str
                elif 'wire_size' in code or 'ขนาดลวด' in name:
                    specs['ขนาดลวดเชื่อม'] = val_str
                elif 'no-load' in code or 'ไร้ภาระ' in name:
                    pass  # Skip no-load voltage from replacing operating voltage
                elif 'กำลังมอเตอร์' in name or 'motor_power' in code:
                    specs['กำลังมอเตอร์'] = val_str
                elif 'voltage' in code or 'แรงดันไฟ' in name:
                    if 'แรงดันไฟฟ้า' not in specs or '220' in val_str:
                        specs['แรงดันไฟฟ้า'] = val_str
                elif 'กำลังไฟ' in name or 'power_phase' in code or 'continuous_rating' in code:
                    specs['กำลังไฟฟ้า'] = val_str
                elif 'ความเร็วรอบ' in name or 'no_load_speed' in code:
                    specs['ความเร็วรอบ'] = val_str
                elif 'เส้นผ่านศูนย์กลาง' in name or 'grinding_diameter' in code:
                    specs['ขนาดใบตัด/เจียร์'] = val_str
                elif 'น้ำหนัก' in name or 'weight' in code:
                    specs['น้ำหนักตัวเครื่อง'] = val_str
                elif 'ขนาดแกน' in name or 'spindle' in code:
                    specs['ขนาดแกนเกลียว'] = val_str
                elif 'สายไฟ' in name or 'cord' in code:
                    specs['ความยาวสายไฟ'] = val_str
                elif ('แรงดัน' in name or 'pressure' in code) and 'ไฟ' not in name and 'สาย' not in name:
                    specs['แรงดันสูงสุด'] = val_str
                elif 'อัตราการไหล' in name or 'ปริมาณน้ำ' in name or 'flow_rate' in code:
                    specs['อัตราการไหลของน้ำ'] = val_str
                elif 'step_drill' in code or 'เจาะคว้าน' in name or 'ความสามารถในการเจาะ' in name:
                    specs['ขนาดการเจาะ'] = val_str
                elif 'grade' in code or 'เกรด' in name:
                    specs['เกรดวัสดุ'] = val_str
                elif 'applications_drill' in code or 'วัสดุที่เจาะ' in name:
                    specs['วัสดุที่เจาะได้'] = val_str
                elif 'overall_length' in code or 'ความยาวรวม' in name:
                    specs['ความยาวรวม'] = val_str
                elif 'torque' in code or 'แรงบิด' in name:
                    specs['แรงบิดสูงสุด'] = val_str

    # 2. From KTW Automated Summary & Title (covers products with empty description tabs)
    summary_text = f"{detail.get('summary', '') or ''} {detail.get('name', '') or ''}".strip()
    if summary_text:
        if 'กระแสไฟเชื่อม' not in specs:
            m_cur = re.search(r'(?:กระแสไฟเชื่อม|กระแสเชื่อม|กระแสไฟ)\s*[:：]?\s*([0-9\-\.\s]+(?:\s*แอมป์|A\b))', summary_text, re.IGNORECASE)
            if m_cur:
                specs['กระแสไฟเชื่อม'] = m_cur.group(1).strip()
        if 'ขนาดลวดเชื่อม' not in specs:
            m_wire = re.search(r'ขนาดลวด(?:ที่ใช้)?\s*[:：]?\s*([0-9\-\.\s]+(?:\s*มม\.|mm\b))', summary_text, re.IGNORECASE)
            if m_wire:
                specs['ขนาดลวดเชื่อม'] = m_wire.group(1).strip()
        if 'กำลังไฟฟ้าเข้า' not in specs:
            m_kva = re.search(r'กำลังไฟ(?:ฟ้า)?เข้า?\s*[:：]?\s*([0-9\-\.\s]+(?:KVA|kVA|kva|วัตต์|W\b))', summary_text, re.IGNORECASE)
            if m_kva:
                specs['กำลังไฟฟ้าเข้า'] = m_kva.group(1).strip()
        if 'ระบบการทำงาน' not in specs:
            m_sys = re.search(r'ระบบ\s*[:：]?\s*(IGBT[a-zA-Z0-9\+\s]*|Inverter[a-zA-Z0-9\+\s]*|MMA\b|MIG\b|TIG\b)', summary_text, re.IGNORECASE)
            if m_sys:
                specs['ระบบการทำงาน'] = f"ระบบ {m_sys.group(1).strip()}"
        if 'กำลังมอเตอร์' not in specs and 'กำลังไฟฟ้า' not in specs:
            m_wat = re.search(r'([0-9,]+(?:\.\d+)?)\s*(?:วัตต์|W\b)', summary_text)
            if m_wat:
                specs['กำลังมอเตอร์'] = f"{m_wat.group(1)} วัตต์"
        if 'แรงดันไฟฟ้า' not in specs:
            m_vol = re.search(r'แรงดันไฟ(?:ฟ้า)?\s*[:：]?\s*([0-9\-\.\s]+(?:\s*โวลต์|V\b))', summary_text, re.IGNORECASE)
            if m_vol:
                specs['แรงดันไฟฟ้า'] = m_vol.group(1).strip()
        if 'อัตราการไหลของน้ำ' not in specs:
            m_flw = re.search(r'(?:ปริมาณน้ำ|อัตราการไหล(?:ของน้ำ)?)\s*[:：]?\s*([0-9\-\.\s]+(?:\s*ลิตร\/นาที|L\/min))', summary_text, re.IGNORECASE)
            if m_flw:
                specs['อัตราการไหลของน้ำ'] = m_flw.group(1).strip()
        if 'ระยะส่งสูงสุด' not in specs:
            m_hd = re.search(r'(?:ส่งสูง|ระยะส่งสูงสุด)\s*[:：]?\s*([0-9\-\.\s]+(?:\s*ม\.|เมตร))', summary_text, re.IGNORECASE)
            if m_hd:
                specs['ระยะส่งสูงสุด'] = m_hd.group(1).strip()
        if 'ขนาดท่อส่ง' not in specs:
            m_pip = re.search(r'ขนาดท่อ(?:ที่ใช้ได้)?\s*[:：]?\s*([^,\(\)\n]+?(?:นิ้ว|หุน|มม\.))', summary_text, re.IGNORECASE)
            if m_pip:
                specs['ขนาดท่อส่ง'] = m_pip.group(1).strip()
        if 'ขนาดการเจาะ' not in specs:
            m_drl = re.search(r'ขนาด\s*([0-9\-\.\s]+\s*มม\.)', summary_text)
            if m_drl:
                specs['ขนาดการเจาะ'] = m_drl.group(1).strip()
        if 'ขนาดแกนเกลียว' not in specs:
            m_shk = re.search(r'แกน\s*([0-9\-\.\s]+\s*มม\.)', summary_text)
            if m_shk:
                specs['ขนาดแกนเกลียว'] = m_shk.group(1).strip()
        if 'แรงบิดสูงสุด' not in specs:
            m_tor = re.search(r'แรงบิด(?:สูงสุด)?\s*[:：]?\s*([0-9\-\.\s]+(?:\s*นิวตันเมตร|N\.m|Nm\b))', summary_text, re.IGNORECASE)
            if m_tor:
                specs['แรงบิดสูงสุด'] = m_tor.group(1).strip()
        if 'ความเร็วรอบ' not in specs:
            m_rpm = re.search(r'ความเร็วรอบ\s*[:：]?\s*([0-9,]+(?:\s*-\s*[0-9,]+)?\s*(?:รอบ\/นาที|รอบต่อนาที|RPM|rpm\b))', summary_text, re.IGNORECASE)
            if m_rpm:
                specs['ความเร็วรอบ'] = m_rpm.group(1).strip()

    # 2. From Description bullet points (POLO, DongCheng, consumables, etc.)
    desc = detail.get('description', '') or ''
    clean_desc = re.sub(r'<br\s*/?>', '\n', desc, flags=re.IGNORECASE)
    clean_desc = re.sub(r'</p>', '\n', clean_desc, flags=re.IGNORECASE)
    clean_desc = re.sub(r'<[^>]+>', '', clean_desc)
    prod_full_name = detail.get('name', '') or ''
    full_text = (prod_full_name + ' ' + clean_desc).replace('สวิทซ์', 'สวิทช์').replace('สวิตซ์', 'สวิทช์').replace('สวิตช์', 'สวิทช์')
    is_tape_or_consumable = any(k in full_text.lower() for k in ['เทป', 'temflex', 'scotch', 'กาว', 'สายรัด', 'น้ำยา', 'ซิลิโคน', 'ถุงมือ', 'หน้ากาก', 'แว่นตา', 'ใบมีด'])

    for line in clean_desc.split('\n'):
        line = line.strip().lstrip('•').lstrip('-').lstrip('*').strip()
        if not line:
            continue
        if ':' in line or '：' in line:
            parts = re.split(r'[:：]', line, maxsplit=1)
            k = parts[0].strip()
            v = parts[1].strip()
            if k and v and len(k) < 30 and len(v) < 50:
                # Capture generic catalog bullet points from source
                if k not in specs and not any(q in k.lower() for q in ['ประกัน', 'เงื่อนไข', 'แถม', 'บริการ']):
                    specs[k] = v
                # Hose length (pressure washers only, NOT power cords)
                if ('สายฉีด' in k or 'สายอัดฉีด' in k or 'hose' in k.lower()) and 'ความยาวสายฉีด' not in specs:
                    m_v = re.search(r'(\d+(?:\.\d+)?)\s*(?:ม\.|เมตร|m\b)', v, re.IGNORECASE)
                    m_k = re.search(r'(\d+(?:\.\d+)?)\s*(?:ม\.|เมตร|m\b)', k, re.IGNORECASE)
                    if m_v:
                        specs['ความยาวสายฉีด'] = f"{m_v.group(1)} เมตร"
                    elif m_k:
                        specs['ความยาวสายฉีด'] = f"{m_k.group(1)} เมตร"
                    elif not any(q in v for q in ['ชิ้น', 'อัน', 'เส้น', 'ชุด', 'กล่อง']):
                        specs['ความยาวสายฉีด'] = v
                elif ('สายไฟ' in k or 'cord' in k.lower()) and 'ความยาวสายไฟ' not in specs:
                    m_v = re.search(r'(\d+(?:\.\d+)?)\s*(?:ม\.|เมตร|m\b)', v, re.IGNORECASE)
                    if m_v:
                        specs['ความยาวสายไฟ'] = f"{m_v.group(1)} เมตร"
                    else:
                        specs['ความยาวสายไฟ'] = v
                elif 'กำลังมอเตอร์' in k and 'กำลังมอเตอร์' not in specs:
                    specs['กำลังมอเตอร์'] = v
                elif ('ประเภทมอเตอร์' in k or 'ชนิดมอเตอร์' in k) and 'ประเภทมอเตอร์' not in specs:
                    specs['ประเภทมอเตอร์'] = v
                elif 'กำลังไฟ' in k and 'กำลังไฟฟ้า' not in specs:
                    specs['กำลังไฟฟ้า'] = v
                elif ('แรงดัน' in k or 'pressure' in k.lower()) and 'สาย' not in k and 'ไฟ' not in k and 'แรงดันสูงสุด' not in specs:
                    specs['แรงดันสูงสุด'] = v
                elif ('ปริมาณน้ำ' in k or 'อัตราการไหล' in k or 'อัตราการฉีด' in k) and 'อัตราการไหลของน้ำ' not in specs:
                    specs['อัตราการไหลของน้ำ'] = v
                elif 'น้ำหนัก' in k and 'น้ำหนักตัวเครื่อง' not in specs:
                    specs['น้ำหนักตัวเครื่อง'] = v
                elif 'ความเร็วรอบ' in k and 'ความเร็วรอบ' not in specs:
                    specs['ความเร็วรอบ'] = v
        
        # Free-text checks in line
        if 'Auto Stop' in line and 'ระบบตัดการทำงาน' not in specs:
            specs['ระบบตัดการทำงาน'] = 'ระบบ Auto Stop'
        if ('เหนี่ยวนำ' in line or 'Induction' in line) and 'ประเภทมอเตอร์' not in specs:
            specs['ประเภทมอเตอร์'] = 'มอเตอร์เหนี่ยวนำ'
        elif ('แปรงถ่าน' in line or 'Universal' in line) and 'ประเภทมอเตอร์' not in specs:
            specs['ประเภทมอเตอร์'] = 'มอเตอร์แปรงถ่าน'
            
        # Free-text hose check if still missing
        if 'ความยาวสายฉีด' not in specs and ('สายอัดฉีด' in line or ('สายฉีด' in line and 'สายไฟ' not in line)):
            m_line = re.search(r'ยาว(?:ถึง)?\s*(\d+(?:\.\d+)?)\s*(?:ม\.|เมตร|m\b)', line, re.IGNORECASE)
            if m_line:
                specs['ความยาวสายฉีด'] = f"{m_line.group(1)} เมตร"

    # Fallback: if 'กำลังมอเตอร์' is in specs but 'กำลังไฟฟ้า' missing and vice-versa
    if 'กำลังมอเตอร์' not in specs and 'กำลังไฟฟ้า' in specs and 'วัตต์' in specs['กำลังไฟฟ้า']:
        specs['กำลังมอเตอร์'] = specs['กำลังไฟฟ้า']
        del specs['กำลังไฟฟ้า']

    # 3. Fallback from conversionUnits if weight missing (ONLY for tools / machines, NEVER for tape/consumables)
    if not is_tape_or_consumable and 'น้ำหนักตัวเครื่อง' not in specs:
        units = detail.get('conversionUnits', [])
        if units:
            u0 = units[0]
            gross_w = u0.get('conversionGross', 0)
            net_w = u0.get('netWeight', 0)
            if gross_w:
                specs['น้ำหนักตัวเครื่อง'] = f"{gross_w:.2f} กก."
            elif net_w:
                specs['น้ำหนักตัวเครื่อง'] = f"{round(net_w / 1000.0, 2)} กก."
                
    # 4. Standardize and Balance Specs
    # 4.1 Normalize Pressure (Bar + PSI across all models)
    if 'แรงดันสูงสุด' in specs:
        p_str = specs['แรงดันสูงสุด']
        m_bar = re.search(r'(\d+)\s*บาร์', p_str)
        if m_bar:
            bar_val = int(m_bar.group(1))
            psi_val = round(bar_val * 14.5038)
            specs['แรงดันสูงสุด'] = f"{bar_val} บาร์ ({psi_val:,} PSI)"

    # Switch type extraction (for grinders and power tools)
    full_text = (detail.get('name', '') + ' ' + clean_desc).replace('สวิทซ์', 'สวิทช์').replace('สวิตซ์', 'สวิทช์').replace('สวิตช์', 'สวิทช์')
    if 'ตำแหน่งสวิตช์' not in specs:
        if 'สวิทช์ท้าย' in full_text:
            specs['ตำแหน่งสวิตช์'] = 'สวิตช์ท้าย (เปิด-ปิดท้ายเครื่อง)'
        elif 'สวิทช์สไลด์' in full_text:
            specs['ตำแหน่งสวิตช์'] = 'สวิตช์สไลด์ (เปิด-ปิดด้านบน)'
        elif 'สวิทช์ข้าง' in full_text:
            specs['ตำแหน่งสวิตช์'] = 'สวิตช์ข้าง (เปิด-ปิดด้านข้าง)'
        elif 'สวิทช์ไก' in full_text:
            specs['ตำแหน่งสวิตช์'] = 'สวิตช์ไกปืน'

    # Auto Stop for all pressure washers (verified by user and manufacturer catalog)
    is_pressure_washer = 'เครื่องฉีดน้ำ' in (detail.get('name', '') + clean_desc)
    if is_pressure_washer:
        specs['ระบบตัดการทำงาน'] = 'ระบบ Auto Stop'

    # Tape and Consumable specifications
    is_tape_or_consumable = any(k in full_text for k in ['เทป', 'TEMFLEX', 'temflex', 'scotch', 'กาว', 'สายรัด', 'น้ำยา', 'ซิลิโคน'])
    if is_tape_or_consumable:
        dim_m = re.search(r'กว้าง\s*(\d+[\d.]*)\s*มม\.?\s*ยาว\s*(\d+[\d.]*)\s*ม\.?(?:\s*หนา\s*(\d+[\d.]*)\s*มม\.?)?', clean_desc)
        if dim_m:
            specs['ขนาดหน้ากว้าง'] = f"{dim_m.group(1)} มม. x {dim_m.group(2)} ม."
            if dim_m.group(3):
                specs['ความหนาเนื้อเทป'] = f"{dim_m.group(3)} มม."
        
        volt_m = re.search(r'ทนแรงดันไฟฟ้า(?:ได้)?\s*(\d+[\d.]*)\s*(?:โวลต์|V)', clean_desc, re.IGNORECASE)
        if volt_m:
            specs['ทนแรงดันไฟฟ้า'] = f"{volt_m.group(1)} โวลต์"
            
        temp_m = re.search(r'ทนอุณหภูมิ(?:สูงสุด)?\s*(\d+[\d.]*)\s*°?\s*C', clean_desc, re.IGNORECASE)
        if temp_m:
            specs['ทนอุณหภูมิสูงสุด'] = f"{temp_m.group(1)} °C"
            
        if 'Flame Retardant' in clean_desc or 'ไม่เป็นเชื้อไฟ' in clean_desc or 'ไม่ลามไฟ' in clean_desc:
            specs['คุณสมบัติพิเศษ'] = 'ไม่ลามไฟ (Flame Retardant)'
            
        if 'แพ็ค' in (detail.get('name') or '') or 'แถม' in clean_desc:
            pack_cnt = re.search(r'(\d+)\s*(?:ม้วน|ชิ้น|แพ็ค)', detail.get('name') or '')
            specs['จำนวนบรรจุ'] = f"แพ็ค {pack_cnt.group(1)} ม้วน" if pack_cnt else "แพ็ค 10 ม้วน"

    # User requirement: fill 220V power supply ONLY for corded power tools / pressure washers
    if not is_tape_or_consumable:
        if 'กำลังไฟฟ้า' not in specs and ('วัตต์' in clean_desc or 'กำลังมอเตอร์' in specs or is_pressure_washer):
            specs['กำลังไฟฟ้า'] = '220 โวลต์ / 1 เฟส'

    # User requirement: 90 bar / compact pressure washer models use carbon brush motor (แปรงถ่าน)
    if is_pressure_washer and 'ประเภทมอเตอร์' not in specs:
        m_power = specs.get('กำลังมอเตอร์', '')
        w_match = re.search(r'(\d+[\d,]*)', m_power)
        watt = int(w_match.group(1).replace(',', '')) if w_match else 0
        if watt >= 1800:
            specs['ประเภทมอเตอร์'] = 'มอเตอร์เหนี่ยวนำ'
        elif watt > 0:
            specs['ประเภทมอเตอร์'] = 'มอเตอร์แปรงถ่าน'

    # Deduplicate similar spec keys
    if 'ความเร็วรอบ' in specs and 'ความเร็วรอบตัวเปล่า' in specs:
        del specs['ความเร็วรอบตัวเปล่า']
    if 'ความเร็วรอบ' in specs and 'ความเร็วหมุนเปล่า' in specs:
        del specs['ความเร็วหมุนเปล่า']

    # Power deduplication: keep only one single watt power key
    power_keys = [k for k in list(specs.keys()) if any(w in k for w in ['กำลังมอเตอร์', 'กำลังไฟฟ้าที่ใช้', 'กำลังไฟฟ้า', 'กำลังวัตต์', 'กำลังไฟ']) and any(u in str(specs[k]) for u in ['วัตต์', 'W', 'w'])]
    if len(power_keys) > 1:
        best_p_val = specs.get('กำลังมอเตอร์') or specs[power_keys[0]]
        for pk in power_keys:
            del specs[pk]
        specs['กำลังมอเตอร์'] = best_p_val

    # Grinding disc size deduplication
    if 'ขนาดใบตัด/เจียร์' in specs:
        for dk in ['เส้นผ่านศูนย์กลางแผ่นเจีย', 'เส้นผ่าศูนย์กลางแผ่นเจีย', 'เส้นผ่านศูนย์กลางใบ', 'ขนาดแผ่นเจียร', 'ขนาดใบตัด']:
            if dk in specs and dk != 'ขนาดใบตัด/เจียร์':
                del specs[dk]

    if 'กำลังมอเตอร์' in specs and 'กำลังไฟฟ้า' in specs and 'วัตต์' in str(specs['กำลังไฟฟ้า']):
        del specs['กำลังไฟฟ้า']

    return specs


def get_auto_cover_defaults(sku, detail=None, shop_name="MEGATOOL"):
    from app.ktw_service import get_product_detail, detect_brand_from_sku
    if not detail and sku:
        try:
            detail = get_product_detail(sku) or {}
        except Exception:
            detail = {}
    detail = detail or {}

    prod_name = detail.get('name', '') or ''
    detected_brand = (detail.get('brand') if detail else None) or detect_brand_from_sku(sku) or "MAKITA"
    specs_dict = extract_key_specs(detail)

    # 1. Category title
    if 'ดอกสว่าน' in prod_name or 'เจดีย์' in prod_name:
        category_title = "ชุดดอกสว่านเจดีย์" if ('ชุด' in prod_name or 'SET' in prod_name.upper() or '3 ดอก' in prod_name) else "ดอกสว่านเจดีย์"
    elif 'ใบตัด' in prod_name or 'ใบเจียร์' in prod_name:
        category_title = "ใบตัด / ใบเจียร์คุณภาพ"
    elif 'เครื่องเจียร์' in prod_name or 'ลูกหมู' in prod_name:
        m_sz = re.search(r'(\d+)\s*(?:นิ้ว|")', prod_name)
        category_title = f"เครื่องเจียร์ไฟฟ้า {m_sz.group(1)} นิ้ว" if m_sz else "เครื่องเจียร์ไฟฟ้า 4 นิ้ว"
    elif 'เครื่องฉีดน้ำ' in prod_name:
        category_title = "เครื่องฉีดน้ำแรงดันสูง"
    elif 'สว่านโรตารี่' in prod_name:
        category_title = "สว่านโรตารี่"
    elif 'สว่าน' in prod_name:
        category_title = "สว่านไฟฟ้า"
    elif 'เครื่องจี้ปูน' in prod_name:
        category_title = "เครื่องจี้ปูนไฟฟ้า"
    elif 'ตู้เชื่อม' in prod_name or 'เครื่องเชื่อม' in prod_name:
        category_title = "เครื่องเชื่อมไฟฟ้า"
    elif 'ปั๊ม' in prod_name:
        category_title = "ปั๊มน้ำมาตรฐาน"
    elif 'เทป' in prod_name or 'TEMFLEX' in prod_name.upper():
        category_title = "เทปพันสายไฟไวนิล"
    else:
        clean_p = re.sub(r'^\s*[\(\[]\s*(?:แพ็ค|กล่อง|ชุด|แถม).*?[\)\]]\s*', '', prod_name).strip()
        clean_p = re.sub(r'\[.*?\]', '', clean_p).strip()
        words = clean_p.split()
        category_title = ' '.join(words[:3]) if words else "เครื่องมือช่างคุณภาพ"

    # 2. Model Name
    model_code, _ = extract_model_label(prod_name, sku, detail=detail)
    model_name = f"รุ่น {model_code}" if not model_code.startswith("รุ่น") else model_code

    # 3. Spec cards with deduplication
    icon_map = {
        'แรงดันไฟฟ้า': '⚡', 'กำลัง': '⚡', 'มอเตอร์': '⚡', 'วัตต์': '⚡', 'โวลต์': '⚡',
        'กระแส': '⚡', 'แอมป์': '⚡', 'KVA': '⚡', 'เชื่อม': '⚡',
        'ความเร็ว': '⏱', 'รอบ': '⏱',
        'สวิตช์': '🔘', 'ตำแหน่ง': '🔘',
        'ขนาด': '📏', 'แกน': '📏', 'ใบ': '📏', 'สาย': '📏', 'กว้าง': '📏', 'ยาว': '📏', 'ลวด': '📏',
        'หนา': '📐',
        'แรงบิด': '⚙️', 'ทอร์ค': '⚙️',
        'อุณหภูมิ': '🌡️', 'ความร้อน': '🌡️',
        'แรงดัน': '🌊', 'บาร์': '🌊',
        'น้ำหนัก': '⚖️',
        'น้ำ': '💧', 'ไหล': '💧',
        'ระบบ': '🔌', 'Auto': '🔌', 'IGBT': '🔌', 'Inverter': '🔌',
        'คุณสมบัติ': '🛡️', 'ไม่ลามไฟ': '🛡️', 'วัสดุ': '🛡️', 'เกรด': '🛡️',
        'จำนวน': '📦', 'บรรจุ': '📦', 'แพ็ค': '📦'
    }
    def _spec_priority(item):
        k, v = item
        if 'กระแส' in k or 'แอมป์' in str(v): return 1
        if 'เจาะ' in k or 'ขนาดการเจาะ' in k: return 1
        if 'แรงบิด' in k or 'นิวตัน' in str(v): return 1
        if 'มอเตอร์' in k or 'วัตต์' in str(v) or 'W' in str(v) or 'KVA' in str(v): return 2
        if 'แรงดันสูงสุด' in k or 'บาร์' in str(v): return 3
        if 'ขนาด' in k or 'ลวด' in k or 'หัว' in k or 'ใบ' in k: return 4
        if 'ความเร็ว' in k or 'รอบ' in str(v): return 5
        if 'ความยาว' in k or 'เมตร' in str(v): return 6
        if 'อัตรา' in k or 'น้ำ' in k: return 7
        if 'สวิตช์' in k or 'ระบบ' in k: return 8
        if 'เกรด' in k or 'วัสดุ' in k: return 9
        if 'แรงดันไฟฟ้า' in k or '220' in str(v): return 10
        if 'น้ำหนัก' in k: return 11
        return 15

    sorted_specs = sorted(specs_dict.items(), key=_spec_priority)
    spec_cards = []
    seen_values = set()
    for k, v in sorted_specs:
        if len(spec_cards) >= 4:
            break
        val_clean = str(v).strip()
        val_norm = re.sub(r'\s+', '', val_clean).lower()
        if val_norm in seen_values:
            continue
        m_w = re.search(r'(\d+)\s*(?:วัตต์|w\b)', val_clean, re.I)
        if m_w and any(m_w.group(1) in sv for sv in seen_values):
            continue
        if ('220' in str(v) or 'โวลต์' in str(v)) and any('วัตต์' in sp['val'] or 'W' in sp['val'] or 'KVA' in sp['val'] or 'แอมป์' in sp['val'] for sp in spec_cards) and len(sorted_specs) > 3:
            continue
        matched_icon = '⚡'
        if 'น้ำหนัก' in k:
            matched_icon = '⚖️'
        else:
            for ik, iv in icon_map.items():
                if ik in k:
                    matched_icon = iv
                    break
        spec_cards.append({"icon": matched_icon, "label": k, "val": val_clean})
        seen_values.add(val_norm)
        if m_w:
            seen_values.add(m_w.group(1))

    # 4. Hero Pills
    hero_pills = []
    if 'เครื่องฉีดน้ำ' in prod_name:
        p_val = specs_dict.get('แรงดันสูงสุด', '90 บาร์').split('(')[0].strip()
        m_val = specs_dict.get('กำลังมอเตอร์', '1,200W').replace('วัตต์', 'W').strip()
        hero_pills = [f"แรงดัน {p_val}", f"มอเตอร์ {m_val}"]
    elif 'เครื่องเชื่อม' in prod_name or 'ตู้เชื่อม' in prod_name or 'WELDING' in prod_name.upper():
        cur = specs_dict.get('กระแสไฟเชื่อม') or '20 - 200 แอมป์'
        wire = specs_dict.get('ขนาดลวดเชื่อม') or specs_dict.get('ระบบการทำงาน') or 'ลวด 1.6 - 4.0 มม.'
        hero_pills = [f"กระแสไฟ {cur}", wire if 'ลวด' in wire else f"ขนาดลวด {wire}"]
    elif 'เครื่องเจียร์' in prod_name:
        mot = specs_dict.get('กำลังมอเตอร์', '') or specs_dict.get('กำลังไฟฟ้า', '') or '540 วัตต์'
        p_val = mot.replace('วัตต์', 'W').replace(' ', '').strip()
        b_val = specs_dict.get('ขนาดใบตัด/เจียร์', '100 มม. (4 นิ้ว)')
        hero_pills = [f"กำลังไฟ {p_val}", f"ขนาด {b_val}"]
    elif 'เทป' in prod_name or 'TEMFLEX' in prod_name.upper():
        v_str = specs_dict.get('ทนแรงดันไฟฟ้า', '600 โวลต์')
        d_str = specs_dict.get('ขนาดหน้ากว้าง', '19 มม. x 10 ม.')
        hero_pills = [f"ทนแรงดัน {v_str}", f"ขนาด {d_str}"]
    elif len(spec_cards) >= 2:
        hero_pills = [f"{spec_cards[0]['label']} {spec_cards[0]['val']}", f"{spec_cards[1]['label']} {spec_cards[1]['val']}"]
    elif len(spec_cards) == 1:
        hero_pills = [f"{spec_cards[0]['label']} {spec_cards[0]['val']}"]
    else:
        hero_pills = ["สินค้ารับประกันของแท้ 100%"]

    is_bigpower = bool(shop_name and ('bigpower' in shop_name.lower() or 'big power' in shop_name.lower() or 'shop2' in shop_name.lower() or 'shop_2' in shop_name.lower()))
    official_shop_name = "BIGPOWER TOOLS" if is_bigpower else "MEGATOOL"

    # Clean description for display
    clean_desc = re.sub(r'<br\s*/?>', '\n', detail.get('description', '') or '', flags=re.IGNORECASE)
    clean_desc = re.sub(r'</p>', '\n', clean_desc, flags=re.IGNORECASE)
    clean_desc = re.sub(r'<[^>]+>', '', clean_desc).strip()

    # Formatted classifications for display
    raw_classifs = []
    for c in (detail.get('classifications') or []):
        c_name = c.get('name') or 'คุณสมบัติทางเทคนิค'
        feats = []
        for f in c.get('features', []):
            f_name = f.get('name') or f.get('description') or ''
            vals = ', '.join([v.get('value', '') for v in f.get('featureValues', []) if v.get('value')])
            if f_name and vals and vals != '-':
                feats.append({'name': f_name, 'value': vals})
        if feats:
            raw_classifs.append({'category': c_name, 'features': feats})

    # Check if this SKU has saved persistent customizations
    custom_saved = None
    custom_file = "app/data/cover_customizations.json"
    if os.path.exists(custom_file) and sku:
        try:
            import json
            with open(custom_file, "r", encoding="utf-8") as f:
                cdata = json.load(f)
                custom_saved = cdata.get(sku)
        except Exception:
            pass

    return {
        "category_title": category_title,
        "model_name": model_name,
        "hero_pills": hero_pills,
        "spec_cards": spec_cards,
        "trust_s1": "จัดส่งด่วนจากไทย 100%",
        "trust_s2": "สต็อกไทย ได้รับของรวดเร็ว",
        "badge_text": "มีสต็อกพร้อมส่งทันที",
        "shop_name": official_shop_name,
        "all_specs": specs_dict,
        "saved_customizations": custom_saved,
        "ktw_raw": {
            "name": detail.get('name', ''),
            "sku": sku,
            "brand": detected_brand,
            "summary": detail.get('summary', ''),
            "description": clean_desc,
            "classifications": raw_classifs,
            "price": detail.get('price', {}).get('value') if isinstance(detail.get('price'), dict) else detail.get('price'),
            "stock": detail.get('stock', {}).get('stockLevel') if isinstance(detail.get('stock'), dict) else detail.get('stock')
        }
    }

def generate_comparison_card(
    items,
    output_path,
    parent_title="เปรียบเทียบสเปกและฟังก์ชันแต่ละรุ่น",
    shop_name="MEGATOOL"
):
    from app.ktw_service import get_product_detail, extract_product_images

    CANVAS_SIZE = 1200
    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    BORDER_W = 16
    draw.rectangle([0, 0, CANVAS_SIZE - 1, CANVAS_SIZE - 1], outline=(239, 28, 37, 255), width=BORDER_W)

    font_title = load_font("leelawdb.ttf", 34)
    font_sub = load_font("leelawdb.ttf", 20)
    font_model = load_font("leelawdb.ttf", 20)
    font_model_sub = load_font("leelawdb.ttf", 20)
    font_price = load_font("tahomabd.ttf", 26)
    font_label = load_font("leelawdb.ttf", 20)
    font_val = load_font("leelawdb.ttf", 18)
    font_footer = load_font("leelawdb.ttf", 19)

    # 1. Header (y: 30 to 115)
    header_box = [30, 30, CANVAS_SIZE - 30, 115]
    draw.rounded_rectangle(header_box, radius=18, fill=(15, 23, 42, 255))

    # Clean shop name: remove STORE
    clean_shop_name = re.sub(r'\s*STORE\s*$', '', str(shop_name), flags=re.IGNORECASE).strip()
    shop_str = clean_shop_name
    sb = font_sub.getbbox(shop_str)
    sw = sb[2] - sb[0]
    draw.text((CANVAS_SIZE - 70 - sw, 60), shop_str, font=font_sub, fill=(249, 115, 22, 255))

    # Format concise clean title: e.g. [POLO แท้ 100%] ตารางเปรียบเทียบเครื่องฉีดน้ำแรงดันสูง
    clean_raw = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]', '', str(parent_title)).strip()
    brand_match = re.search(r'\[(.*?)\]', clean_raw)
    if brand_match:
        brand_tag = f"[{brand_match.group(1)}]"
    else:
        first_brand = items[0].get('brand') if items else 'POLO'
        brand_tag = f"[{first_brand} แท้ 100%]" if first_brand else "[ของแท้ 100%]"

    combined_text = clean_raw + ' ' + ' '.join([i.get('name', '') for i in items])
    if 'เครื่องฉีดน้ำ' in combined_text:
        clean_parent_title = f"{brand_tag} ตารางเปรียบเทียบเครื่องฉีดน้ำแรงดันสูง"
    elif 'เครื่องเจียร์' in combined_text or 'ลูกหมู' in combined_text:
        clean_parent_title = f"{brand_tag} ตารางเปรียบเทียบเครื่องเจียร์"
    elif 'สว่าน' in combined_text:
        clean_parent_title = f"{brand_tag} ตารางเปรียบเทียบสว่านไฟฟ้า / สว่านโรตารี่"
    elif 'ปั๊มจุ่ม' in combined_text or 'ไดโว่' in combined_text:
        clean_parent_title = f"{brand_tag} ตารางเปรียบเทียบปั๊มจุ่ม / ปั๊มแช่"
    elif 'เครื่องตัดหญ้า' in combined_text:
        clean_parent_title = f"{brand_tag} ตารางเปรียบเทียบเครื่องตัดหญ้า"
    elif 'ตู้เชื่อม' in combined_text or 'เครื่องเชื่อม' in combined_text:
        clean_parent_title = f"{brand_tag} ตารางเปรียบเทียบเครื่องเชื่อมไฟฟ้า"
    else:
        short_name = re.sub(r'\[.*?\]', '', clean_raw).strip()
        words = short_name.split()
        tool_name = ' '.join(words[:3]) if words else 'สินค้าคุณภาพ'
        clean_parent_title = f"{brand_tag} ตารางเปรียบเทียบ{tool_name}"

    # Dynamic scaling for title to ensure it fits perfectly without truncation
    max_title_w = (CANVAS_SIZE - 70 - sw) - 80
    cur_font_title = font_title
    tb = cur_font_title.getbbox(clean_parent_title)
    tw = tb[2] - tb[0]
    if tw > max_title_w:
        scaled_size = max(22, int(34 * max_title_w / tw))
        cur_font_title = load_font("leelawdb.ttf", scaled_size)
        tb = cur_font_title.getbbox(clean_parent_title)
        tw = tb[2] - tb[0]

    draw.text((60, 42 + (34 - (tb[3] - tb[1])) // 2), clean_parent_title, font=cur_font_title, fill=(255, 255, 255, 255))
    draw.text((60, 82), "ตารางเปรียบเทียบสเปกเพื่อให้คุณเลือกรุ่นที่ตอบโจทย์งานที่สุด", font=font_sub, fill=(203, 213, 225, 255))

    processed_items = []
    all_spec_keys = []
    preferred_order = [
        'ตำแหน่งสวิตช์', 'แรงดันสูงสุด', 'กำลังมอเตอร์', 'ประเภทมอเตอร์', 'ระบบตัดการทำงาน',
        'ขนาดใบตัด/เจียร์', 'ความเร็วรอบ', 'อัตราการไหลของน้ำ', 'ความยาวสายฉีด',
        'ความยาวสายไฟ', 'น้ำหนักตัวเครื่อง'
    ]

    for item in items[:4]:
        sku = item.get('sku')
        detail = get_product_detail(sku)
        specs = extract_key_specs(detail)
        raw_w = (detail.get('warrenty') or detail.get('warranty')) if detail else None
        cleaned_w = clean_warranty(raw_w)
        
        for k in specs.keys():
            if k not in all_spec_keys:
                all_spec_keys.append(k)
        
        # Reliable Image Fetching: use extract_product_images if available
        img_url = item.get('image') or item.get('selected_image')
        if detail:
            imgs = extract_product_images(detail)
            if imgs:
                img_url = imgs[0]
        
        thumb_im = None
        if img_url:
            try:
                raw_im = fetch_image_safe(img_url)
                thumb_im = trim_white_space(raw_im)
            except Exception as e:
                print(f"Error fetching thumb for {sku}:", e)

        raw_name = item.get('name') or item.get('raw_name') or item.get('opt_name') or (detail.get('name') if detail else sku)
        model_code, model_sub = extract_model_label(raw_name, sku, detail=detail)

        raw_price = item.get('price') or item.get('sale_price') or 0
        try:
            parsed_price = float(str(raw_price).replace(',', '').replace('฿', '').strip())
        except Exception:
            parsed_price = 0.0

        processed_items.append({
            'sku': sku,
            'name': raw_name,
            'model_code': model_code,
            'model_sub': model_sub,
            'price': parsed_price,
            'specs': specs,
            'warranty': cleaned_w,
            'thumb': thumb_im
        })

    # Sort specs by preferred order (Exclude 'กำลังไฟฟ้า', include 'ระบบตัดการทำงาน' and 'น้ำหนักตัวเครื่อง')
    all_spec_keys = [k for k in all_spec_keys if k != 'กำลังไฟฟ้า']
    ordered_keys = [k for k in preferred_order if k in all_spec_keys and k != 'กำลังไฟฟ้า']
    for k in all_spec_keys:
        if k not in ordered_keys and k != 'กำลังไฟฟ้า':
            ordered_keys.append(k)
    ordered_keys = ordered_keys[:7]

    if not ordered_keys:
        ordered_keys = ['กำลังไฟฟ้า', 'ความเร็วรอบ / แรงดัน', 'ขนาด / ความจุ', 'น้ำหนักตัวเครื่อง']

    tbl_top = 135
    tbl_bottom = 1115
    tbl_left = 30
    tbl_right = CANVAS_SIZE - 30
    tbl_w = tbl_right - tbl_left

    label_col_w = 260
    num_models = max(1, len(processed_items))
    model_col_w = (tbl_w - label_col_w) // num_models

    draw.rounded_rectangle([tbl_left, tbl_top, tbl_right, tbl_bottom], radius=16, fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), width=2)

    thumb_row_h = 290
    draw.rounded_rectangle([tbl_left, tbl_top, tbl_right, tbl_top + thumb_row_h], radius=16, fill=(248, 250, 252, 255))
    draw.line([tbl_left, tbl_top + thumb_row_h, tbl_right, tbl_top + thumb_row_h], fill=(226, 232, 240, 255), width=2)

    draw.text((tbl_left + 25, tbl_top + 115), "เปรียบเทียบ", font=font_title, fill=(30, 41, 59, 255))
    draw.text((tbl_left + 25, tbl_top + 160), "สเปกแต่ละรุ่น", font=font_label, fill=(100, 116, 139, 255))

    for idx, m in enumerate(processed_items):
        col_x = tbl_left + label_col_w + (idx * model_col_w)
        draw.line([col_x, tbl_top, col_x, tbl_bottom], fill=(226, 232, 240, 255), width=2)

        # 1. Product Thumbnail
        if m['thumb']:
            tw, th = m['thumb'].size
            max_th = 135
            scale = min((model_col_w - 35) / tw, max_th / th)
            new_w = int(tw * scale)
            new_h = int(th * scale)
            r_im = m['thumb'].resize((new_w, new_h), Image.Resampling.LANCZOS)
            px = col_x + (model_col_w - new_w) // 2
            py = tbl_top + 12 + (max_th - new_h) // 2
            canvas.paste(r_im, (px, py), r_im)

        # 2. Model Code Tag (Line 1: Bold Model Name Pill)
        m_code = m['model_code']
        pill_w = min(model_col_w - 16, 220)
        pill_x1 = col_x + (model_col_w - pill_w) // 2
        pill_y1 = tbl_top + 155
        draw.rounded_rectangle([pill_x1, pill_y1, pill_x1 + pill_w, pill_y1 + 32], radius=8, fill=(234, 88, 12, 255))
        
        cur_font_model = font_model
        nb = cur_font_model.getbbox(m_code)
        nw = nb[2] - nb[0]
        if nw > pill_w - 16:
            scaled_size = max(12, int(20 * (pill_w - 20) / nw))
            cur_font_model = load_font("leelawdb.ttf", scaled_size)
            nb = cur_font_model.getbbox(m_code)
            nw = nb[2] - nb[0]
        draw.text((pill_x1 + (pill_w - nw) // 2, pill_y1 + (32 - (nb[3] - nb[1])) // 2), m_code, font=cur_font_model, fill=(255, 255, 255, 255))

        # Line 2: Subtitle / Spec tag (Enlarged & Highlighted in Red Badge as requested)
        if m['model_sub']:
            sub_text = m['model_sub'].strip('()[]')
            sb = font_model_sub.getbbox(sub_text)
            sw = sb[2] - sb[0]
            sh = sb[3] - sb[1]
            
            badge_w = min(model_col_w - 20, sw + 26)
            badge_h = 30
            badge_x = col_x + (model_col_w - badge_w) // 2
            badge_y = tbl_top + 194
            
            # Highlight badge: soft red background with subtle red border
            draw.rounded_rectangle(
                [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
                radius=6,
                fill=(254, 242, 242, 255),
                outline=(248, 113, 113, 255),
                width=1
            )
            cur_font_sub = font_model_sub
            if sw > badge_w - 12:
                scaled_sub_size = max(12, int(20 * (badge_w - 14) / sw))
                cur_font_sub = load_font("leelawdb.ttf", scaled_sub_size)
                sb = cur_font_sub.getbbox(sub_text)
                sw = sb[2] - sb[0]
                sh = sb[3] - sb[1]
                
            draw.text(
                (badge_x + (badge_w - sw) // 2, badge_y + (badge_h - sh) // 2 - 1),
                sub_text,
                font=cur_font_sub,
                fill=(220, 38, 38, 255)
            )

        # Price (only draw if price > 0, otherwise skip cleanly without showing an empty '-' dash)
        if m['price'] and m['price'] > 0:
            price_str = f"฿{m['price']:,.0f}"
            pb = font_price.getbbox(price_str)
            pw = pb[2] - pb[0]
            draw.text((col_x + (model_col_w - pw) // 2, tbl_top + 235), price_str, font=font_price, fill=(239, 28, 37, 255))

    rows_h = (tbl_bottom - (tbl_top + thumb_row_h))
    row_count = len(ordered_keys) + 1
    row_h = rows_h // row_count

    for r_idx, key in enumerate(ordered_keys):
        ry1 = tbl_top + thumb_row_h + (r_idx * row_h)
        ry2 = ry1 + row_h
        
        # Check if values in this row are DIFFERENT across models (key differentiator!)
        row_vals = [m['specs'].get(key, "-") for m in processed_items]
        non_empty_vals = [v for v in row_vals if v and v != "-"]
        is_diff_row = len(set(non_empty_vals)) > 1
        
        if is_diff_row:
            bg_color = (254, 242, 242, 255)
        else:
            bg_color = (255, 255, 255, 255) if r_idx % 2 == 0 else (248, 250, 252, 255)
            
        draw.rectangle([tbl_left + 2, ry1, tbl_right - 2, ry2], fill=bg_color)
        draw.line([tbl_left, ry2, tbl_right, ry2], fill=(226, 232, 240, 255), width=1)

        label_color = (220, 38, 38, 255) if is_diff_row else (51, 65, 85, 255)
        draw.text((tbl_left + 25, ry1 + (row_h - 22) // 2), f"• {key}", font=font_label, fill=label_color)

        for idx, m in enumerate(processed_items):
            col_x = tbl_left + label_col_w + (idx * model_col_w)
            val = m['specs'].get(key, "-")
            
            # Dynamic fitting: do not arbitrarily cut with len > 28
            max_val_w = model_col_w - 20
            cur_font_val = font_val
            vb = cur_font_val.getbbox(val)
            vw = vb[2] - vb[0]
            
            # If text is wider than column, scale down font first so full text is visible
            if vw > max_val_w:
                scaled_size = max(13, int(20 * (max_val_w - 8) / vw))
                cur_font_val = load_font("leelawdb.ttf", scaled_size)
                vb = cur_font_val.getbbox(val)
                vw = vb[2] - vb[0]
                
            # Only truncate if it still exceeds after scaling down to minimum size
            if vw > max_val_w:
                while len(val) > 4 and vw > max_val_w:
                    val = val[:-2] + ".."
                    vb = cur_font_val.getbbox(val)
                    vw = vb[2] - vb[0]
                    
            val_color = (220, 38, 38, 255) if is_diff_row else (15, 23, 42, 255)
            vh = vb[3] - vb[1]
            draw.text((col_x + (model_col_w - vw) // 2, ry1 + (row_h - vh) // 2 - 1), val, font=cur_font_val, fill=val_color)

    last_ry1 = tbl_top + thumb_row_h + (len(ordered_keys) * row_h)
    draw.rectangle([tbl_left + 2, last_ry1, tbl_right - 2, tbl_bottom - 2], fill=(241, 245, 249, 255))
    draw.text((tbl_left + 25, last_ry1 + (row_h - 22) // 2), "• การรับประกันศูนย์", font=font_label, fill=(51, 65, 85, 255))
    for idx, m in enumerate(processed_items):
        col_x = tbl_left + label_col_w + (idx * model_col_w)
        w_text = m.get('warranty') or "ของแท้ 100% ประกันศูนย์"
        cur_w_font = font_val
        wb = cur_w_font.getbbox(w_text)
        ww = wb[2] - wb[0]
        if ww > model_col_w - 20:
            scaled_w_size = max(13, int(20 * (model_col_w - 28) / ww))
            cur_w_font = load_font("leelawdb.ttf", scaled_w_size)
            wb = cur_w_font.getbbox(w_text)
            ww = wb[2] - wb[0]
        wh = wb[3] - wb[1]
        draw.text((col_x + (model_col_w - ww) // 2, last_ry1 + (row_h - wh) // 2 - 1), w_text, font=cur_w_font, fill=(16, 185, 129, 255))

    for idx in range(num_models):
        col_x = tbl_left + label_col_w + (idx * model_col_w)
        draw.line([col_x, tbl_top + thumb_row_h, col_x, tbl_bottom], fill=(226, 232, 240, 255), width=2)

    footer_box = [30, 1130, CANVAS_SIZE - 30, 1175]
    draw.rounded_rectangle(footer_box, radius=12, fill=(241, 245, 249, 255))
    footer_text = f"{clean_shop_name} • สินค้าของแท้ 100% พร้อมจัดส่งด่วน • มีศูนย์บริการรองรับมาตรฐานสากล"
    ft_b = font_footer.getbbox(footer_text)
    ft_w = ft_b[2] - ft_b[0]
    draw.text(((CANVAS_SIZE - ft_w) // 2, 1142), footer_text, font=font_footer, fill=(71, 85, 105, 255))

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    canvas.convert('RGB').save(output_path, "JPEG", quality=98, subsampling=0, optimize=True)
    return output_path
