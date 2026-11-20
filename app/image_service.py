import os
import io
import gc
import json
import time
import re
import math
import functools
import collections
import requests
from requests.adapters import HTTPAdapter
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageChops

_IMG_HTTP_SESSION = requests.Session()
_img_adapter = HTTPAdapter(pool_connections=25, pool_maxsize=25)
_IMG_HTTP_SESSION.mount("https://", _img_adapter)
_IMG_HTTP_SESSION.mount("http://", _img_adapter)

@functools.lru_cache(maxsize=64)
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

try:
    from PIL import features as _pil_features
    HAS_RAQM = bool(_pil_features.check("raqm"))
except Exception:
    HAS_RAQM = False

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
    """draw.text() replacement: uses native HarfBuzz (libraqm) GPOS Thai shaping when available (Linux/Render),
    and falls back to manual stacked tone-mark raising only when libraqm is unavailable (Windows)."""
    if HAS_RAQM:
        draw.text(xy, text, font=font, fill=fill, anchor=anchor)
        return
    stripped, marks = _thai_split_stacked(text)
    draw.text(xy, stripped, font=font, fill=fill, anchor=anchor)
    if marks:
        lift = font.size * lift_ratio
        for idx, mk in marks:
            pen = font.getlength(stripped[:idx])
            draw.text((xy[0] + pen, xy[1] - lift), mk, font=font, fill=fill, anchor=anchor)


AUTO_SPEC_TYPO_VER = "v6hd"

PROMPT_FILES = {
    "regular": "Prompt-Regular.ttf",
    "medium": "Prompt-Medium.ttf",
    "semibold": "Prompt-SemiBold.ttf",
    "bold": "Prompt-Bold.ttf",
}

# Ultra-crisp Auto-Spec typography (Leelawadee UI Bold/Regular — open counters, zero Thai tone collision, identical on Windows & Linux)
AUTO_SPEC_FONTS = {
    "regular": "leelawad.ttf",
    "medium": "leelawdb.ttf",
    "semibold": "leelawdb.ttf",
    "bold": "leelawdb.ttf",
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
    """Width in logical 1200p px of text rendered with the Ultra-Crisp Auto-Spec font (same on Windows & Linux)."""
    f = load_font(AUTO_SPEC_FONTS.get(weight, "leelawdb.ttf"), int(round(size * 4)))
    return f.getlength(text) / 4.0


def draw_hq(canvas, text, x, baseline, weight="semibold", size=30, color=(0, 0, 0)):
    """Draw Thai/Latin text for Auto-Spec at maximum sharpness (4x supersampled -> exact BOX area-averaging).
    Eliminates UnsharpMask halos and LUT stroke bloating so characters remain razor-sharp at both 2400px Ultra-HD and mobile screens.
    (x, baseline, size) are in logical 1200p coordinates and automatically scale to canvas resolution (e.g. 2400x2400)."""
    if not text:
        return 0
    hd_scale = canvas.width / 1200.0
    real_x = x * hd_scale
    real_baseline = baseline * hd_scale
    real_size = max(8, int(round(size * hd_scale)))

    S = 4
    f = load_font(AUTO_SPEC_FONTS.get(weight, "leelawdb.ttf"), real_size * S)
    stripped_t, _mk = (text, []) if HAS_RAQM else _thai_split_stacked(text)
    bb = f.getbbox(stripped_t, anchor="ls")
    if _mk or HAS_RAQM:
        bb = (bb[0], min(bb[1], bb[1] - int(real_size * 0.45 * S)), bb[2], bb[3])
    pad = 8
    ox = ((-bb[0]) // S + pad + 1) * S
    oy = ((-bb[1]) // S + pad + 1) * S
    w = ox + (bb[2] // S + pad + 2) * S
    h = oy + (bb[3] // S + pad + 2) * S
    layer = Image.new("L", (w, h), 0)
    _draw_thai_text(ImageDraw.Draw(layer), (ox, oy), text, f, 255, anchor="ls", lift_ratio=0.22)
    # Exact 4x4 subpixel BOX area-averaging: razor-sharp stems, smooth curves, zero halo ringing or stroke bloat
    a = layer.resize((w // S, h // S), Image.Resampling.BOX)
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
    """Split text into 2 clean, balanced lines (prefers ' / ', before '(', or after ', ' so ranges never break awkwardly)."""
    text = str(text or "").strip()
    if " / " in text:
        parts = [p.strip() for p in text.split(" / ") if p.strip()]
        if len(parts) >= 2:
            mid = len(parts) // 2
            return " / ".join(parts[:mid]), " / ".join(parts[mid:])
    if "(" in text and text.index("(") > 0:
        i = text.index("(")
        return text[:i].strip(), text[i:].strip()
    if ", " in text:
        chunks = [c.strip() for c in text.split(", ") if c.strip()]
        if len(chunks) >= 2:
            best_c = min(
                range(1, len(chunks)),
                key=lambda k: abs(len(", ".join(chunks[:k]) + ",") - len(", ".join(chunks[k:])))
            )
            l1 = ", ".join(chunks[:best_c]) + ","
            l2 = ", ".join(chunks[best_c:])
            if min(len(l1), len(l2)) >= max(len(l1), len(l2)) * 0.35:
                return l1, l2
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
    """Ultra-fast exterior border floodfill (~45x faster than Python pixel BFS):
    floodfills exterior white background at ~240px and intersects with full-resolution white mask
    for pixel-exact silhouettes while protecting white interiors & blister packs."""
    img = img.convert('RGBA')
    w, h = img.size
    r, g, b, _ = img.split()
    min_rgb = ImageChops.darker(ImageChops.darker(r, g), b)
    full_white = min_rgb.point(lambda v: 255 if v >= threshold else 0, mode='L')

    scale = max(1, max(w, h) // 240)
    if scale > 1:
        sw, sh = max(1, w // scale), max(1, h // scale)
        small_white = full_white.resize((sw, sh), Image.Resampling.BOX).point(lambda v: 255 if v >= 245 else 0, mode='L')
        padded = Image.new('L', (sw + 2, sh + 2), 255)
        padded.paste(small_white, (1, 1))
        ImageDraw.floodfill(padded, (0, 0), 128, thresh=0)
        small_ext = padded.crop((1, 1, sw + 1, sh + 1)).point(lambda v: 255 if v == 128 else 0, mode='L')
        small_ext = small_ext.filter(ImageFilter.MaxFilter(5))
        ext_full = small_ext.resize((w, h), Image.Resampling.BILINEAR).point(lambda v: 255 if v > 64 else 0, mode='L')
        bg_mask = ImageChops.darker(ext_full, full_white)
    else:
        padded = Image.new('L', (w + 2, h + 2), 255)
        padded.paste(full_white, (1, 1))
        ImageDraw.floodfill(padded, (0, 0), 128, thresh=0)
        bg_mask = padded.crop((1, 1, w + 1, h + 1)).point(lambda v: 255 if v == 128 else 0, mode='L')

    alpha = ImageChops.invert(bg_mask)
    img.putalpha(alpha)

    # Clean isolated noise specks from alpha mask before computing bounding box
    alpha_clean = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    bbox = alpha_clean.getbbox()
    if bbox:
        return img.crop(bbox)
    bbox_raw = alpha.getbbox()
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
    box_left = 388 * hd_s
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
    while len(_HERO_PRODUCT_CACHE) > 3:
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
    s_low = (shop_name or "").strip().lower()
    is_bigpower = bool(s_low and ('bigpower' in s_low or 'big power' in s_low or 'shop2' in s_low or 'shop_2' in s_low))
    is_mega = not is_bigpower and (not s_low or 'mega' in s_low or 'zonix' in s_low or 'shop1' in s_low or 'shop_1' in s_low)
    if is_bigpower:
        official_shop_name = "BIGPOWER TOOLS"
    elif is_mega:
        official_shop_name = "MEGATOOL"
    else:
        official_shop_name = shop_name.strip()

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

            max_box_w = 264 * HD_S
            max_box_h = (76 if ratio >= 1.6 else 82) * HD_S
            target_area = (15500 if ratio >= 1.6 else 11800) * (HD_S * HD_S)
            scale_area = math.sqrt(target_area / (bw * bh))
            b_scale = min(scale_area, max_box_w / bw, max_box_h / bh)

            if bh * b_scale < 52 * HD_S and bw * ((52 * HD_S) / bh) <= max_box_w:
                b_scale = (52 * HD_S) / bh

            tgt_bw = max(1, int(bw * b_scale))
            tgt_bh = max(1, int(bh * b_scale))
            brand_logo = b_img.resize((tgt_bw, tgt_bh), Image.Resampling.LANCZOS)

            logo_y = 32 * HD_S + (74 * HD_S - tgt_bh) // 2
            canvas.paste(brand_logo, (44 * HD_S, logo_y), brand_logo)
        except Exception as e:
            print(f"Error placing brand logo: {e}")

    # Approved Style 2B: Razor-sharp Pure Jet-Black headings > Deep Slate-Charcoal answers across ALL shops (MEGATOOL, BigPower Tools, future shops)
    TEXT_LABEL = (0, 0, 0)
    TEXT_VAL = (55, 65, 81)
    trust_s1_color = theme_rgb if is_bigpower else (0, 0, 0)
    trust_s2_color = TEXT_VAL

    DIVIDER_COLOR = (205, 210, 218, 255)
    WHITE = (255, 255, 255, 255)
    COL_L = 44
    COL_R = 376   # clean balanced left column (product starts safely at x >= 388, zero overlap)
    max_text_w = COL_R - COL_L

    # --- Title (category): smart pixel-scan of pure white canvas space in the title band ---
    # ONLY the product category title may extend into guaranteed white space to the right (never touching product pixels, shop logo, or spec cards)
    def _find_title_white_right_limit(cv, hd_s, y0_1200=120, y1_1200=198, min_r=384, max_r=860):
        try:
            x0 = int(min_r * hd_s)
            x1 = int(max_r * hd_s)
            y0 = int(y0_1200 * hd_s)
            y1 = int(y1_1200 * hd_s)
            strip = cv.crop((x0, y0, x1, y1)).convert('RGB')
            r_c, g_c, b_c = strip.split()
            min_rgb = ImageChops.darker(ImageChops.darker(r_c, g_c), b_c)
            nonwhite = min_rgb.point(lambda v: 255 if v < 242 else 0, mode='L')
            bb = nonwhite.getbbox()
            if not bb:
                return max_r
            first_obs_1200 = min_r + (bb[0] / float(hd_s))
            return max(min_r, min(max_r, int(first_obs_1200) - 24))
        except Exception:
            return min_r

    title_right_r = _find_title_white_right_limit(canvas, HD_S, y0_1200=120, y1_1200=198, min_r=384, max_r=860)
    title_w_limit = title_right_r - COL_L
    t_sz, _tw = fit_hq(category_title, "bold", 54, 36, title_w_limit)
    if t_sz < 42 and ' ' in category_title:
        # Even if wrapping to 2 lines, scan white space across the 2-line band (y=120..238)
        title_2l_r = _find_title_white_right_limit(canvas, HD_S, y0_1200=120, y1_1200=238, min_r=384, max_r=660)
        title_2l_w = title_2l_r - COL_L
        tl1, tl2 = split_two_lines(category_title)
        s1, _ = fit_hq(tl1, "bold", 46, 36, title_2l_w)
        s2, _ = fit_hq(tl2, "bold", 46, 36, title_2l_w)
        tsz2 = min(s1, s2)
        draw_hq(canvas, tl1, COL_L, 174, "bold", tsz2, TEXT_LABEL)
        draw_hq(canvas, tl2, COL_L, 174 + int(round(tsz2 * 1.16)), "bold", tsz2, TEXT_LABEL)
        pill_top = 174 + int(round(tsz2 * 1.16)) + 16
    else:
        t_sz1, _ = fit_hq(category_title, "bold", 54, 34, title_w_limit)
        draw_hq(canvas, category_title, COL_L, 178, "bold", t_sz1, TEXT_LABEL)
        pill_top = 200

    # --- Model pill (balanced Option 2 sizing) ---
    pill_h = 64
    m_sz, m_w = fit_hq(model_name, "bold", 36, 20, max_text_w - 26)
    pill_w = min(max_text_w, int(m_w) + 28)
    draw_aa_rounded_rect(canvas, [COL_L, pill_top, COL_L + pill_w, pill_top + pill_h], radius=12, fill=theme_color)
    draw_hq(canvas, model_name, COL_L + (pill_w - m_w) / 2.0, pill_top + pill_h // 2 + int(m_sz * 0.35), "bold", m_sz, (255, 255, 255))

    # --- Highlight sub-pills (enlarged clear key feature badges under model pill) ---
    curr_y = pill_top + pill_h + 13
    sub_bg = (238, 244, 252, 255) if is_bigpower else (255, 238, 239, 255)
    sub_border = (170, 194, 224, 255) if is_bigpower else (250, 165, 168, 255)

    clean_pills = []
    for hp in hero_pills[:2]:
        hp_clean = hp.strip()
        if ',' in hp_clean and len(hp_clean) > 28:
            hp_clean = hp_clean.split(',')[0].strip()
        if len(hp_clean) > 36:
            hp_clean = hp_clean[:35].rstrip(' ,-/')
        clean_pills.append(hp_clean)

    for hp in clean_pills:
        hp_sz, hp_w = fit_hq(hp, "bold", 29, 20, max_text_w - 18)
        ph = 48
        bw_ = min(max_text_w, int(hp_w) + 22)
        draw_aa_rounded_rect(canvas, [COL_L, curr_y, COL_L + bw_, curr_y + ph], radius=9, fill=sub_bg, outline=sub_border, width=2)
        draw_hq(canvas, hp, COL_L + (bw_ - hp_w) / 2.0, curr_y + ph // 2 + int(hp_sz * 0.35), "bold", hp_sz, TEXT_LABEL)
        curr_y += ph + 8

    # --- Spec rows (Style 2B: Label 31 Pure Black > Value 25 Slate Charcoal, balanced airy spacing) ---
    spec_top = curr_y + 12
    n_rows = max(1, len(spec_cards[:4]))
    trust_card_h = 86
    bottom_limit = COVER_SAFE_BOTTOM - 4
    avail = bottom_limit - spec_top - trust_card_h - 14
    spec_row_h = max(100, min(132, avail // n_rows))

    hex_radius = 24
    hex_center_x = COL_L + hex_radius
    hex_fill = (18, 56, 88, 255) if is_bigpower else (215, 25, 33, 255)
    text_x = hex_center_x + hex_radius + 13
    val_max_w = COL_R - text_x

    # Clear typographic hierarchy: Heading (Label) is always larger & darker than Answer (Value)
    STD_LABEL_SZ = 31
    STD_VAL_SZ = 25
    STD_VAL_2LINE_SZ = 23

    for idx, sp in enumerate(spec_cards[:4]):
        r_y = spec_top + idx * spec_row_h
        h_cy = r_y + spec_row_h // 2 - 2

        draw_smooth_hexagon(canvas, hex_center_x, h_cy, hex_radius, fill_color=hex_fill, icon_str=sp.get('icon', '⚡'))

        lbl = sp.get('label', '')
        val = sp.get('val', '')
        if 'รอบ/นาที' in val and val.count('รอบ/นาที') > 1:
            speeds = [s.strip() for s in re.split(r',\s+(?=\d)', val) if s.strip()]
            if len(speeds) >= 2:
                val = f"{speeds[0]} / {speeds[-1]}"

        l_sz, _ = fit_hq(lbl, "bold", STD_LABEL_SZ, 25, val_max_w)
        val_cap_1 = min(STD_VAL_SZ, l_sz - 5)
        v_sz, v_w = fit_hq(val, "bold", val_cap_1, 21, val_max_w)
        if v_w <= val_max_w and v_sz >= 21:
            draw_hq(canvas, lbl, text_x, h_cy - 6, "bold", l_sz, TEXT_LABEL)
            draw_hq(canvas, val, text_x, h_cy + int(v_sz * 1.15) + 4, "bold", v_sz, TEXT_VAL)
        else:
            ln1, ln2 = split_two_lines(val)
            val_cap_2 = min(STD_VAL_2LINE_SZ, l_sz - 5)
            sz1, _ = fit_hq(ln1, "bold", val_cap_2, 18, val_max_w)
            sz2, _ = fit_hq(ln2, "bold", val_cap_2, 18, val_max_w) if ln2 else (val_cap_2, 0)
            v2_sz = min(sz1, sz2)
            line_step = int(round(v2_sz * 1.26))
            draw_hq(canvas, lbl, text_x, h_cy - 22, "bold", l_sz, TEXT_LABEL)
            draw_hq(canvas, ln1, text_x, h_cy + 10, "bold", v2_sz, TEXT_VAL)
            if ln2:
                draw_hq(canvas, ln2, text_x, h_cy + 10 + line_step, "bold", v2_sz, TEXT_VAL)

        div_y = r_y + spec_row_h - 2
        draw.line([(COL_L * HD_S, div_y * HD_S), (COL_R * HD_S, div_y * HD_S)], fill=DIVIDER_COLOR, width=2 * HD_S)

    # --- Trust card ---
    trust_card_y = spec_top + n_rows * spec_row_h + 14
    trust_card_w = COL_R + 8 - COL_L
    card_bg = (247, 250, 253, 255) if is_bigpower else (255, 246, 246, 255)
    card_outline = (206, 218, 234, 255) if is_bigpower else (250, 205, 207, 255)
    draw_aa_rounded_rect(canvas, [COL_L, trust_card_y, COL_L + trust_card_w, trust_card_y + trust_card_h], radius=12, fill=card_bg, outline=card_outline, width=2)

    shield_cx = COL_L + 28
    shield_cy = trust_card_y + trust_card_h // 2
    draw_vector_shield(canvas, shield_cx, shield_cy, size=38, fill_color=theme_rgb)

    trust_txt_x = COL_L + 56
    tr_max_w = COL_L + trust_card_w - 10 - trust_txt_x
    s1_sz, _ = fit_hq(trust_s1, "bold", 24, 18, tr_max_w)
    s2_sz, _ = fit_hq(trust_s2, "bold", 20, 16, tr_max_w)
    draw_hq(canvas, trust_s1, trust_txt_x, trust_card_y + int(trust_card_h * 0.43), "bold", s1_sz, trust_s1_color)
    draw_hq(canvas, trust_s2, trust_txt_x, trust_card_y + int(trust_card_h * 0.78), "bold", s2_sz, trust_s2_color)

    final_rgb = canvas.convert('RGB')
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    final_rgb.save(output_path, "JPEG", quality=98, subsampling=0, optimize=True)
    try:
        final_rgb.close()
        canvas.close()
    except Exception:
        pass
    gc.collect()
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
                    while len(_RAW_IMG_CACHE) > 3:
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

def _clean_spec_label(raw_name):
    """Normalize SAP / KTW feature label into concise, natural Thai for spec cards."""
    s = str(raw_name or "").strip()
    s = re.sub(r'^[\d\.\)\-\•\*▪▫\s]+', '', s).strip()
    # Strip trailing parenthetical units like (ตัน), (ฟุต), (มม.), (เมตร), (กก.), (ลิตร/นาที), (โวลต์)
    s = re.sub(r'\s*\([^)]*(?:มม|ซม|เมตร|นิ้ว|ฟุต|ตัน|กก|กรัม|ลิตร|มล|โวลต์|วัตต์|กิโลวัตต์|แอมป์|รอบ|บาร์|เฟส|องศา|แรงม้า|mm|cm|kg|kw|kv|v|w|a|l|bar|rpm|hp|ton|ล่าง|บน)[^)]*\)', '', s, flags=re.I)
    # Strip trailing single engineering dimension code letters like " H", " B2", " L1" after Thai text
    s = re.sub(r'(?<=[\u0E00-\u0E7F])\s+[A-Z]\d?$', '', s).strip()
    s = s.replace('สูงสูด', 'สูงสุด').replace('เส้นผ่าศูนย์กลาง', 'เส้นผ่านศูนย์กลาง')
    s = re.sub(r'\s+', ' ', s).strip(' :-–—')
    return s


def _clean_spec_value(raw_val):
    """Normalize common unit abbreviations and trim whitespace in spec card values."""
    v = str(raw_val or "").strip()
    # If KTW concatenated two "label: value" pairs on one line, keep only the first clean value
    if ':' in v or '：' in v:
        m_two = re.search(r'\s+[\u0E00-\u0E7F]{2,}\s*[:：]', v)
        if m_two:
            v = v[:m_two.start()].strip()
    v = re.sub(r'\s+', ' ', v)
    v = re.sub(r'\bMM\b\.?', 'มม.', v)
    v = re.sub(r'\bCM\b\.?', 'ซม.', v, flags=re.I)
    v = re.sub(r'\bML\b\.?', 'มล.', v, flags=re.I)
    v = re.sub(r'\bKPA\b', 'kPa', v)
    v = re.sub(r'\bTON\b', 'ตัน', v, flags=re.I)
    v = re.sub(r'\.{2,}', '.', v)
    v = re.sub(r'(\d)\s*x\s*(\d)', r'\1 x \2', v, flags=re.I)
    if v == 'ไม่รวมแบตเตอรี่และแท่นชาร์จ':
        v = 'ไม่รวมแบตและแท่นชาร์จ'
    return v.strip(' ,;-')


_SPEC_NOISE_KEYS = (
    'สารบัญ', 'หมวดหมู่', 'ยี่ห้อ', 'แบรนด์', 'brand', 'manufacturer',
    'รุ่น', 'model', 'รหัส', 'sku', 'บาร์โค้ด', 'barcode', 'สี', 'color',
    'ประเทศ', 'origin', 'บรรจุภัณฑ์', 'packaging', 'อุปกรณ์มาตรฐาน', 'อุปกรณ์เสริม',
    'สัมประสิทธิ', 'ไร้ภาระ', 'no-load', 'กล่อง', 'หมายเลข', 'เงื่อนไข',
    'หมายเหตุ', 'น้ำหนักรวม', 'ประกัน', 'แถม', 'บริการ', 'คำเตือน', 'ข้อควรระวัง',
    'ขนาดกล่อง', 'กว้าง x ยาว x สูง'
)


def _is_noise_spec_key(label):
    lk = str(label or "").strip().lower()
    if not lk or len(lk) < 2 or len(lk) > 32:
        return True
    return any(nk in lk for nk in _SPEC_NOISE_KEYS)


def extract_key_specs(detail):
    specs = {}
    if not detail:
        return specs

    # 1. Layer 1: Universal SAP Classifications Harvester (canonical mapping + generic catch-all for ALL KTW categories)
    classifs = detail.get('classifications', []) or []
    dim_l, dim_w, dim_h = None, None, None
    for c in classifs:
        for f in c.get('features', []):
            name = (f.get('name') or f.get('description') or '').strip()
            code = f.get('code', '') or ''
            vals = f.get('featureValues', []) or []
            val_str = _clean_spec_value(', '.join([str(v.get('value', '')).strip() for v in vals if v.get('value')]))
            if not name or not val_str or val_str in ('-', 'N/A', 'n/a', 'None'):
                continue
            if 'current_range' in code or 'กระแสไฟเชื่อม' in name:
                specs['กระแสไฟเชื่อม'] = val_str
            elif 'wire_size' in code or 'ขนาดลวด' in name:
                specs['ขนาดลวดเชื่อม'] = val_str
            elif 'no-load' in code or 'ไร้ภาระ' in name:
                pass  # Skip no-load voltage from replacing operating voltage
            elif 'กำลังมอเตอร์' in name or 'motor_power' in code:
                specs['กำลังมอเตอร์'] = val_str
            elif 'แรงดันไฟในการเชื่อม' in name:
                specs['แรงดันไฟเชื่อม'] = val_str
            elif 'voltage' in code or 'แรงดันไฟ' in name:
                if 'แรงดันไฟฟ้า' not in specs or '220' in val_str:
                    specs['แรงดันไฟฟ้า'] = val_str
            elif 'กำลังไฟ' in name or 'power_phase' in code or 'continuous_rating' in code:
                if 'เฟส' not in name:
                    specs['กำลังไฟฟ้า'] = val_str
            elif 'ความเร็วรอบ' in name or 'no_load_speed' in code:
                specs['ความเร็วรอบ'] = val_str
            elif 'เส้นผ่านศูนย์กลาง' in name or 'grinding_diameter' in code:
                specs['ขนาดใบตัด/เจียร์'] = val_str
            elif 'น้ำหนัก' in name or 'weight' in code:
                if 'กล่อง' not in name and 'รวม' not in name:
                    specs['น้ำหนักตัวเครื่อง'] = val_str
            elif 'ขนาดแกน' in name or 'spindle' in code:
                specs['ขนาดแกนเกลียว'] = val_str
            elif 'สายไฟ' in name or 'cord' in code:
                specs['ความยาวสายไฟ'] = val_str
            elif ('แรงดัน' in name or 'pressure' in code) and 'ไฟ' not in name and 'สาย' not in name:
                specs['แรงดันสูงสุด'] = val_str
            elif 'อัตราการไหล' in name or 'ปริมาณน้ำ' in name or 'flow_rate' in code:
                specs['อัตราการไหลของน้ำ'] = val_str
            elif 'ความสามารถในการเจาะ' in name:
                if 'คอนกรีต' in name:
                    specs['เจาะคอนกรีตสูงสุด'] = val_str
                elif 'เหล็ก' in name:
                    specs['เจาะเหล็กสูงสุด'] = val_str
                elif 'ไม้' in name:
                    specs['เจาะไม้สูงสุด'] = val_str
                elif 'อิฐ' in name or 'ปูน' in name:
                    specs['เจาะอิฐสูงสุด'] = val_str
                else:
                    specs['ขนาดการเจาะ'] = val_str
            elif 'step_drill' in code or 'เจาะคว้าน' in name:
                specs['ขนาดการเจาะ'] = val_str
            elif 'grade' in code or 'เกรด' in name:
                specs['เกรดวัสดุ'] = val_str
            elif 'applications_drill' in code or 'วัสดุที่เจาะ' in name:
                specs['วัสดุที่เจาะได้'] = val_str
            elif 'overall_length' in code or 'ความยาวรวม' in name:
                specs['ความยาวรวม'] = val_str
            elif 'torque' in code or 'แรงบิด' in name:
                specs['แรงบิดสูงสุด'] = val_str
            elif 'การป้องกัน' in name or 'ip code' in name.lower() or 'ip_code' in code.lower():
                specs['มาตรฐานป้องกัน (IP)'] = val_str
            elif 'ประสิทธิภาพ' in name and '%' in val_str:
                specs['ประสิทธิภาพ'] = val_str
            elif 'ฉนวน' in name:
                specs['ระดับฉนวน'] = f"Class {val_str}" if len(val_str.strip()) <= 2 else val_str
            elif 'ความถี่' in name:
                specs['ความถี่ไฟฟ้า'] = val_str
            elif 'ความยาว' in name and not any(w in name for w in ['สาย', 'เพลา', 'บาร์', 'รวม', 'บันได']):
                m_num = re.search(r'([\d\.]+)', val_str)
                if m_num: dim_l = m_num.group(1)
            elif 'ความกว้าง' in name and 'บันได' not in name and 'หน้า' not in name:
                m_num = re.search(r'([\d\.]+)', val_str)
                if m_num: dim_w = m_num.group(1)
            elif 'ความสูง' in name and not any(w in name for w in ['บันได', 'ต่ำสุด', 'มากสุด', 'สูงสุด', 'ยก']):
                m_num = re.search(r'([\d\.]+)', val_str)
                if m_num: dim_h = m_num.group(1)
            else:
                # Universal catch-all: harvest ANY real category-specific SAP spec (ladders, jacks, pumps, compressors, saws, etc.)
                clean_lbl = _clean_spec_label(name)
                if (
                    clean_lbl
                    and not _is_noise_spec_key(clean_lbl)
                    and clean_lbl not in specs
                    and len(val_str) <= 46
                    and not re.match(r'^1\s*(?:ชิ้น|อัน|เครื่อง|ชุด)$', val_str)
                ):
                    specs[clean_lbl] = val_str
    if dim_l and dim_w and dim_h and 'ขนาดตัวเครื่อง' not in specs:
        specs['ขนาดตัวเครื่อง'] = f"{dim_l} x {dim_w} x {dim_h} มม."

    # 2. Layer 2: KTW Summary & Title Extraction (universal technical units across all tool families)
    summary_text = f"{detail.get('summary', '') or ''} {detail.get('name', '') or ''}".strip()
    desc = detail.get('description', '') or ''
    clean_desc = re.sub(r'<br\s*/?>', '\n', desc, flags=re.IGNORECASE)
    clean_desc = re.sub(r'</p>', '\n', clean_desc, flags=re.IGNORECASE)
    clean_desc = re.sub(r'<[^>]+>', '', clean_desc)
    prod_full_name = detail.get('name', '') or ''
    full_text = (prod_full_name + ' ' + summary_text + ' ' + clean_desc).replace('สวิทซ์', 'สวิทช์').replace('สวิตซ์', 'สวิทช์').replace('สวิตช์', 'สวิทช์')
    full_lower = full_text.lower()

    is_tape_or_consumable = any(k in full_lower for k in ['เทป', 'temflex', 'scotch', 'กาว', 'สายรัด', 'น้ำยา', 'ซิลิโคน', 'ถุงมือ', 'หน้ากาก', 'แว่นตา', 'ใบมีด'])
    is_cordless = any(k in full_lower for k in ['ไร้สาย', 'แบตเตอรี่', 'ไม่แบต', 'ไม่รวมแบต', 'vmax', 'cordless']) or bool(re.search(r'\b(?:12|14\.4|18|20|36|40|80)\s*v(?:max)?\b', prod_full_name + ' ' + summary_text, re.I))
    is_engine = any(k in full_lower for k in ['จังหวะ', 'เบนซิน', 'ดีเซล', 'เครื่องยนต์', 'แรงม้า', 'ตัดหญ้า', 'เลื่อยโซ่ยนต์', 'เครื่องปั่นไฟ'])

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
            else:
                m_kw = re.search(r'([0-9,]+(?:\.\d+)?)\s*(?:กิโลวัตต์|KW\b|kW\b)', summary_text)
                if m_kw:
                    specs['กำลังไฟฟ้า'] = f"{m_kw.group(1)} กิโลวัตต์"
        if 'แรงดันไฟฟ้า' not in specs and 'แรงดันแบตเตอรี่' not in specs:
            m_vol = re.search(r'แรงดันไฟ(?:ฟ้า)?\s*[:：]?\s*([0-9\-\.\s]+(?:\s*โวลต์|V\b))', summary_text, re.IGNORECASE)
            if m_vol:
                specs['แรงดันแบตเตอรี่' if is_cordless else 'แรงดันไฟฟ้า'] = m_vol.group(1).strip()
            elif is_cordless:
                m_bv = re.search(r'(\d+(?:\.\d+)?)\s*(?:โวลต์|V(?:MAX|max)?\b)', summary_text)
                if m_bv:
                    specs['แรงดันแบตเตอรี่'] = f"{m_bv.group(1)} โวลต์"
        if 'อัตราการไหลของน้ำ' not in specs:
            m_flw = re.search(r'(?:ปริมาณน้ำ|อัตราการไหล(?:ของน้ำ)?)\s*[:：]?\s*([0-9\-\.\s]+(?:\s*ลิตร\/นาที|L\/min))', summary_text, re.IGNORECASE)
            if m_flw:
                specs['อัตราการไหลของน้ำ'] = m_flw.group(1).strip()
        if 'ระยะส่งสูงสุด' not in specs:
            m_hd = re.search(r'(?:ส่งสูง(?:สุด)?|ระยะส่งสูงสุด)\s*[:：]?\s*([0-9\-\.\s]+(?:\s*ม\.|เมตร))', summary_text, re.IGNORECASE)
            if m_hd:
                specs['ระยะส่งสูงสุด'] = m_hd.group(1).strip()
        if 'ขนาดท่อส่ง' not in specs and 'ขนาดท่อออก' not in specs:
            m_pip = re.search(r'ขนาดท่อ(?:ที่ใช้ได้|ส่งออก|ออก)?\s*[:：]?\s*([^,\(\)\n]+?(?:นิ้ว|หุน|มม\.))', summary_text, re.IGNORECASE)
            if m_pip:
                specs['ขนาดท่อส่ง'] = m_pip.group(1).strip()
        if 'ขนาดการเจาะ' not in specs and not any(k.startswith('เจาะ') for k in specs):
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
            m_rpm = re.search(r'ความเร็วรอบ(?:ตัวเปล่า)?\s*[:：]?\s*([0-9,]+(?:\s*-\s*[0-9,]+)?\s*(?:รอบ\/นาที|รอบต่อนาที|RPM|rpm\b))', summary_text, re.IGNORECASE)
            if m_rpm:
                specs['ความเร็วรอบ'] = m_rpm.group(1).strip()
        if 'แรงดันลมสูงสุด' not in specs:
            m_airp = re.search(r'แรงดันลม(?:สูงสุด)?\s*[:：]?\s*([0-9\-\.\s]+(?:kPa|KPA|บาร์|PSI|bar))', summary_text, re.IGNORECASE)
            if m_airp:
                specs['แรงดันลมสูงสุด'] = _clean_spec_value(m_airp.group(1).strip())
        if 'กำลังเครื่องยนต์' not in specs and 'ประสิทธิภาพเครื่องยนต์' not in specs:
            m_hp = re.search(r'(\d+(?:\.\d+)?)\s*(?:แรงม้า|HP\b)', summary_text, re.IGNORECASE)
            if m_hp:
                specs['กำลังเครื่องยนต์'] = f"{m_hp.group(1)} แรงม้า"
        if 'ความจุถัง' not in specs and not any('ถัง' in k for k in specs):
            m_tank = re.search(r'(?:ถัง(?:จุ|บรรจุ|ลม|น้ำมัน|เชื้อเพลิง|เก็บฝุ่น)?|น้ำ-แห้ง[^\d]{0,16})\s*(\d+(?:\.\d+)?)\s*(?:ลิตร|L\b)', summary_text)
            if m_tank:
                specs['ความจุถัง'] = f"{m_tank.group(1)} ลิตร"
        if 'มุมการตัด' not in specs:
            m_ang = re.search(r'มุม(?:การ)?ตัด\s*[:：]?\s*([0-9\-\–\s]+(?:องศา|°))', summary_text)
            if m_ang:
                specs['มุมการตัด'] = m_ang.group(1).strip()

    # 3. Layer 2B: Description Structured Bullet Parser (Colon `k : v` + Colon-less `• Label NumberUnit` + Warning-Stop Guard)
    _STOP_SECTIONS = ('คำเตือน', 'ข้อควรระวัง', 'การบำรุงรักษา', 'การเก็บรักษา', 'เงื่อนไขการรับประกัน', 'อุปกรณ์มาตรฐาน', 'อุปกรณ์ในกล่อง', 'สินค้าในกล่อง')
    _COLONLESS_UNIT_RE = re.compile(
        r'^([\u0E00-\u0E7FA-Za-z][\u0E00-\u0E7FA-Za-z\s/\-]{1,24}?)\s+'
        r'([±~]?\d[\d,\.\-\/xX×\s]*\s*(?:วัตต์|กิโลวัตต์|แรงม้า|แอมป์|โวลต์|บาร์|ลิตร\/นาที|ลิตร\/ชม\.|ลิตร|มล\.|มม\.|ซม\.|เมตร|ม\.|นิ้ว|ฟุต|ตัน|กก\.|กรัม|รอบ\/นาที|จังหวะ|ทาง|องศา|ขั้น|ระบบ|โหมด|กิโลปาสคาล|kPa|KPA|kW|KW|kVA|KVA|HP|CC|cc|ml|ML|cm\.?|mm\.?|RPM|rpm|V\b|W\b|A\b|L\b|Bar|PSI))',
        re.IGNORECASE
    )
    _COLONLESS_BAD_PREFIX = ('ใช้', 'สามารถ', 'เหมาะ', 'ควร', 'ห้าม', 'มี', 'ให้', 'รับประกัน', 'สินค้า', 'รุ่น', 'ยี่ห้อ', 'เครื่อง', 'ผลิตจาก', 'ช่วย', 'ไม่', 'พร้อม', 'น้ำหนัก', 'และ', 'หรือ', 'เพื่อ', 'สำหรับ', 'ตัวเครื่อง')

    in_warning_section = False
    for raw_line in clean_desc.split('\n'):
        line = raw_line.strip().lstrip('•').lstrip('-').lstrip('*').lstrip('▪').strip()
        if not line:
            continue
        if any(line.startswith(sh) and len(line) <= 32 for sh in _STOP_SECTIONS):
            in_warning_section = True
            continue
        if in_warning_section:
            continue

        if ':' in line or '：' in line:
            parts = re.split(r'[:：]', line, maxsplit=1)
            k = _clean_spec_label(parts[0])
            v = _clean_spec_value(parts[1])
            if k and v and len(k) < 30 and len(v) < 50:
                # Capture generic catalog bullet points from source (excluding noise metadata)
                if k not in specs and not _is_noise_spec_key(k) and not re.match(r'^1\s*(?:ชิ้น|อัน|เครื่อง|ชุด)$', v):
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
                elif 'กำลังไฟ' in k and 'กำลังไฟฟ้า' not in specs and 'กำลังไฟสูงสุด' not in specs:
                    specs['กำลังไฟฟ้า'] = v
                elif ('แรงดัน' in k or 'pressure' in k.lower()) and 'สาย' not in k and 'ไฟ' not in k and 'ลม' not in k and 'แรงดันสูงสุด' not in specs:
                    specs['แรงดันสูงสุด'] = v
                elif ('ปริมาณน้ำ' in k or 'อัตราการไหล' in k or 'อัตราการฉีด' in k) and 'อัตราการไหลของน้ำ' not in specs:
                    specs['อัตราการไหลของน้ำ'] = v
                elif 'น้ำหนัก' in k and 'น้ำหนักตัวเครื่อง' not in specs and 'กล่อง' not in k:
                    specs['น้ำหนักตัวเครื่อง'] = v
                elif 'ความเร็วรอบ' in k and 'ความเร็วรอบ' not in specs:
                    specs['ความเร็วรอบ'] = v
        elif len(line) <= 58:
            # Universal colon-less technical bullet parser (e.g. "• แรงลม 9 ลิตร/นาที", "• ทางลมออก 4 ทาง", "• กำลังไฟสูงสุด 6.5 กิโลวัตต์")
            m_cl = _COLONLESS_UNIT_RE.match(line)
            if m_cl:
                ck = _clean_spec_label(m_cl.group(1))
                cv = _clean_spec_value(m_cl.group(2))
                if (
                    ck and cv
                    and not _is_noise_spec_key(ck)
                    and not any(ck.startswith(bp) for bp in _COLONLESS_BAD_PREFIX)
                    and len(ck) <= 24 and len(cv) <= 36
                    and ck not in specs
                ):
                    specs[ck] = cv
            elif re.search(r'สูบเดี่ยว\s*[24]\s*จังหวะ', line) and 'ระบบเครื่องยนต์' not in specs:
                m_eng = re.search(r'(สูบเดี่ยว\s*[24]\s*จังหวะ)', line)
                if m_eng:
                    specs['ระบบเครื่องยนต์'] = m_eng.group(1)

        # Free-text checks in line
        if 'Auto Stop' in line and 'ระบบตัดการทำงาน' not in specs:
            specs['ระบบตัดการทำงาน'] = 'ระบบ Auto Stop'
        if ('เหนี่ยวนำ' in line or 'Induction' in line) and 'ประเภทมอเตอร์' not in specs:
            specs['ประเภทมอเตอร์'] = 'มอเตอร์เหนี่ยวนำ'
        elif ('แปรงถ่าน' in line or 'Universal' in line) and 'ประเภทมอเตอร์' not in specs:
            specs['ประเภทมอเตอร์'] = 'มอเตอร์แปรงถ่าน'
        if 'ระบายความร้อนด้วยอากาศ' in line and 'ระบบระบายความร้อน' not in specs:
            specs['ระบบระบายความร้อน'] = 'ระบายความร้อนด้วยอากาศ'
        elif 'ระบายความร้อนด้วยน้ำ' in line and 'ระบบระบายความร้อน' not in specs:
            specs['ระบบระบายความร้อน'] = 'ระบายความร้อนด้วยน้ำ'

        # Free-text hose check if still missing
        if 'ความยาวสายฉีด' not in specs and ('สายอัดฉีด' in line or ('สายฉีด' in line and 'สายไฟ' not in line)):
            m_line = re.search(r'ยาว(?:ถึง)?\s*(\d+(?:\.\d+)?)\s*(?:ม\.|เมตร|m\b)', line, re.IGNORECASE)
            if m_line:
                specs['ความยาวสายฉีด'] = f"{m_line.group(1)} เมตร"

    # Universal Engine / Cordless / Saw extras when still missing
    if is_engine:
        if 'ระบบสตาร์ท' not in specs:
            if 'สตาร์ทไฟฟ้า' in full_text or 'กุญแจสตาร์ท' in full_text:
                specs['ระบบสตาร์ท'] = 'สตาร์ทไฟฟ้า'
            elif 'สตาร์ทมือดึง' in full_text or 'ลานดึง' in full_text:
                specs['ระบบสตาร์ท'] = 'สตาร์ทมือดึง (ลานดึง)'
        if 'ระบบเครื่องยนต์' not in specs and 'ประเภทเครื่องยนต์' not in specs:
            m_st = re.search(r'([24]\s*จังหวะ)', full_text)
            if m_st:
                specs['ระบบเครื่องยนต์'] = f"เครื่องยนต์ {m_st.group(1)}"
        if 'ความจุกระบอกสูบ' not in specs:
            m_cc = re.search(r'(\d+(?:\.\d+)?)\s*(?:ซีซี|CC\b|cc\b)', full_text)
            if m_cc:
                specs['ความจุกระบอกสูบ'] = f"{m_cc.group(1)} ซีซี"

    if is_cordless and 'ชุดอุปกรณ์' not in specs and 'แบตเตอรี่และแท่นชาร์จ' not in specs:
        if any(k in full_text for k in ['ไม่รวมแบต', 'ไม่แบต', 'ตัวเปล่า']):
            specs['ชุดอุปกรณ์'] = 'ตัวเครื่องเปล่า (ไม่รวมแบต)'

    # Fallback: if 'กำลังมอเตอร์' is in specs but 'กำลังไฟฟ้า' missing and vice-versa
    if 'กำลังมอเตอร์' not in specs and 'กำลังไฟฟ้า' in specs and 'วัตต์' in specs['กำลังไฟฟ้า'] and 'กิโลวัตต์' not in specs['กำลังไฟฟ้า']:
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

    # Welding machines: extract wire size, welding modes, and built-in functions from description
    is_welder = any(k in full_text.lower() for k in ['เครื่องเชื่อม', 'ตู้เชื่อม', 'welding']) and 'คีม' not in full_text.lower()
    if is_welder:
        if 'ขนาดลวดเชื่อม' not in specs:
            m_rod = re.search(r'ลวดเชื่อม[^\d\n]{0,35}(\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?)\s*(?:มม\.?|มิลลิเมตร|mm\b)', full_text, re.IGNORECASE)
            if m_rod:
                specs['ขนาดลวดเชื่อม'] = f"{re.sub(r'\s+', ' ', m_rod.group(1).strip())} มม."
        if 'ระบบการเชื่อม' not in specs:
            modes = []
            if re.search(r'\bMMA\b', full_text, re.I): modes.append('MMA')
            if re.search(r'Lift\s*TIG', full_text, re.I): modes.append('Lift TIG')
            elif re.search(r'\bTIG\b', full_text, re.I): modes.append('TIG')
            if re.search(r'\bMIG\b', full_text, re.I): modes.append('MIG')
            if re.search(r'\bVRD\b', full_text, re.I): modes.append('VRD')
            if modes:
                if len(modes) == 1:
                    extra_f = []
                    if re.search(r'Hot\s*Start', full_text, re.I): extra_f.append('Hot Start')
                    if re.search(r'Arc\s*Force', full_text, re.I): extra_f.append('Arc Force')
                    if re.search(r'Digital|ดิจิตอล', full_text, re.I): extra_f.append('จอดิจิตอล')
                    specs['ระบบการเชื่อม'] = ' / '.join(modes + extra_f[:2]) if extra_f else modes[0]
                else:
                    specs['ระบบการเชื่อม'] = ' / '.join(modes[:3])
        if 'ฟังก์ชันเสริม' not in specs:
            funcs = []
            if re.search(r'Hot\s*Start', full_text, re.I): funcs.append('Hot Start')
            if re.search(r'Arc\s*Force', full_text, re.I): funcs.append('Arc Force')
            if re.search(r'Anti[\s-]*Stick', full_text, re.I): funcs.append('Anti-Stick')
            if re.search(r'Digital|ดิจิตอล', full_text, re.I): funcs.append('จอดิจิตอล')
            if funcs:
                specs['ฟังก์ชันเสริม'] = ', '.join(funcs[:3])
        m_war = re.search(r'รับประกัน(?:ศูนย์)?\s*(\d+\s*(?:ปี|เดือน))', f"{summary_text} {clean_desc}")
        if m_war and 'การรับประกัน' not in specs:
            specs['การรับประกัน'] = f"ประกันศูนย์ {m_war.group(1).strip()}"

    # Hand tools (คีม, คีมล็อค, ประแจ, ลูกบล็อก) — match product name ONLY (not included hex-wrench accessories!)
    if any(k in prod_full_name for k in ['คีม', 'คีมล็อค', 'ประแจ', 'ลูกบล็อก']):
        m_inch = re.search(r'(\d+[\d.]*)\s*(?:นิ้ว|")', full_text)
        if m_inch and 'ขนาดความยาว' not in specs and 'ขนาด' not in specs:
            try:
                inch_v = float(m_inch.group(1))
                mm_v = round(inch_v * 25.4)
                specs['ขนาดความยาว'] = f"{inch_v:g} นิ้ว ({mm_v} มม.)"
            except Exception:
                pass
        if 'ปากตรง' in full_text and 'ลักษณะปากจับ' not in specs:
            specs['ลักษณะปากจับ'] = 'ปากตรง ยึดจับแน่น'
        elif 'ปากโค้ง' in full_text and 'ลักษณะปากจับ' not in specs:
            specs['ลักษณะปากจับ'] = 'ปากโค้ง ล็อคแน่น'
        elif 'ปากแหลม' in full_text and 'ลักษณะปากจับ' not in specs:
            specs['ลักษณะปากจับ'] = 'ปากแหลม เข้าที่แคบง่าย'
        if 'คีมล็อค' in full_text and 'ระบบล็อค' not in specs:
            specs['ระบบล็อค'] = 'ล็อคแรงบีบสูง ปรับขนาดได้'
        if 'เหมาะสำหรับงาน' not in specs:
            uses = []
            if 'โลหะ' in full_text: uses.append('งานโลหะ')
            if 'น๊อต' in full_text or 'น็อต' in full_text: uses.append('จับหัวน็อต')
            if 'เชื่อม' in full_text: uses.append('งานเชื่อม')
            if 'ท่อ' in full_text: uses.append('จับท่อ')
            if uses:
                specs['เหมาะสำหรับงาน'] = ' / '.join(uses[:3])

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

    # User requirement: fill 220V power supply ONLY for corded AC power tools / pressure washers (NEVER cordless battery or engine tools!)
    if not is_tape_or_consumable and not is_cordless and not is_engine:
        if 'กำลังไฟฟ้า' not in specs and 'แรงดันไฟฟ้า' not in specs and ('วัตต์' in clean_desc or 'กำลังมอเตอร์' in specs or is_pressure_washer):
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

    # Power deduplication: keep only one single watt/kW power key
    power_keys = [
        k for k in list(specs.keys())
        if any(w in k for w in ['กำลังมอเตอร์', 'กำลังไฟฟ้าที่ใช้', 'กำลังไฟฟ้า', 'กำลังไฟสูงสุด', 'กำลังวัตต์', 'กำลังไฟ'])
        and 'เข้า' not in k
        and (any(u in str(specs[k]) for u in ['วัตต์', 'กิโลวัตต์', 'kW', 'KW']) or bool(re.search(r'\d+\s*w\b', str(specs[k]), re.I)))
    ]
    if len(power_keys) > 1:
        best_p_key = 'กำลังมอเตอร์' if 'กำลังมอเตอร์' in power_keys else ('กำลังไฟสูงสุด' if 'กำลังไฟสูงสุด' in power_keys else power_keys[0])
        best_p_val = specs[best_p_key]
        for pk in power_keys:
            del specs[pk]
        specs[best_p_key] = best_p_val

    # Pressure deduplication: keep only 'แรงดันสูงสุด' with Bar + PSI
    if 'แรงดันสูงสุด' in specs and 'แรงดัน' in specs:
        del specs['แรงดัน']

    # Water flow deduplication: keep only one flow rate
    if 'อัตราการไหลของน้ำ' in specs and 'ปริมาณน้ำ' in specs:
        del specs['ปริมาณน้ำ']
    elif 'ปริมาณน้ำสูงสุด' in specs and 'ปริมาณน้ำ' in specs:
        del specs['ปริมาณน้ำ']

    # Hose and cord deduplication:
    if 'ความยาวสายฉีด' in specs:
        for hk in list(specs.keys()):
            if hk != 'ความยาวสายฉีด' and ('สายอัดฉีด' in hk or 'สายฉีด' in hk):
                del specs[hk]
    if 'ความยาวสายไฟ' in specs:
        for ck in list(specs.keys()):
            if ck != 'ความยาวสายไฟ' and 'สายไฟ' in ck:
                del specs[ck]

    # Grinding / saw disc size deduplication
    if 'ขนาดใบตัด/เจียร์' in specs:
        for dk in ['เส้นผ่านศูนย์กลางแผ่นเจีย', 'เส้นผ่าศูนย์กลางแผ่นเจีย', 'เส้นผ่านศูนย์กลางใบ', 'เส้นผ่านศูนย์กลางใบตัด', 'ขนาดแผ่นเจียร', 'ขนาดใบตัด']:
            if dk in specs and dk != 'ขนาดใบตัด/เจียร์':
                del specs[dk]
    if 'ขนาดท่อออก' in specs and 'ขนาดท่อส่ง' in specs:
        del specs['ขนาดท่อส่ง']
    if 'ขนาดท่อออก' in specs and 'ขนาดท่อส่งออก' in specs:
        del specs['ขนาดท่อส่งออก']
    if 'ระยะส่งสูงสุด' in specs and 'ส่งสูงสุด' in specs:
        del specs['ส่งสูงสุด']
    if 'ความสามารถในการยก' in specs and 'ยกได้' in specs:
        del specs['ยกได้']
    if 'ความสูงมากสุด' in specs and 'ความสูงเมื่อยกสูงสุด' in specs:
        del specs['ความสูงเมื่อยกสูงสุด']
    if 'ระบบไฟฟ้า' in specs and ('แรงดันไฟฟ้า' in specs or 'กำลังไฟฟ้า' in specs):
        del specs['ระบบไฟฟ้า']
    if 'ความจุถัง' in specs and any(k != 'ความจุถัง' and 'ความจุถัง' in k for k in specs):
        del specs['ความจุถัง']

    if 'กำลังมอเตอร์' in specs and 'กำลังไฟฟ้า' in specs and 'วัตต์' in str(specs['กำลังไฟฟ้า']) and 'กิโลวัตต์' not in str(specs['กำลังไฟฟ้า']):
        del specs['กำลังไฟฟ้า']

    return specs


def is_stale_truncated_category(saved_cat, model_code=""):
    """Detect broken auto-generated titles saved by legacy code (e.g. 'PL-411C ตัดหญ้าสะพายข้าง 2', '10R คีมล็อคปากตรง ขนาด') without touching clean manual edits."""
    s = str(saved_cat or "").strip()
    if not s:
        return True
    # 1. Ends with a dangling bare digit cut off from its unit word (e.g. 'ตัดหญ้าสะพายข้าง 2')
    if re.search(r'\s\d+$', s):
        return True
    # 2. Ends with a dangling incomplete Thai connector/preposition (e.g. 'คีมล็อคปากตรง ขนาด')
    if re.search(r'(?:^|\s)(?:ขนาด|รุ่น|แบบ|ระบบ|สี|พร้อม|สำหรับ|และ|หรือ|/|[-–+])$', s):
        return True
    # 3. Duplicates the model code at the start (e.g. 'PL-411C ...', 'SHT-30 ...', 'M5801B ...', '10R ...')
    mc = re.sub(r'^รุ่น\s*', '', str(model_code or "").strip()).strip()
    if len(mc) >= 2:
        mc_norm = re.sub(r'[\-\s_]+', '', mc).lower()
        first_tok = s.split()[0] if s.split() else ""
        first_norm = re.sub(r'[\-\s_]+', '', first_tok).lower()
        if first_norm and mc_norm and (first_norm == mc_norm or (len(mc_norm) >= 3 and first_norm.startswith(mc_norm))):
            return True
    return False


def _build_clean_category_title(prod_name, model_code, summary="", desc=""):
    """Generate a complete, clean, model-free Thai product category title across all 96,280 KTW SKUs."""
    raw_name = (prod_name or "").replace('”', '"').replace('“', '"').replace('อุตฯ', 'อุตสาหกรรม').strip()
    ctx = f"{raw_name} {summary or ''}"

    # 1. Curated high-clarity Thai category templates for major hardware families
    if 'ดอกสว่าน' in raw_name or 'เจดีย์' in raw_name:
        return "ชุดดอกสว่านเจดีย์" if ('ชุด' in raw_name or 'SET' in raw_name.upper() or '3 ดอก' in raw_name) else "ดอกสว่านเจดีย์"
    if 'ใบตัด' in raw_name or 'ใบเจียร์' in raw_name:
        return "ใบตัด / ใบเจียร์คุณภาพ"
    if 'เครื่องเจียร์' in raw_name or 'ลูกหมู' in raw_name:
        m_sz = re.search(r'(\d+(?:\.\d+)?)\s*(?:นิ้ว|")', raw_name)
        return f"เครื่องเจียร์ไฟฟ้า {m_sz.group(1)} นิ้ว" if m_sz else "เครื่องเจียร์ไฟฟ้า 4 นิ้ว"
    if 'เครื่องฉีดน้ำ' in raw_name:
        return "เครื่องฉีดน้ำแรงดันสูง"
    if 'ตัดหญ้า' in raw_name:
        m_st = re.search(r'([24])\s*จังหวะ', ctx)
        st_txt = f" {m_st.group(1)} จังหวะ" if m_st else ""
        if 'สะพาย' in ctx:
            return f"เครื่องตัดหญ้าสะพายข้าง{st_txt}"
        return f"เครื่องตัดหญ้า{st_txt}"
    if 'เลื่อยวงเดือน' in raw_name or 'วงเดือน' in raw_name:
        m_sz = re.search(r'(\d+(?:\.\d+)?)\s*(?:นิ้ว|")', ctx)
        is_saw_cordless = (
            any(k in ctx.lower() for k in ['ไร้สาย', 'แบต', 'ไม่รวมแบต', 'ไม่แบต', '20v', '18v', '40v', 'cordless'])
            or bool(re.search(r'(?<!รอบ)ตัวเปล่า', raw_name))
        )
        cordless_txt = "ไร้สาย" if is_saw_cordless else ""
        sz_txt = f" {m_sz.group(1)} นิ้ว" if m_sz else ""
        return f"เครื่องเลื่อยวงเดือน{cordless_txt}{sz_txt}"
    if 'เลื่อยโซ่' in raw_name:
        m_sz = re.search(r'(\d+(?:\.\d+)?)\s*(?:นิ้ว|")', ctx)
        sz_txt = f" {m_sz.group(1)} นิ้ว" if m_sz else ""
        if any(k in ctx for k in ['จังหวะ', 'ยนต์', 'เบนซิน']):
            return f"เครื่องเลื่อยโซ่ยนต์{sz_txt}"
        return f"เครื่องเลื่อยโซ่ไฟฟ้า{sz_txt}"
    if 'พัดลม' in raw_name or 'ดูดเป่า' in raw_name:
        m_sz = re.search(r'(\d+)\s*(?:นิ้ว|")', ctx)
        sz_txt = f" {m_sz.group(1)} นิ้ว" if m_sz else ""
        if 'ดูดเป่า' in ctx:
            return f"พัดลมอุตสาหกรรมดูดเป่า{sz_txt}"
        return f"พัดลมอุตสาหกรรม{sz_txt}"
    if 'คีมล็อค' in raw_name:
        jaw = "ปากตรง" if 'ปากตรง' in ctx else ("ปากโค้ง" if 'ปากโค้ง' in ctx else ("ปากแหลม" if 'ปากแหลม' in ctx else ""))
        m_sz = re.search(r'(\d+(?:\.\d+)?)\s*(?:นิ้ว|")', ctx)
        sz_txt = f" {m_sz.group(1)} นิ้ว" if m_sz else ""
        return f"คีมล็อค{jaw}{sz_txt}"
    if 'เครื่องปั่นไฟ' in raw_name:
        m_kw = re.search(r'(\d+(?:\.\d+)?)\s*(?:KW|kW|กิโลวัตต์)', ctx)
        if m_kw:
            return f"เครื่องปั่นไฟเบนซิน {m_kw.group(1)} KW" if 'เบนซิน' in ctx else f"เครื่องปั่นไฟ {m_kw.group(1)} KW"
        return "เครื่องปั่นไฟเบนซิน" if 'เบนซิน' in ctx else "เครื่องปั่นไฟ"
    if 'ปั๊มลม' in raw_name:
        m_way = re.search(r'(\d+)\s*ทาง', ctx)
        m_lt = re.search(r'(\d+)\s*(?:ลิตร|L\b)', ctx)
        if m_way:
            return f"ปั๊มลม {m_way.group(1)} ทาง"
        if m_lt:
            return f"ปั๊มลม {m_lt.group(1)} ลิตร"
        return "ปั๊มลมไฟฟ้า"
    if 'ปั๊มแช่' in raw_name:
        m_sz = re.search(r'(\d+(?:\.\d+)?)\s*(?:นิ้ว|")', ctx)
        return f"ปั๊มแช่ไฟฟ้า {m_sz.group(1)} นิ้ว" if m_sz else "ปั๊มแช่ไฟฟ้า"
    if 'ปั๊มจุ่ม' in raw_name:
        return "ปั๊มน้ำมาตรฐาน"
    if 'ดูดฝุ่น' in raw_name:
        dry_wet = " น้ำ-แห้ง" if ('น้ำ-แห้ง' in ctx or 'เปียกและแห้ง' in ctx) else ""
        m_lt = re.search(r'(\d+)\s*(?:ลิตร|L\b)', ctx)
        lt_txt = f" {m_lt.group(1)} ลิตร" if m_lt else ""
        return f"เครื่องดูดฝุ่น{dry_wet}{lt_txt}"
    if 'แม่แรง' in raw_name:
        m_ton = re.search(r'(\d+(?:\.\d+)?)\s*(?:ตัน|TON)', ctx, re.I)
        ton_txt = f" {m_ton.group(1)} ตัน" if m_ton else ""
        return f"แม่แรงตะเข้{ton_txt}" if 'ตะเข้' in ctx else f"แม่แรงยก{ton_txt}"
    if 'บันได' in raw_name:
        m_ft = re.search(r'(\d+)\s*(?:ฟุต|ขั้น)', ctx)
        ft_txt = f" {m_ft.group(0)}" if m_ft else ""
        if 'กางปรับพาด' in ctx or 'ปรับพาด' in ctx:
            return f"บันไดกางปรับพาด{ft_txt}"
        return f"บันไดอลูมิเนียม{ft_txt}" if 'อลูมิเนียม' in ctx else f"บันไดช่าง{ft_txt}"
    if 'วัดระยะ' in raw_name and 'เลเซอร์' in ctx:
        m_m = re.search(r'(\d+)\s*(?:เมตร|ม\.)', ctx)
        return f"เครื่องวัดระยะเลเซอร์ {m_m.group(1)} เมตร" if m_m else "เครื่องวัดระยะเลเซอร์"
    if 'สว่านโรตารี่' in raw_name:
        return "สว่านโรตารี่"
    if 'สว่าน' in raw_name:
        if any(k in ctx.lower() for k in ['ไร้สาย', 'แบต', '12v', '18v', '20v', '40v']):
            m_sys = re.search(r'(\d+)\s*(?:ระบบ|โหมด)', ctx)
            return f"สว่านไร้สาย {m_sys.group(1)} ระบบ" if m_sys else "สว่านไร้สาย"
        return "สว่านไฟฟ้า"
    if 'เครื่องจี้ปูน' in raw_name:
        return "เครื่องจี้ปูนไฟฟ้า"
    if 'ตู้เชื่อม' in raw_name or 'เครื่องเชื่อม' in raw_name:
        return "เครื่องเชื่อมไฟฟ้า"
    if 'ปั๊ม' in raw_name:
        return "ปั๊มน้ำมาตรฐาน"
    if 'เทป' in raw_name or 'TEMFLEX' in raw_name.upper():
        return "เทปพันสายไฟไวนิล"

    # 2. Universal smart fallback for ANY unseen KTW product: strip model_code, colors & tags; NEVER split a number from its unit!
    clean_p = re.sub(r'^\s*[\(\[]\s*(?:แพ็ค|กล่อง|ชุด|แถม).*?[\)\]]\s*', '', raw_name).strip()
    clean_p = re.sub(r'\[.*?\]', '', clean_p)
    clean_p = re.sub(r'\([^\)]*(?:ใหม่|ลิมิเต็ด|ตัวเปล่า|ไม่รวมแบต|ไม่แบต|[A-Z0-9]{4,})[^\)]*\)', '', clean_p, flags=re.I)
    clean_p = re.sub(r'(\d+(?:\.\d+)?)\s*"', r'\1 นิ้ว', clean_p)
    # Strip model_code tokens so category never duplicates the red/navy model pill
    mc_clean = re.sub(r'^รุ่น\s*', '', str(model_code or "")).strip()
    if len(mc_clean) >= 2:
        mc_esc = re.escape(mc_clean)
        mc_nodash = re.escape(re.sub(r'[\-\s_]+', '', mc_clean))
        clean_p = re.sub(rf'(?:^|\s)(?:{mc_esc}|{mc_nodash})(?=\s|$)', ' ', clean_p, flags=re.I)
    # Strip trailing color words (สีแดง, สีดำ, etc.)
    clean_p = re.sub(r'\s+สี(?:แดง|ดำ|ขาว|น้ำเงิน|เขียว|เหลือง|ส้ม|เทา|ฟ้า|ม่วง|ชมพู|ทอง|เงิน)\b.*$', '', clean_p)
    clean_p = re.sub(r'\s+', ' ', clean_p).strip(' /-–+')

    words = clean_p.split()
    if not words:
        return "เครื่องมือช่างคุณภาพ"

    # Keep natural phrase up to 4 tokens (~34 chars), ALWAYS attaching unit word if last token is numeric or 'ขนาด'
    kept = []
    for w in words:
        if len(kept) >= 4 or (len(' '.join(kept + [w])) > 34 and len(kept) >= 2):
            break
        kept.append(w)
    idx = len(kept)
    while idx < len(words):
        last = kept[-1]
        if re.match(r'^\d+(?:\.\d+)?$', last):
            kept.append(words[idx])
            idx += 1
        elif last in ('ขนาด', 'ระบบ', 'แบบ', 'รุ่น', 'ชุด') and idx + 1 < len(words) and re.match(r'^\d', words[idx]):
            kept.extend(words[idx:idx + 2])
            idx += 2
        else:
            break
    while len(kept) > 1 and kept[-1] in ('ขนาด', 'ระบบ', 'แบบ', 'รุ่น', 'สี', 'พร้อม', 'สำหรับ', '/', '-', '+'):
        kept.pop()
    return ' '.join(kept) if kept else "เครื่องมือช่างคุณภาพ"


def enrich_spec_cards(saved_cards, default_cards, target_count=4):
    """Preserve user's existing spec cards and automatically backfill any empty slots up to 4 from KTW defaults."""
    base = [c for c in (saved_cards or []) if isinstance(c, dict) and str(c.get("label", "")).strip() and str(c.get("val", "")).strip()]
    if len(base) >= target_count:
        return base[:target_count]
    seen_labels = {str(c.get("label", "")).strip().lower() for c in base}
    seen_vals = {re.sub(r'\s+', '', str(c.get("val", ""))).lower() for c in base}
    out = list(base)
    for dc in (default_cards or []):
        if len(out) >= target_count:
            break
        if not isinstance(dc, dict) or not dc.get("label") or not dc.get("val"):
            continue
        lk = str(dc["label"]).strip().lower()
        vk = re.sub(r'\s+', '', str(dc["val"])).lower()
        if lk in seen_labels or vk in seen_vals:
            continue
        out.append(dc)
        seen_labels.add(lk)
        seen_vals.add(vk)
    return out


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

    # 1. Model Name FIRST (so category_title never duplicates model_code)
    model_code, _ = extract_model_label(prod_name, sku, detail=detail)
    model_name = f"รุ่น {model_code}" if not model_code.startswith("รุ่น") else model_code

    # 2. Complete Smart Category Title
    category_title = _build_clean_category_title(
        prod_name, model_code, summary=detail.get('summary', '') or '', desc=detail.get('description', '') or ''
    )

    # 3. Spec cards with universal vector-supported icons and smart priority
    icon_map = {
        'ขนาด': '📏', 'แกน': '📏', 'ใบ': '📏', 'สาย': '📏', 'กว้าง': '📏', 'ยาว': '📏', 'สูง': '📏',
        'ลวด': '📏', 'ท่อ': '📏', 'บาร์': '📏', 'ระยะ': '📏', 'หนา': '📐', 'มุม': '📐', 'แม่นยำ': '📐',
        'ระบบ': '⚙️', 'ฟังก์ชัน': '⚙️', 'ล็อค': '⚙️', 'แรงบิด': '⚙️', 'ทอร์ค': '⚙️', 'โหมด': '⚙️',
        'สตาร์ท': '⚙️', 'เครื่องยนต์': '⚙️', 'จังหวะ': '⚙️', 'ชุดอุปกรณ์': '⚙️', 'รูปแบบ': '⚙️', 'ทางลม': '⚙️',
        'เหมาะสำหรับ': '✅', 'จุดเด่น': '✅', 'การใช้งาน': '✅',
        'มาตรฐาน': '🛡️', 'กันน้ำ': '🛡️', 'ประกัน': '🛡️', 'ฉนวน': '🛡️',
        'คุณสมบัติ': '🛡️', 'ไม่ลามไฟ': '🛡️', 'วัสดุ': '🛡️', 'เกรด': '🛡️', 'ระดับ': '🛡️', 'ยก': '🛡️',
        'ความเร็ว': '⏱', 'รอบ': '⏱', 'เวลา': '⏱', 'อัตรา': '⏱',
        'สวิตช์': '🔘', 'ตำแหน่ง': '🔘',
        'แรงดันไฟฟ้า': '⚡', 'แรงดันแบต': '⚡', 'กำลัง': '⚡', 'มอเตอร์': '⚡', 'วัตต์': '⚡', 'โวลต์': '⚡',
        'กระแส': '⚡', 'แอมป์': '⚡', 'KVA': '⚡', 'ประสิทธิภาพ': '⚡', 'เชื่อม': '⚡', 'แรงดัน': '⚡',
        'ถัง': '⚙️', 'ความจุ': '⚙️', 'ลม': '⚡', 'น้ำ': '⚡', 'เลเซอร์': '⚡',
    }
    def _spec_priority(item):
        k, v = item
        vs = str(v)
        if 'กระแส' in k or 'แอมป์' in vs: return 1
        if 'ความสามารถในการยก' in k or 'ระยะการวัด' in k: return 1
        if 'เจาะ' in k or 'ขนาดการเจาะ' in k: return 1
        if 'แรงบิด' in k or 'นิวตัน' in vs: return 1
        if 'มอเตอร์' in k or 'กำลังเครื่องยนต์' in k or 'ประสิทธิภาพเครื่องยนต์' in k or 'กำลังไฟสูงสุด' in k or 'วัตต์' in vs or 'กิโลวัตต์' in vs or 'KVA' in vs or bool(re.search(r'\d+\s*w\b', vs, re.I)): return 2
        if 'แรงดันสูงสุด' in k or 'แรงดันลม' in k or 'บาร์' in vs or 'kPa' in vs: return 3
        if 'ขนาดลวด' in k or 'ขนาดบาร์' in k or 'แรงดันแบตเตอรี่' in k: return 3
        if 'ความสูง' in k or 'ความแม่นยำ' in k or 'ความจุถัง' in k or 'ระยะส่ง' in k: return 3
        if 'ขนาดตัวเครื่อง' in k or k == 'ขนาด': return 13
        if 'ขนาด' in k or 'ลวด' in k or 'หัว' in k or 'ใบ' in k or 'ท่อ' in k or 'ความกว้าง' in k: return 4
        if 'ความเร็ว' in k or 'รอบ' in vs or 'แรงลม' in k: return 5
        if 'ความยาว' in k or 'เมตร' in vs or 'มุม' in k or 'ทางลม' in k: return 6
        if 'ระบบการเชื่อม' in k or 'ฟังก์ชัน' in k or 'ระบบสตาร์ท' in k or 'ระบบเครื่องยนต์' in k or 'ประเภทเครื่องยนต์' in k: return 6
        if 'อัตรา' in k or ('น้ำ' in k and 'น้ำหนัก' not in k and 'กันน้ำ' not in k): return 7
        if 'สวิตช์' in k or 'ระบบ' in k or 'ประเภท' in k or 'ระดับ' in k: return 8
        if 'เกรด' in k or 'วัสดุ' in k or 'เหมาะสำหรับ' in k: return 9
        if 'มาตรฐาน' in k or 'ประกัน' in k or 'ประสิทธิภาพ' in k: return 10
        if 'ชุดอุปกรณ์' in k or 'แบตเตอรี่และแท่นชาร์จ' in k: return 11
        if 'แรงดันไฟฟ้า' in k or '220' in vs: return 12
        if 'น้ำหนัก' in k: return 14
        return 11

    # 3. Extract Weight Pill (Pill 2: น้ำหนักสินค้า)
    weight_pill = None
    desc_raw = detail.get('description', '') or ''
    
    # 3.1 Check specific packaging in description (e.g. "น้ำหนัก (ม้วน) 40 กรัม")
    m_roll = re.search(r'น้ำหนัก\s*\(([^\)]+)\)\s*([\d\.]+)\s*(กรัม|กก|กิโลกรัม|g|kg)', desc_raw, flags=re.I)
    if m_roll:
        unit_type = m_roll.group(1).strip()
        val_w = m_roll.group(2).strip()
        u_str = m_roll.group(3).strip()
        u_th = 'กรัม' if u_str.lower() in ['g', 'กรัม'] else 'กก.'
        weight_pill = f"น้ำหนัก {val_w} {u_th}/{unit_type}"
    
    # 3.2 Free-text regex in description
    if not weight_pill:
        m_desc = re.search(r'(?:น้ำหนัก|weight)[^\d]{0,10}([\d\.]+)\s*(กรัม|กก|กิโลกรัม|g|kg)', desc_raw, flags=re.I)
        if m_desc:
            val_f = float(m_desc.group(1))
            u_str = m_desc.group(2).strip()
            if u_str.lower() in ['g', 'กรัม'] or (u_str.lower() in ['กก', 'กิโลกรัม', 'kg'] and val_f < 1):
                g_val = int(val_f * 1000) if u_str.lower() in ['กก', 'กิโลกรัม', 'kg'] else int(val_f)
                weight_pill = f"น้ำหนัก {g_val} กรัม"
            else:
                weight_pill = f"น้ำหนัก {val_f:.1f}".rstrip('0').rstrip('.') + " กก."

    # 3.3 From specs_dict
    if not weight_pill:
        for wk in ['น้ำหนัก', 'น้ำหนัก (กก.)', 'น้ำหนักสุทธิ', 'น้ำหนักตัวเครื่อง', 'น้ำหนัก (kg)']:
            if wk in specs_dict and specs_dict[wk]:
                v_str = str(specs_dict[wk])
                m_w = re.search(r'([\d\.]+)\s*(กก|กรัม|g|kg)?', v_str, flags=re.I)
                if m_w:
                    val_f = float(m_w.group(1))
                    if val_f < 1:
                        weight_pill = f"น้ำหนัก {int(val_f * 1000)} กรัม"
                    else:
                        weight_pill = f"น้ำหนัก {val_f:.1f}".rstrip('0').rstrip('.') + " กก."
                else:
                    weight_pill = f"น้ำหนัก {v_str}"
                break

    # 3.4 From conversionUnits (gross or net)
    if not weight_pill:
        units = detail.get('conversionUnits') or []
        for u in units:
            gw = u.get('conversionGross') or u.get('conversionNet')
            if gw and float(gw) > 0:
                f_gw = float(gw)
                if 'แพ็ค' in prod_name or 'ม้วน' in prod_name:
                    if f_gw < 1:
                        weight_pill = f"น้ำหนัก {int(f_gw * 1000)} กรัม/ม้วน"
                    else:
                        weight_pill = f"น้ำหนัก {f_gw:.1f}".rstrip('0').rstrip('.') + " กก./แพ็ค"
                elif f_gw < 1:
                    weight_pill = f"น้ำหนัก {int(f_gw * 1000)} กรัม"
                else:
                    weight_pill = f"น้ำหนัก {f_gw:.1f}".rstrip('0').rstrip('.') + " กก."
                break

    # 4. Extract Feature Pill (Pill 1: คุณสมบัติเด่น / ความปลอดภัย / เกรดวัสดุ / มอเตอร์)
    desc_lower = desc_raw.lower()
    name_lower = prod_name.lower()
    feat_pill = None

    if 'เทป' in name_lower or 'temflex' in name_lower or 'tape' in name_lower:
        feat_pill = "ไม่ลามไฟ ปลอดภัยสูง"
    elif ('เครื่องเชื่อม' in name_lower or 'ตู้เชื่อม' in name_lower or 'welding' in name_lower) and 'คีม' not in name_lower:
        if 'igbt' in desc_lower or 'igbt' in name_lower:
            feat_pill = "ระบบ IGBT ลากยาวไม่สะดุด"
        else:
            feat_pill = "เชื่อมลากยาว ลวดไม่ติด"
    elif 'เครื่องฉีดน้ำ' in name_lower or 'washer' in name_lower or 'ปั๊มอัดฉีด' in name_lower:
        feat_pill = "ดูดน้ำจากถังได้อัตโนมัติ"
    elif 'พัดลม' in name_lower or 'ดูดเป่า' in name_lower or 'blower' in name_lower:
        if 'อลูมิเนียม' in desc_lower or 'ใบพัด' in desc_lower:
            feat_pill = "ใบพัดอลูมิเนียม ลมแรงสูง"
        else:
            feat_pill = "ระบายอากาศเยี่ยม ลมแรงดี"
    elif 'ตัดหญ้า' in name_lower or 'เครื่องยนต์' in name_lower:
        feat_pill = "สตาร์ทติดง่าย ลุยงานหนัก"
    elif 'ดอกสว่าน' in name_lower or 'step drill' in name_lower or 'ดอกเจาะ' in name_lower:
        if 'hss' in desc_lower or 'hss' in name_lower:
            feat_pill = "เคลือบไทเทเนียม HSS แท้"
        else:
            feat_pill = "เจาะคม เที่ยงตรง ทนทาน"
    elif 'คีม' in name_lower or 'ประแจ' in name_lower or 'ลูกบล็อก' in name_lower:
        if 'cr-v' in desc_lower or 'chrome vanadium' in desc_lower:
            feat_pill = "เหล็ก CR-V ชุบแข็งพิเศษ"
        else:
            feat_pill = "เหล็กเกรดพรีเมียม ปากจับแน่น"
    elif any(k in name_lower for k in ['เครื่องเจียร์', 'สว่าน', 'เลื่อย', 'ขัดกระดาษทราย', 'เป่าลม', 'ทริมเมอร์', 'เร้าเตอร์']):
        if 'ไร้แปรงถ่าน' in desc_lower or 'brushless' in desc_lower or 'brushless' in name_lower or '-bl' in name_lower:
            feat_pill = "มอเตอร์ Brushless ทนทาน"
        else:
            feat_pill = "มอเตอร์ทองแดงแท้ 100%"
    elif 'ปั๊มน้ำ' in name_lower or 'ปั๊มจุ่ม' in name_lower or 'ปั๊มแช่' in name_lower:
        feat_pill = "ระบบป้องกันมอเตอร์ไหม้"
    elif 'บันได' in name_lower:
        feat_pill = "อลูมิเนียมหนา รับน้ำหนักสูง"
    elif 'แม่แรง' in name_lower:
        feat_pill = "เหล็กหนาพิเศษ ปลอดภัยสูง"
    else:
        if 'ไม่ลามไฟ' in desc_lower or 'flame retardant' in desc_lower:
            feat_pill = "ไม่ลามไฟ ปลอดภัยสูง"
        elif 'ทองแดงแท้' in desc_lower:
            feat_pill = "มอเตอร์ทองแดงแท้ 100%"
        elif 'cr-v' in desc_lower or 'chrome vanadium' in desc_lower:
            feat_pill = "เหล็ก CR-V ชุบแข็งพิเศษ"
        elif 'สเตนเลส' in desc_lower or 'stainless' in desc_lower:
            feat_pill = "สแตนเลสแท้ ทนสนิม"
        elif 'ฉนวน' in desc_lower:
            feat_pill = "ฉนวนสองชั้น ปลอดภัยสูง"
        else:
            feat_pill = "มาตรฐานสากล ทนทานสูง"

    # Assemble hero_pills (Pill 1: Key Feature, Pill 2: Weight or Standout Value)
    hero_pills = []
    if feat_pill:
        hero_pills.append(feat_pill)
    if weight_pill:
        hero_pills.append(weight_pill)
    elif len(specs_dict) >= 1 and len(hero_pills) < 2:
        hero_pills.append("รับประกันของแท้ 100%")
    if not hero_pills:
        hero_pills = ["สินค้ารับประกันของแท้ 100%"]

    # 5. Spec cards with STRICT BIDIRECTIONAL DEDUPLICATION
    # (Never duplicate weight from Pill 2, feature concepts from Pill 1, or same metric types across cards)
    sorted_specs = sorted(specs_dict.items(), key=_spec_priority)
    spec_cards = []
    seen_values = set()
    seen_types = set()
    feat_lower_check = (feat_pill or '').lower()

    for k, v in sorted_specs:
        if len(spec_cards) >= 4:
            break
        val_clean = str(v).strip()
        val_norm = re.sub(r'\s+', '', val_clean).lower()
        k_lower = k.lower()

        if val_norm in seen_values:
            continue

        # 5.1 Strict Anti-Duplication against Pill 2 (Weight)
        if weight_pill and ('น้ำหนัก' in k_lower or 'weight' in k_lower):
            continue

        # 5.2 Strict Anti-Duplication against Pill 1 (Feature)
        if 'igbt' in feat_lower_check and 'igbt' in (k_lower + ' ' + val_norm):
            continue
        if 'ไม่ลามไฟ' in feat_lower_check and ('ไม่ลามไฟ' in (k_lower + ' ' + val_norm) or 'เชื้อไฟ' in (k_lower + ' ' + val_norm)):
            continue
        if 'ดูดน้ำ' in feat_lower_check and 'ดูดน้ำ' in (k_lower + ' ' + val_norm):
            continue
        if 'ทองแดง' in feat_lower_check and 'ทองแดง' in (k_lower + ' ' + val_norm):
            continue
        if 'cr-v' in feat_lower_check and 'cr-v' in (k_lower + ' ' + val_norm):
            continue
        if 'ไทเทเนียม' in feat_lower_check and ('ไทเทเนียม' in (k_lower + ' ' + val_norm) or 'hss' in (k_lower + ' ' + val_norm)):
            continue

        # 5.3 Metric Type Deduplication (Never allow two pressure, power, speed, or flow cards)
        m_type = None
        if 'บาร์' in val_norm or 'psi' in val_norm or bool(re.search(r'\d\s*bar\b', val_clean, re.I)):
            m_type = 'pressure'
        elif any(u in val_norm for u in ['ลิตร/นาที', 'ลิตร/ชม', 'flow', 'l/min', 'l/hr']):
            m_type = 'flow'
        elif any(u in val_norm for u in ['วัตต์', 'กิโลวัตต์', 'kva', 'kw']) or bool(re.search(r'\d\s*w\b', val_clean, re.I)):
            m_type = 'power'
        elif any(u in val_norm for u in ['รอบ/นาที', 'รอบต่อนาที', 'rpm']):
            m_type = 'speed'
        elif 'แอมป์' in val_norm or bool(re.search(r'\d\s*amp\b', val_clean, re.I)):
            m_type = 'current'
        elif 'สายฉีด' in k:
            m_type = 'hose'
        elif 'สายไฟ' in k:
            m_type = 'cord'

        if m_type and m_type in seen_types:
            continue

        # 5.4 Skip pure accessory package pieces (e.g. "1 ชิ้น") if technical specs are available
        if '1 ชิ้น' in val_clean and len(sorted_specs) > 4:
            continue

        # 5.5 Skip 220V power supply card ONLY if we already have >= 4 other usable non-weight specs
        usable_non_220 = sum(
            1 for sk, sv in sorted_specs
            if not (weight_pill and ('น้ำหนัก' in sk.lower() or 'weight' in sk.lower()))
            and not ('220' in str(sv) or 'แรงดันไฟฟ้า' in sk)
        )
        if ('220' in str(v) or 'แรงดันไฟฟ้า' in k) and any(t in seen_types for t in ['power', 'current']) and usable_non_220 >= 4:
            continue

        # Determine icon (always vector-supported)
        matched_icon = '⚡'
        for ik, iv in icon_map.items():
            if ik in k:
                matched_icon = iv
                break

        spec_cards.append({"icon": matched_icon, "label": k, "val": val_clean})
        seen_values.add(val_norm)
        if m_type:
            seen_types.add(m_type)
        m_w = re.search(r'(\d+)\s*(?:วัตต์|w\b)', val_clean, re.I)
        if m_w:
            seen_values.add(m_w.group(1))

    # Clean description for display & Layer 4 backfill
    clean_desc = re.sub(r'<br\s*/?>', '\n', detail.get('description', '') or '', flags=re.IGNORECASE)
    clean_desc = re.sub(r'</p>', '\n', clean_desc, flags=re.IGNORECASE)
    clean_desc = re.sub(r'<[^>]+>', '', clean_desc).strip()

    # Layer 4: Universal KTW Feature/Attribute Backfill (ONLY when < 4 cards from SAP + numeric extraction)
    if len(spec_cards) < 4:
        existing_blob = ' '.join([f"{c['label']} {c['val']}" for c in spec_cards] + hero_pills).lower()
        ctx_all = f"{prod_name} {detail.get('summary', '') or ''} {clean_desc}"
        backfill_candidates = []
        # 4a. Structured universal attributes detected directly from KTW text
        if ('น้ำ-แห้ง' in ctx_all or 'เปียกและแห้ง' in ctx_all) and 'น้ำ' not in existing_blob:
            backfill_candidates.append(('⚙️', 'รูปแบบการใช้งาน', 'ดูดได้ทั้งน้ำและแห้ง'))
        if ('กางปรับพาด' in ctx_all or 'ปรับพาด' in ctx_all) and 'กาง' not in existing_blob:
            backfill_candidates.append(('⚙️', 'รูปแบบบันได', 'กางใช้งาน / ปรับพาดได้'))
        m_modes = re.search(r'(\d+)\s*(?:ระบบ|โหมด)', ctx_all)
        if m_modes and 'โหมด' not in existing_blob and 'ระบบการทำงาน' not in existing_blob:
            backfill_candidates.append(('⚙️', 'โหมดการทำงาน', f"ปรับได้ {m_modes.group(1)} ระบบ"))
        if 'ซ้าย-ขวา' in ctx_all and 'ซ้าย-ขวา' not in existing_blob:
            backfill_candidates.append(('⚙️', 'ฟังก์ชันเสริม', 'ปรับหมุนซ้าย-ขวาได้'))
        if ('ใบพัดอลูมิเนียม' in ctx_all or 'อลูมิเนียม' in ctx_all) and 'อลูมิเนียม' not in existing_blob:
            backfill_candidates.append(('🛡️', 'วัสดุตัวเครื่อง', 'อลูมิเนียมคุณภาพสูง'))
        elif ('สแตนเลส' in ctx_all or 'สเตนเลส' in ctx_all) and 'สแตนเลส' not in existing_blob and 'สเตนเลส' not in existing_blob:
            backfill_candidates.append(('🛡️', 'วัสดุตัวเครื่อง', 'สแตนเลสแท้ ทนสนิม'))
        elif ('เหล็กกล้า' in ctx_all or 'เหล็กคุณภาพดี' in ctx_all or 'เหล็กชุบแข็ง' in ctx_all) and 'เหล็ก' not in existing_blob:
            backfill_candidates.append(('🛡️', 'วัสดุผลิต', 'เหล็กกล้าคุณภาพสูง ทนทาน'))
        if 'ระบบกรอง' in ctx_all or 'HEPA' in ctx_all.upper():
            if 'hepa' in ctx_all.lower() and 'hepa' not in existing_blob:
                backfill_candidates.append(('🛡️', 'ระบบกรองฝุ่น', 'ฟิลเตอร์กรองฝุ่น HEPA'))
        if 'ปรับความเร็ว' in ctx_all and 'ปรับความเร็ว' not in existing_blob:
            backfill_candidates.append(('⚙️', 'การควบคุม', 'ปรับระดับความเร็วได้'))
        if 'ตัดแต่งกิ่งไม้' in ctx_all and 'กิ่งไม้' not in existing_blob:
            backfill_candidates.append(('✅', 'เหมาะสำหรับงาน', 'ตัดไม้ / ตัดแต่งกิ่งไม้'))

        # 4b. Short, factual non-warning KTW bullet lines from description (never hallucinated!)
        _WARN_HDRS = ('คำเตือน', 'ข้อควรระวัง', 'การบำรุงรักษา', 'เงื่อนไข', 'หมายเหตุ', 'อุปกรณ์มาตรฐาน', 'อุปกรณ์ในกล่อง')
        _SKIP_BULLET = ('ห้าม', 'โปรด', 'รับประกัน', 'ติดต่อ', 'ราคา', 'ส่งฟรี', 'รุ่น ', 'ไม่รวมแบต', 'รายละเอียดสินค้า', 'ลักษณะพิเศษ', 'คุณสมบัติ', 'ข้อมูลจำเพาะ')
        stop_b = False
        bullet_lbls = ['คุณสมบัติเด่น', 'จุดเด่นสินค้า', 'การใช้งาน']
        b_idx = 0
        for raw_ln in clean_desc.split('\n'):
            ln = raw_ln.strip().lstrip('•').lstrip('-').lstrip('*').lstrip('▪').strip()
            if not ln:
                continue
            if any(ln.startswith(wh) and len(ln) <= 32 for wh in _WARN_HDRS):
                stop_b = True
                continue
            if stop_b or ':' in ln or '：' in ln:
                continue
            if 10 <= len(ln) <= 36 and not any(sb in ln for sb in _SKIP_BULLET):
                ln_low = ln.lower()
                # Skip if already represented in title, pills, or existing cards
                if ln_low not in existing_blob and prod_name.lower()[:12] not in ln_low:
                    lbl_pick = bullet_lbls[min(b_idx, len(bullet_lbls) - 1)]
                    backfill_candidates.append(('✅', lbl_pick, ln))
                    b_idx += 1
                    if b_idx >= 2:
                        break

        seen_bf_lbls = {c['label'].strip().lower() for c in spec_cards}
        seen_bf_vals = {re.sub(r'\s+', '', c['val']).lower() for c in spec_cards}
        for ic, bl, bv in backfill_candidates:
            if len(spec_cards) >= 4:
                break
            if bl.lower() in seen_bf_lbls or re.sub(r'\s+', '', bv).lower() in seen_bf_vals:
                continue
            spec_cards.append({"icon": ic, "label": bl, "val": bv})
            seen_bf_lbls.add(bl.lower())
            seen_bf_vals.add(re.sub(r'\s+', '', bv).lower())

    is_bigpower = bool(shop_name and ('bigpower' in shop_name.lower() or 'big power' in shop_name.lower() or 'shop2' in shop_name.lower() or 'shop_2' in shop_name.lower()))
    official_shop_name = "BIGPOWER TOOLS" if is_bigpower else "MEGATOOL"

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

    if isinstance(custom_saved, dict):
        changed_saved = False
        custom_saved = dict(custom_saved)
        saved_cards = [c for c in (custom_saved.get("custom_spec_cards") or []) if isinstance(c, dict) and c.get("label") and c.get("val")]
        if len(saved_cards) < 4 and len(spec_cards) > len(saved_cards):
            custom_saved["custom_spec_cards"] = enrich_spec_cards(saved_cards, spec_cards)
            changed_saved = True
        saved_cat = custom_saved.get("custom_category")
        if saved_cat and is_stale_truncated_category(saved_cat, custom_saved.get("custom_model") or model_code):
            custom_saved["custom_category"] = category_title
            changed_saved = True
        _ = changed_saved

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
