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
        margin_right = 32
        margin_top = 28

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
        margin_right = 32
        margin_top = 28
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
    
    badge_y = y_top - 22
    
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

def upload_to_cdn(image_path, max_retries=1, force=False):
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
    position="top-left"
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

    if count == 1:
        # 1 single image: full centered safe area inside template (no card border, no #1 badge)
        slots.append([45, 145, 1155, 1140])

    elif count == 2:
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
        # Draw soft card border only when multiple images are arranged
        if count > 1:
            draw.rounded_rectangle([sx1, sy1, sx2, sy2], radius=16, fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), width=2)
            pad = 20
        else:
            # Single image mode: clean floating product
            pad = 35

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

        # Number Circle Badge only when multiple images
        if count > 1:
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
    base_sz = max(26, min(56, base_sz))

    max_total_w = 555 if pos in ("top-left", "top-right") else (540 if pos == "bottom-left" else 780)
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
            pill_x2 = min(pill_x1 + total_w, 600)
            total_w = pill_x2 - pill_x1
            w_right = total_w - w_left
        elif pos == "top-right":
            total_w = min(total_w, max_total_w)
            pill_x1 = max(600, CANVAS_SIZE - 45 - total_w)
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

        if pos in ("center", "bottom-left"):
            draw.rounded_rectangle([pill_x1 + 3, pill_y1 + 4, pill_x2 + 3, pill_y2 + 4], radius=16, fill=(0, 0, 0, 70))

        draw.rounded_rectangle([pill_x1, pill_y1, pill_x2, pill_y2], radius=16, fill=SLATE)
        draw.rounded_rectangle([pill_x1, pill_y1, pill_x1 + w_left, pill_y2], radius=16, fill=RED)
        draw.rectangle([pill_x1 + w_left - 16, pill_y1, pill_x1 + w_left, pill_y2], fill=RED)

        hm = bm[3] - bm[1]
        tx_m = pill_x1 + (w_left - wm) // 2
        ty_m = pill_y1 + (pill_h - hm) // 2 - bm[1]
        draw.text((tx_m, ty_m), clean_model, font=f_m, fill=WHITE)

        start_ty = pill_y1 + (pill_h - total_lines_h) // 2
        curr_y = start_ty
        for i, l in enumerate(lines):
            b = line_boxes[i]
            lw = b[2] - b[0]
            lx = pill_x1 + w_left + (w_right - lw) // 2
            draw.text((lx, curr_y - b[1]), l, font=f_t, fill=WHITE)
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
            pill_x2 = min(pill_x1 + total_w, 600)
            total_w = pill_x2 - pill_x1
        elif pos == "top-right":
            total_w = min(total_w, max_total_w)
            pill_x1 = max(600, CANVAS_SIZE - 45 - total_w)
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

        if pos in ("center", "bottom-left"):
            draw.rounded_rectangle([pill_x1 + 3, pill_y1 + 4, pill_x2 + 3, pill_y2 + 4], radius=16, fill=(0, 0, 0, 70))
        draw.rounded_rectangle([pill_x1, pill_y1, pill_x2, pill_y2], radius=16, fill=RED)

        hm = bm[3] - bm[1]
        tx_m = pill_x1 + (total_w - wm) // 2
        ty_m = pill_y1 + (pill_h - hm) // 2 - bm[1]
        draw.text((tx_m, ty_m), clean_model, font=f_m, fill=WHITE)

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
            pill_x2 = min(pill_x1 + pill_w, 600)
            pill_w = pill_x2 - pill_x1
        elif pos == "top-right":
            pill_w = min(pill_w, max_total_w)
            pill_x1 = max(600, CANVAS_SIZE - 45 - pill_w)
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

        if pos in ("center", "bottom-left"):
            draw.rounded_rectangle([pill_x1 + 3, pill_y1 + 4, pill_x2 + 3, pill_y2 + 4], radius=16, fill=(0, 0, 0, 70))
        draw.rounded_rectangle([pill_x1, pill_y1, pill_x2, pill_y2], radius=16, fill=SLATE)

        start_ty = pill_y1 + (pill_h - total_lines_h) // 2
        curr_y = start_ty
        for i, l in enumerate(lines):
            b = line_boxes[i]
            lw = b[2] - b[0]
            lx = pill_x1 + (pill_w - lw) // 2
            draw.text((lx, curr_y - b[1]), l, font=f_t, fill=WHITE)
            curr_y += ht_line + line_gap

    else:
        # CASE 4: Neither Model nor Title -> Clean canvas without any pill!
        pass

    # 5. Official MEGATOOL Red Logo (Exact shop template)
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
    margin_top = 28

    if pos == "top-right":
        x_start = 32
    else:
        margin_right = 32
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
    badge_y = y_top - 22

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
                if 'กำลังมอเตอร์' in name or 'motor_power' in code:
                    specs['กำลังมอเตอร์'] = val_str
                elif 'กำลังไฟ' in name or 'power_phase' in code or 'voltage' in code or 'continuous_rating' in code:
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
            if k and v and len(k) < 40 and len(v) < 60:
                # Hose length first (avoids "สายอัดฉีดแรงดันสูง" matching pressure!)
                if ('สาย' in k or 'hose' in k.lower()) and 'ความยาวสายฉีด' not in specs:
                    m_v = re.search(r'(\d+(?:\.\d+)?)\s*(?:ม\.|เมตร|m\b)', v, re.IGNORECASE)
                    m_k = re.search(r'(\d+(?:\.\d+)?)\s*(?:ม\.|เมตร|m\b)', k, re.IGNORECASE)
                    if m_v:
                        specs['ความยาวสายฉีด'] = f"{m_v.group(1)} เมตร"
                    elif m_k:
                        specs['ความยาวสายฉีด'] = f"{m_k.group(1)} เมตร"
                    elif not any(q in v for q in ['ชิ้น', 'อัน', 'เส้น', 'ชุด', 'กล่อง']):
                        specs['ความยาวสายฉีด'] = v
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
        if 'ความยาวสายฉีด' not in specs and ('สายอัดฉีด' in line or 'สายฉีด' in line):
            m_line = re.search(r'ยาว(?:ถึง)?\s*(\d+(?:\.\d+)?)\s*(?:ม\.|เมตร|m\b)', line, re.IGNORECASE)
            if m_line:
                specs['ความยาวสายฉีด'] = f"{m_line.group(1)} เมตร"

    # Fallback: if 'กำลังมอเตอร์' is in specs but 'กำลังไฟฟ้า' missing and vice-versa
    if 'กำลังมอเตอร์' not in specs and 'กำลังไฟฟ้า' in specs and 'วัตต์' in specs['กำลังไฟฟ้า']:
        specs['กำลังมอเตอร์'] = specs['กำลังไฟฟ้า']
        del specs['กำลังไฟฟ้า']

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

    clean_parent_title = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]', '', str(parent_title)).strip()
    draw.text((60, 42), clean_parent_title[:45], font=font_title, fill=(255, 255, 255, 255))
    draw.text((60, 82), "ตารางเปรียบเทียบสเปกเพื่อให้คุณเลือกรุ่นที่ตอบโจทย์งานที่สุด", font=font_sub, fill=(203, 213, 225, 255))

    shop_str = f"{shop_name} STORE"
    sb = font_sub.getbbox(shop_str)
    sw = sb[2] - sb[0]
    draw.text((CANVAS_SIZE - 70 - sw, 60), shop_str, font=font_sub, fill=(249, 115, 22, 255))

    processed_items = []
    all_spec_keys = []
    preferred_order = [
        'แรงดันสูงสุด', 'กำลังมอเตอร์', 'ประเภทมอเตอร์', 'กำลังไฟฟ้า', 'อัตราการไหลของน้ำ',
        'ความยาวสายฉีด', 'ระบบตัดการทำงาน', 'ความเร็วรอบ', 'ขนาดใบตัด/เจียร์', 'น้ำหนักตัวเครื่อง'
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

        raw_name = item.get('name') or sku
        model_code, model_sub = extract_model_label(raw_name, sku)

        raw_price = item.get('price', 0)
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

    # Sort specs by preferred order
    ordered_keys = [k for k in preferred_order if k in all_spec_keys]
    for k in all_spec_keys:
        if k not in ordered_keys:
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
        nb = font_model.getbbox(m_code)
        nw = nb[2] - nb[0]
        draw.text((pill_x1 + (pill_w - nw) // 2, pill_y1 + 5), m_code, font=font_model, fill=(255, 255, 255, 255))

        # Line 2: Subtitle / Spec tag (e.g. แรงดัน 90 บาร์)
        if m['model_sub']:
            sb = font_model_sub.getbbox(m['model_sub'])
            sw = sb[2] - sb[0]
            draw.text((col_x + (model_col_w - sw) // 2, tbl_top + 192), m['model_sub'], font=font_model_sub, fill=(100, 116, 139, 255))

        # Price
        if m['price'] and m['price'] > 0:
            price_str = f"฿{m['price']:,.0f}"
        else:
            price_str = "-"
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
        w_text = m.get('warranty') or "ของแท้ 100% ประกันศูนย์"
        wb = font_val.getbbox(w_text)
        ww = wb[2] - wb[0]
        draw.text((col_x + (model_col_w - ww) // 2, last_ry1 + (row_h - 20) // 2), w_text, font=font_val, fill=(16, 185, 129, 255))

    for idx in range(num_models):
        col_x = tbl_left + label_col_w + (idx * model_col_w)
        draw.line([col_x, tbl_top + thumb_row_h, col_x, tbl_bottom], fill=(226, 232, 240, 255), width=2)

    footer_box = [30, 1130, CANVAS_SIZE - 30, 1175]
    draw.rounded_rectangle(footer_box, radius=12, fill=(241, 245, 249, 255))
    footer_text = f"{shop_name} STORE • สินค้าของแท้ 100% พร้อมจัดส่งด่วน • มีศูนย์บริการรองรับมาตรฐานสากล"
    ft_b = font_footer.getbbox(footer_text)
    ft_w = ft_b[2] - ft_b[0]
    draw.text(((CANVAS_SIZE - ft_w) // 2, 1142), footer_text, font=font_footer, fill=(71, 85, 105, 255))

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    canvas.convert('RGB').save(output_path, "JPEG", quality=92)
    return output_path
