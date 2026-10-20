import os
import io
import json
import time
import requests
from PIL import Image, ImageDraw, ImageFont

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

def generate_cover(
    raw_img_path_or_url,
    output_path,
    brand=None,
    sku="",
    badge_text=None,
    custom_footer=None,
    shop_name="MEGATOOL",
    shop_subtitle="เมก้า ทูล"
):
    """
    Exact Zupertools Replica Template for Zonix Tools:
    - 1200x1200px Clean White background
    - Solid Red Outer Border (Zupertools Red #EF1C25)
    - Top-Right: ZonixTools. + โซนิกซ์ ทูลส์
    - Bottom-Right: 'ของแท้ 100%' with top/bottom lines + Slanted Red Ribbon
    - Ribbon Text: 'มีสต็อกพร้อมส่งทันที' (or custom text)
    - Product auto-cropped from whitespace and maximized to fill 80-85%
    - ZERO brand logo clutter (product branding is on the physical tool)
    """
    if output_path and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        return output_path

    RED = (239, 28, 37, 255) # #EF1C25
    WHITE = (255, 255, 255, 255)
    canvas_size = 1200
    
    # 1. Canvas
    canvas = Image.new('RGBA', (canvas_size, canvas_size), WHITE)
    draw = ImageDraw.Draw(canvas)
    
    # 2. Load Product Image (Original size & composition)
    if raw_img_path_or_url.startswith('http'):
        try:
            r = requests.get(raw_img_path_or_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            if r.status_code == 200 and len(r.content) > 100:
                raw_img = Image.open(io.BytesIO(r.content)).convert('RGBA')
            else:
                raw_img = Image.new('RGBA', (canvas_size, canvas_size), WHITE)
        except Exception:
            raw_img = Image.new('RGBA', (canvas_size, canvas_size), WHITE)
    else:
        if os.path.exists(raw_img_path_or_url):
            raw_img = Image.open(raw_img_path_or_url).convert('RGBA')
        else:
            raw_img = Image.new('RGBA', (canvas_size, canvas_size), WHITE)

    # 3. Fit original image directly to 1200x1200 (preserve exact original framing & proportions)
    w, h = raw_img.size
    scale = min(canvas_size / w, canvas_size / h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    resized_raw = raw_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    px = (canvas_size - new_w) // 2
    py = (canvas_size - new_h) // 2
    canvas.paste(resized_raw, (px, py), resized_raw if resized_raw.mode == 'RGBA' else None)

    # 4. Outer Red Frame (on top of image)
    border_w = 22
    draw.rectangle([(0, 0), (canvas_size - 1, canvas_size - 1)], outline=RED, width=border_w)

    # 4. Top-Right: Shop Logo (MEGATOOL with curved mustache under 'OO', no S, no dot)
    is_mega = not shop_name or 'mega' in shop_name.lower() or 'zonix' in shop_name.lower()

    if is_mega:
        f_prefix = load_font('arialbd.ttf', 84)
        f_tool = load_font('ariblk.ttf', 84)

        # Support both all-caps MEGATOOL and mixed MegaTool
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
        margin_right = 50
        margin_top = 38

        x_start = canvas_size - margin_right - total_w
        y_text = margin_top

        # Draw prefix (MEGA / Mega)
        draw.text((x_start, y_text), part_prefix, fill=RED, font=f_prefix)

        # Draw TOOL / tool (NO S, NO dot)
        xt = x_start + w_prefix
        draw.text((xt, y_text), char_t, fill=RED, font=f_tool)

        xo1 = xt + w_t
        draw.text((xo1, y_text), char_o1, fill=RED, font=f_tool)

        xo2 = xo1 + w_o1
        draw.text((xo2, y_text), char_o2, fill=RED, font=f_tool)

        xl = xo2 + w_o2
        draw.text((xl, y_text), char_l, fill=RED, font=f_tool)

        # Trademark curved smile mustache under OO
        o1_box = draw.textbbox((xo1, y_text), char_o1, font=f_tool)
        o2_box = draw.textbbox((xo2, y_text), char_o2, font=f_tool)
        arc_left = o1_box[0] + 6
        arc_right = o2_box[2] - 6
        arc_top = o1_box[3] - 16
        arc_bot = o1_box[3] + 16
        draw.arc([arc_left, arc_top, arc_right, arc_bot], start=10, end=170, fill=RED, width=7)
    else:
        # Fallback for custom generic shop names
        f_shop_main = load_font('arialbd.ttf', 76)
        margin_right = 50
        margin_top = 38
        title_text = shop_name.strip().rstrip('.')
        main_bbox = draw.textbbox((0, 0), title_text, font=f_shop_main)
        main_w = main_bbox[2] - main_bbox[0]
        x_main = canvas_size - margin_right - main_w
        draw.text((x_main, margin_top), title_text, fill=RED, font=f_shop_main)

    # 5. Bottom-Right: Slanted Red Ribbon Banner
    banner_h = 120
    y_top = canvas_size - banner_h
    y_bot = canvas_size
    
    x_slant_bot = 570
    x_slant_top = 635
    
    draw.polygon([
        (x_slant_bot, y_bot),
        (canvas_size, y_bot),
        (canvas_size, y_top),
        (x_slant_top, y_top)
    ], fill=RED)
    
    # Text inside ribbon (default: 'มีสต็อกพร้อมส่งทันที')
    display_banner_text = badge_text if (badge_text and badge_text != 'ของแท้ 100%') else "มีสต็อกพร้อมส่งทันที"
    
    f_banner = load_font('tahomabd.ttf', 48)
    text_center_x = (x_slant_top + canvas_size - border_w) // 2
    text_center_y = y_top + (banner_h // 2) - 4
    draw.text((text_center_x, text_center_y), display_banner_text, fill=WHITE, font=f_banner, anchor='mm')

    # 6. Above Banner: 'ของแท้  100%'
    f_badge_thai = load_font('tahomabd.ttf', 54)
    f_badge_num = load_font('arialbd.ttf', 62)
    
    badge_y = y_top - 58
    
    num_str = "100%"
    thai_str = "ของแท้"
    
    num_box = draw.textbbox((0, 0), num_str, font=f_badge_num)
    num_w = num_box[2] - num_box[0]
    
    thai_box = draw.textbbox((0, 0), thai_str, font=f_badge_thai)
    thai_w = thai_box[2] - thai_box[0]
    
    num_x = canvas_size - 45 - num_w
    thai_x = num_x - 30 - thai_w
    
    draw.text((thai_x, badge_y), thai_str, fill=RED, font=f_badge_thai, anchor='ls')
    draw.text((num_x, badge_y), num_str, fill=RED, font=f_badge_num, anchor='ls')
    
    line_w = 4
    draw.line([(num_x - 4, badge_y - 64), (num_x + num_w + 4, badge_y - 64)], fill=RED, width=line_w)
    draw.line([(num_x - 4, badge_y + 8), (num_x + num_w + 4, badge_y + 8)], fill=RED, width=line_w)

    # 7. Save
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    final_img = canvas.convert('RGB')
    final_img.save(output_path, 'JPEG', quality=95)
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

def upload_to_cdn(image_path, max_retries=3):
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
    with _CACHE_LOCK:
        if cache_key in _MEM_CACHE and _MEM_CACHE[cache_key] and 'iili.io' in _MEM_CACHE[cache_key]:
            return _MEM_CACHE[cache_key]

    url = 'https://freeimage.host/api/1/upload'
    api_key = '6d207e02198a847aa98d0a2a901485a5'

    
    for attempt in range(max_retries):
        try:
            with open(image_path, 'rb') as f:
                r = requests.post(
                    url,
                    data={'key': api_key, 'action': 'upload', 'format': 'json'},
                    files={'source': f},
                    timeout=20
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


