import os
import io
import json
import time
import re
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
    shop_subtitle="เมก้า ทูล",
    overwrite=True
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
    if not overwrite and output_path and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
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

def upload_to_cdn(image_path, max_retries=1):
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
            cached_url = _MEM_CACHE[cache_key]
            # Skip known expired or invalid test prefix
            if not cached_url.startswith('https://iili.io/njU'):
                return cached_url

    url = 'https://freeimage.host/api/1/upload'
    api_key = '6d207e02198a847aa98d0a2a901485a5'

    
    for attempt in range(max_retries):
        try:
            with open(image_path, 'rb') as f:
                r = requests.post(
                    url,
                    data={'key': api_key, 'action': 'upload', 'format': 'json'},
                    files={'source': f},
                    timeout=5
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

def fetch_image_safe(url_or_path):
    if not url_or_path:
        raise ValueError("Empty image path or url")
    
    # 1. Clean path prefixes
    if str(url_or_path).startswith('/ktwcommercewebservices/v2'):
        url_or_path = str(url_or_path).replace('/ktwcommercewebservices/v2', '')
        
    # 2. Local static files on disk
    if str(url_or_path).startswith('/static/'):
        disk_p = f"app{url_or_path}"
        if os.path.exists(disk_p):
            return Image.open(disk_p).convert('RGBA')
    elif str(url_or_path).startswith('static/'):
        disk_p = f"app/{url_or_path}"
        if os.path.exists(disk_p):
            return Image.open(disk_p).convert('RGBA')
    elif os.path.exists(str(url_or_path)):
        return Image.open(str(url_or_path)).convert('RGBA')

    # 3. KTW root-relative URLs
    if str(url_or_path).startswith('/'):
        url_or_path = f"https://shop.ktw.co.th{url_or_path}"

    # 4. Web URLs with robust headers and retries
    if str(url_or_path).startswith('http'):
        last_err = None
        for attempt in range(2):
            try:
                resp = requests.get(url_or_path, headers=BROWSER_HEADERS, timeout=15)
                if resp.status_code == 200 and len(resp.content) > 100:
                    return Image.open(io.BytesIO(resp.content)).convert('RGBA')
            except Exception as e:
                last_err = e
                time.sleep(0.5)
        if last_err:
            raise last_err

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

def generate_collage(
    image_urls,
    output_path,
    title="อุปกรณ์มาตรฐานในชุดครบเซ็ต",
    badge_text="มีสต็อกพร้อมส่งทันที",
    shop_name="MEGATOOL"
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
    WHITE = (255, 255, 255, 255)

    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), WHITE)
    draw = ImageDraw.Draw(canvas)

    # 1. Load and trim images
    loaded_imgs = []
    for u in image_urls[:4]:
        try:
            raw_im = fetch_image_safe(u)
            trimmed = trim_white_space(raw_im)
            loaded_imgs.append(trimmed)
        except Exception as e:
            print("Error loading image for collage:", e)

    if not loaded_imgs:
        raise ValueError("ไม่สามารถดาวน์โหลดรูปภาพได้ กรุณาลองใหม่อีกครั้ง")

    count = len(loaded_imgs)

    # 2. Layout Grid Slots (Safe zones: never intersects with top-right logo or bottom-right ribbon!)
    # Top bar area: y: 35..130 (Top-left: Title pill, Top-right: MEGATOOL logo)
    # Bottom-right area: x: 570..1200, y: 920..1200 (Ribbon + ของแท้ 100%)
    slots = []
    gap = 20

    if count == 2:
        # 2 large cards side-by-side
        w_each = 530
        slots.append([45, 145, 45 + w_each, 1140])       # Left: large tool
        slots.append([45 + w_each + gap, 145, 1155, 920]) # Right: accessories (safe above ribbon)

    elif count == 3:
        # 1 large left (main tool) + 2 right (accessories & box)
        w_left = 530
        h_right_each = 365
        slots.append([45, 145, 45 + w_left, 1140])                                              # Left full height
        slots.append([45 + w_left + gap, 145, 1155, 145 + h_right_each])                        # Top right
        slots.append([45 + w_left + gap, 145 + h_right_each + gap, 1155, 145 + (h_right_each * 2) + gap]) # Middle right (stops at y=895, safely above ribbon!)

    else: # 4 images
        # 2x2 grid
        # Col 1 (Left): x: 45..585 (can go down to y=1140)
        # Col 2 (Right): x: 605..1155 (Top: y: 145..520, Bottom: y: 540..915, strictly above y=920 ribbon!)
        slots.append([45, 145, 585, 620])   # Slot 1: Top-Left
        slots.append([605, 145, 1155, 520])  # Slot 2: Top-Right
        slots.append([45, 640, 585, 1140])  # Slot 3: Bottom-Left
        slots.append([605, 540, 1155, 915])  # Slot 4: Bottom-Right (Safe above ribbon!)

    font_num = load_font("tahomabd.ttf", 26)

    # 3. Draw each image inside its slot
    for idx, (slot, img) in enumerate(zip(slots, loaded_imgs)):
        sx1, sy1, sx2, sy2 = slot
        # Draw soft card border
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

        # Number Circle Badge ① ② ③ ④
        badge_r = 20
        bx = sx1 + 16
        by = sy1 + 16
        draw.ellipse([bx, by, bx + (badge_r * 2), by + (badge_r * 2)], fill=RED)
        num_str = str(idx + 1)
        nb = font_num.getbbox(num_str)
        nw = nb[2] - nb[0]
        nh = nb[3] - nb[1]
        draw.text((bx + badge_r - nw // 2, by + badge_r - nh // 2 - 2), num_str, font=font_num, fill=WHITE)

    # 4. Top-Left Title Badge Pill (Opposite MEGATOOL Logo)
    f_title = load_font("leelawdb.ttf", 30)
    # Strip emojis and leading symbols that cause square tofu boxes
    clean_title = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]', '', str(title)).strip()
    if not clean_title:
        clean_title = "อุปกรณ์มาตรฐานในกล่องครบชุด"

    # Ensure text fits comfortably within safe zone before logo
    max_text_w = 540
    while len(clean_title) > 5:
        b = f_title.getbbox(clean_title)
        if (b[2] - b[0]) <= max_text_w:
            break
        clean_title = clean_title[:-1]

    tb = f_title.getbbox(clean_title)
    tw = tb[2] - tb[0]
    
    pill_x1 = 45
    pill_y1 = 42
    pill_x2 = min(620, pill_x1 + tw + 36)
    pill_y2 = pill_y1 + 54
    draw.rounded_rectangle([pill_x1, pill_y1, pill_x2, pill_y2], radius=14, fill=(15, 23, 42, 255))
    draw.text((pill_x1 + 18, pill_y1 + 8), clean_title, font=f_title, fill=WHITE)

    # 5. Top-Right: Official MEGATOOL Red Logo (Exact shop template)
    border_w = 22
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
    margin_right = 50
    margin_top = 38

    x_start = CANVAS_SIZE - margin_right - total_w
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

    # 6. Bottom-Right: Slanted Red Ribbon Banner
    banner_h = 120
    y_top = CANVAS_SIZE - banner_h
    y_bot = CANVAS_SIZE
    x_slant_bot = 570
    x_slant_top = 635

    draw.polygon([
        (x_slant_bot, y_bot),
        (CANVAS_SIZE, y_bot),
        (CANVAS_SIZE, y_top),
        (x_slant_top, y_top)
    ], fill=RED)

    display_banner_text = badge_text or "มีสต็อกพร้อมส่งทันที"
    f_banner = load_font('tahomabd.ttf', 48)
    text_center_x = (x_slant_top + CANVAS_SIZE - border_w) // 2
    text_center_y = y_top + (banner_h // 2) - 4
    draw.text((text_center_x, text_center_y), display_banner_text, fill=WHITE, font=f_banner, anchor='mm')

    # 7. Above Banner: 'ของแท้ 100%'
    f_badge_thai = load_font('tahomabd.ttf', 54)
    f_badge_num = load_font('arialbd.ttf', 62)
    badge_y = y_top - 58

    num_str = "100%"
    thai_str = "ของแท้"

    num_box = draw.textbbox((0, 0), num_str, font=f_badge_num)
    num_w = num_box[2] - num_box[0]
    thai_box = draw.textbbox((0, 0), thai_str, font=f_badge_thai)
    thai_w = thai_box[2] - thai_box[0]

    num_x = CANVAS_SIZE - 45 - num_w
    thai_x = num_x - 30 - thai_w

    draw.text((thai_x, badge_y), thai_str, fill=RED, font=f_badge_thai, anchor='ls')
    draw.text((num_x, badge_y), num_str, fill=RED, font=f_badge_num, anchor='ls')

    draw.line([(num_x - 4, badge_y - 64), (num_x + num_w + 4, badge_y - 64)], fill=RED, width=4)
    draw.line([(num_x - 4, badge_y + 8), (num_x + num_w + 4, badge_y + 8)], fill=RED, width=4)

    # 8. Outer Red Border (drawn LAST so it cleanly frames everything!)
    draw.rectangle([(0, 0), (CANVAS_SIZE - 1, CANVAS_SIZE - 1)], outline=RED, width=border_w)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    canvas.convert('RGB').save(output_path, "JPEG", quality=95)
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
    """
    if not sku:
        return []
    db = _load_collages_db()
    urls = []
    
    # 1. From JSON db
    if sku in db:
        for item in db[sku]:
            if isinstance(item, dict):
                u = item.get("cdn_url") or item.get("url")
            else:
                u = str(item)
            if u and u not in urls:
                urls.append(u)
                
    # 2. From local disk scan (self-healing for any pre-generated collages)
    covers_dir = "app/static/covers"
    if os.path.exists(covers_dir):
        prefix = f"collage_{sku}_"
        for fname in os.listdir(covers_dir):
            if fname.startswith(prefix) and fname.endswith(".jpg"):
                local_rel = f"/static/covers/{fname}"
                if not any(fname in u for u in urls):
                    urls.append(local_rel)
                    save_custom_product_image(sku, local_rel)
                    
    return urls

def delete_custom_product_image(sku: str, image_url: str) -> bool:
    """
    Permanently deletes a custom collage image for a SKU from both JSON db and disk.
    """
    if not sku or not image_url:
        return False
    db = _load_collages_db()
    removed = False
    target_fname = image_url.split('/')[-1].split('?')[0]
    
    if sku in db:
        new_list = []
        for item in db[sku]:
            u = (item.get("url") or item.get("cdn_url")) if isinstance(item, dict) else str(item)
            if target_fname in u or image_url == u:
                removed = True
            else:
                new_list.append(item)
        db[sku] = new_list
        _save_collages_db(db)
        
    # Delete physical file on disk
    if target_fname.startswith("collage_") and target_fname.endswith(".jpg"):
        disk_p = os.path.join("app/static/covers", target_fname)
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

def extract_model_label(name, sku):
    clean_name = re.sub(r'\[.*?\]', '', name).strip()
    words = clean_name.split()
    sku_code = sku.split('-')[-1] if '-' in sku else sku
    model_code = words[0] if words else sku_code
    
    sub = ""
    bar_m = re.search(r'(\d+\s*บาร์)', clean_name)
    watt_m = re.search(r'(\d+\s*[wWวัตต์]+)', clean_name)
    volt_m = re.search(r'(\d+\s*[vVโวลต์]+)', clean_name)
    inch_m = re.search(r'(\d+\s*นิ้ว)', clean_name)
    pack_m = re.search(r'(\d+\s*ม้วน)', clean_name)
    
    if bar_m:
        sub = f"แรงดัน {bar_m.group(1)}"
    elif watt_m:
        sub = f"กำลังไฟ {watt_m.group(1)}"
    elif volt_m:
        sub = f"ระบบ {volt_m.group(1)}"
    elif inch_m:
        sub = f"ขนาด {inch_m.group(1)}"
    elif pack_m:
        sub = f"แพ็ค {pack_m.group(1)}"
    elif len(words) > 1:
        sub = " ".join(words[1:3])
        if len(sub) > 14:
            sub = sub[:12] + "..."
            
    return model_code, sub

def extract_key_specs(detail):
    specs = {}
    if not detail:
        return specs
        
    # 1. From SAP Classifications (Makita & SAP items)
    classifs = detail.get('classifications', []) or []
    for c in classifs:
        for f in c.get('features', []):
            name = f.get('name') or f.get('description') or ''
            vals = f.get('featureValues', [])
            val_str = ', '.join([v.get('value', '') for v in vals if v.get('value')])
            if name and val_str and val_str != '-':
                if 'กำลังไฟ' in name or 'continuous_rating' in f.get('code', ''):
                    specs['กำลังไฟฟ้า'] = val_str
                elif 'ความเร็วรอบ' in name or 'no_load_speed' in f.get('code', ''):
                    specs['ความเร็วรอบ'] = val_str
                elif 'เส้นผ่านศูนย์กลาง' in name or 'grinding_diameter' in f.get('code', ''):
                    specs['ขนาดใบตัด/เจียร์'] = val_str
                elif 'น้ำหนัก' in name or 'weight' in f.get('code', ''):
                    specs['น้ำหนักตัวเครื่อง'] = val_str
                elif 'ขนาดแกน' in name or 'spindle' in f.get('code', ''):
                    specs['ขนาดแกนเกลียว'] = val_str
                elif 'สายไฟ' in name or 'cord' in f.get('code', ''):
                    specs['ความยาวสายไฟ'] = val_str
                elif 'แรงดัน' in name:
                    specs['แรงดันสูงสุด'] = val_str
                elif 'อัตราการไหล' in name or 'ปริมาณน้ำ' in name:
                    specs['อัตราการไหลของน้ำ'] = val_str

    # 2. From Description bullet points (POLO, DongCheng, consumables, etc.)
    desc = detail.get('description', '') or ''
    clean_desc = re.sub(r'<br\s*/?>', '\n', desc, flags=re.IGNORECASE)
    clean_desc = re.sub(r'</p>', '\n', clean_desc, flags=re.IGNORECASE)
    clean_desc = re.sub(r'<[^>]+>', '', clean_desc)

    for line in clean_desc.split('\n'):
        line = line.strip().lstrip('•').lstrip('-').lstrip('*').strip()
        if not line:
            continue
        if ':' in line or '：' in line:
            parts = re.split(r'[:：]', line, maxsplit=1)
            k = parts[0].strip()
            v = parts[1].strip()
            if k and v and len(k) < 30 and len(v) < 60:
                if 'กำลังไฟ' in k and 'กำลังไฟฟ้า' not in specs:
                    specs['กำลังไฟฟ้า'] = v
                elif 'แรงดัน' in k and 'แรงดันสูงสุด' not in specs:
                    specs['แรงดันสูงสุด'] = v
                elif ('ปริมาณน้ำ' in k or 'อัตราการไหล' in k or 'อัตราการฉีด' in k) and 'อัตราการไหลของน้ำ' not in specs:
                    specs['อัตราการไหลของน้ำ'] = v
                elif 'สาย' in k and 'ความยาวสายฉีด' not in specs:
                    specs['ความยาวสายฉีด'] = v
                elif 'น้ำหนัก' in k and 'น้ำหนักตัวเครื่อง' not in specs:
                    specs['น้ำหนักตัวเครื่อง'] = v
                elif 'มอเตอร์' in k and 'ประเภทมอเตอร์' not in specs:
                    specs['ประเภทมอเตอร์'] = v
                elif 'ความเร็วรอบ' in k and 'ความเร็วรอบ' not in specs:
                    specs['ความเร็วรอบ'] = v
        elif 'Auto Stop' in line and 'ระบบตัดการทำงาน' not in specs:
            specs['ระบบตัดการทำงาน'] = 'ระบบ Auto Stop'

    # 3. Fallback from conversionUnits if weight missing
    if 'น้ำหนักตัวเครื่อง' not in specs:
        units = detail.get('conversionUnits', [])
        if units:
            net_w = units[0].get('netWeight', 0)
            if net_w:
                specs['น้ำหนักตัวเครื่อง'] = f"{round(net_w / 1000.0, 2)} กก."
                
    return specs

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
    font_model_sub = load_font("leelawdb.ttf", 16)
    font_price = load_font("tahomabd.ttf", 26)
    font_label = load_font("leelawdb.ttf", 20)
    font_val = load_font("leelawdb.ttf", 18)
    font_footer = load_font("leelawdb.ttf", 19)

    # 1. Header (y: 30 to 115)
    header_box = [30, 30, CANVAS_SIZE - 30, 115]
    draw.rounded_rectangle(header_box, radius=18, fill=(15, 23, 42, 255))

    draw.text((60, 42), f"📊 {parent_title[:45]}", font=font_title, fill=(255, 255, 255, 255))
    draw.text((60, 82), "ตารางเปรียบเทียบสเปกเพื่อให้คุณเลือกรุ่นที่ตอบโจทย์งานที่สุด", font=font_sub, fill=(203, 213, 225, 255))

    shop_str = f"{shop_name} OFFICIAL"
    sb = font_sub.getbbox(shop_str)
    sw = sb[2] - sb[0]
    draw.text((CANVAS_SIZE - 70 - sw, 60), shop_str, font=font_sub, fill=(249, 115, 22, 255))

    processed_items = []
    all_spec_keys = []
    preferred_order = [
        'แรงดันสูงสุด', 'กำลังไฟฟ้า', 'อัตราการไหลของน้ำ', 'ความเร็วรอบ',
        'ขนาดใบตัด/เจียร์', 'ความยาวสายฉีด', 'ระบบตัดการทำงาน', 'น้ำหนักตัวเครื่อง'
    ]

    for item in items[:4]:
        sku = item.get('sku')
        detail = get_product_detail(sku)
        specs = extract_key_specs(detail)
        
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

        raw_name = item.get('name') or sku
        model_code, model_sub = extract_model_label(raw_name, sku)

        processed_items.append({
            'sku': sku,
            'name': raw_name,
            'model_code': model_code,
            'model_sub': model_sub,
            'price': item.get('price', 0),
            'specs': specs,
            'thumb': thumb_im
        })

    # Sort specs by preferred order
    ordered_keys = [k for k in preferred_order if k in all_spec_keys]
    for k in all_spec_keys:
        if k not in ordered_keys:
            ordered_keys.append(k)
    ordered_keys = ordered_keys[:6]

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
        nb = font_model.getbbox(m_code)
        nw = nb[2] - nb[0]
        draw.text((pill_x1 + (pill_w - nw) // 2, pill_y1 + 5), m_code, font=font_model, fill=(255, 255, 255, 255))

        # Line 2: Subtitle / Spec tag (e.g. แรงดัน 90 บาร์)
        if m['model_sub']:
            sb = font_model_sub.getbbox(m['model_sub'])
            sw = sb[2] - sb[0]
            draw.text((col_x + (model_col_w - sw) // 2, tbl_top + 192), m['model_sub'], font=font_model_sub, fill=(100, 116, 139, 255))

        # Price
        price_str = f"฿{m['price']:,.0f}" if m['price'] else "-"
        pb = font_price.getbbox(price_str)
        pw = pb[2] - pb[0]
        draw.text((col_x + (model_col_w - pw) // 2, tbl_top + 235), price_str, font=font_price, fill=(239, 28, 37, 255))

    rows_h = (tbl_bottom - (tbl_top + thumb_row_h))
    row_count = len(ordered_keys) + 1
    row_h = rows_h // row_count

    for r_idx, key in enumerate(ordered_keys):
        ry1 = tbl_top + thumb_row_h + (r_idx * row_h)
        ry2 = ry1 + row_h
        
        bg_color = (255, 255, 255, 255) if r_idx % 2 == 0 else (248, 250, 252, 255)
        draw.rectangle([tbl_left + 2, ry1, tbl_right - 2, ry2], fill=bg_color)
        draw.line([tbl_left, ry2, tbl_right, ry2], fill=(226, 232, 240, 255), width=1)

        draw.text((tbl_left + 25, ry1 + (row_h - 22) // 2), f"• {key}", font=font_label, fill=(51, 65, 85, 255))

        for idx, m in enumerate(processed_items):
            col_x = tbl_left + label_col_w + (idx * model_col_w)
            val = m['specs'].get(key, "-")
            if len(val) > 26:
                val = val[:24] + "..."
            vb = font_val.getbbox(val)
            vw = vb[2] - vb[0]
            draw.text((col_x + (model_col_w - vw) // 2, ry1 + (row_h - 20) // 2), val, font=font_val, fill=(15, 23, 42, 255))

    last_ry1 = tbl_top + thumb_row_h + (len(ordered_keys) * row_h)
    draw.rectangle([tbl_left + 2, last_ry1, tbl_right - 2, tbl_bottom - 2], fill=(241, 245, 249, 255))
    draw.text((tbl_left + 25, last_ry1 + (row_h - 22) // 2), "• การรับประกันศูนย์", font=font_label, fill=(51, 65, 85, 255))
    for idx, m in enumerate(processed_items):
        col_x = tbl_left + label_col_w + (idx * model_col_w)
        w_text = "ของแท้ 100% ประกันศูนย์"
        wb = font_val.getbbox(w_text)
        ww = wb[2] - wb[0]
        draw.text((col_x + (model_col_w - ww) // 2, last_ry1 + (row_h - 20) // 2), w_text, font=font_val, fill=(16, 185, 129, 255))

    for idx in range(num_models):
        col_x = tbl_left + label_col_w + (idx * model_col_w)
        draw.line([col_x, tbl_top + thumb_row_h, col_x, tbl_bottom], fill=(226, 232, 240, 255), width=2)

    footer_box = [30, 1130, CANVAS_SIZE - 30, 1175]
    draw.rounded_rectangle(footer_box, radius=12, fill=(241, 245, 249, 255))
    footer_text = "🛡️ MEGATOOL OFFICIAL STORE • สินค้าของแท้ 100% พร้อมจัดส่งด่วน • มีศูนย์บริการรองรับมาตรฐานสากล"
    ft_b = font_footer.getbbox(footer_text)
    ft_w = ft_b[2] - ft_b[0]
    draw.text(((CANVAS_SIZE - ft_w) // 2, 1142), footer_text, font=font_footer, fill=(71, 85, 105, 255))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    canvas.convert('RGB').save(output_path, "JPEG", quality=92)
    return output_path
