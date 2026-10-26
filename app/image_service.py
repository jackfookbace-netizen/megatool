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

def fetch_image_safe(url_or_path):
    if not url_or_path:
        raise ValueError("Empty image path or url")
    if url_or_path.startswith('/'):
        url_or_path = f"https://shop.ktw.co.th{url_or_path}"
    if url_or_path.startswith('http'):
        resp = requests.get(url_or_path, timeout=12)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert('RGBA')
    return Image.open(url_or_path).convert('RGBA')

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
    shop_name="MEGATOOL"
):
    """
    Combines 2 to 4 product images into a clean 1200x1200px collage card
    Layouts:
      - 2 images: 2 vertical split cards side by side
      - 3 images: 1 large left (main tool) + 2 stacked right (accessories/box)
      - 4 images: 2x2 grid
    """
    CANVAS_SIZE = 1200
    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (248, 250, 252, 255))
    draw = ImageDraw.Draw(canvas)

    BORDER_W = 16
    draw.rectangle([0, 0, CANVAS_SIZE - 1, CANVAS_SIZE - 1], outline=(239, 28, 37, 255), width=BORDER_W)

    inner_box = [BORDER_W, BORDER_W, CANVAS_SIZE - BORDER_W, CANVAS_SIZE - BORDER_W]
    draw.rectangle(inner_box, fill=(255, 255, 255, 255))

    font_title = load_font("leelawdb.ttf", 36)
    font_sub = load_font("leelawdb.ttf", 22)
    font_num = load_font("tahomabd.ttf", 24)
    font_tag = load_font("leelawdb.ttf", 20)

    # 1. Header Area
    header_box = [30, 30, CANVAS_SIZE - 30, 115]
    draw.rounded_rectangle(header_box, radius=18, fill=(15, 23, 42, 255))

    draw.text((60, 48), f"📦 {title[:40]}", font=font_title, fill=(255, 255, 255, 255))
    
    shop_str = f"{shop_name} OFFICIAL"
    shop_bbox = font_sub.getbbox(shop_str)
    sw = shop_bbox[2] - shop_bbox[0]
    draw.text((CANVAS_SIZE - 70 - sw, 58), shop_str, font=font_sub, fill=(249, 115, 22, 255))

    loaded_imgs = []
    for u in image_urls[:4]:
        try:
            raw_im = fetch_image_safe(u)
            trimmed = trim_white_space(raw_im)
            loaded_imgs.append(trimmed)
        except Exception as e:
            print("Error loading image for collage:", e)

    if not loaded_imgs:
        raise ValueError("No valid images could be loaded for collage")

    count = len(loaded_imgs)
    content_top = 135
    content_bottom = 1110
    content_left = 30
    content_right = CANVAS_SIZE - 30
    c_w = content_right - content_left
    c_h = content_bottom - content_top

    slots = []
    if count == 2:
        gap = 20
        w_each = (c_w - gap) // 2
        slots.append([content_left, content_top, content_left + w_each, content_bottom])
        slots.append([content_left + w_each + gap, content_top, content_right, content_bottom])
    elif count == 3:
        gap = 20
        left_w = int(c_w * 0.54)
        right_w = c_w - left_w - gap
        h_each = (c_h - gap) // 2
        slots.append([content_left, content_top, content_left + left_w, content_bottom])
        slots.append([content_left + left_w + gap, content_top, content_right, content_top + h_each])
        slots.append([content_left + left_w + gap, content_top + h_each + gap, content_right, content_bottom])
    else: # 4 images (2x2 grid)
        gap = 20
        w_each = (c_w - gap) // 2
        h_each = (c_h - gap) // 2
        slots.append([content_left, content_top, content_left + w_each, content_top + h_each])
        slots.append([content_left + w_each + gap, content_top, content_right, content_top + h_each])
        slots.append([content_left, content_top + h_each + gap, content_left + w_each, content_bottom])
        slots.append([content_left + w_each + gap, content_top + h_each + gap, content_right, content_bottom])

    for idx, (slot, img) in enumerate(zip(slots, loaded_imgs)):
        sx1, sy1, sx2, sy2 = slot
        draw.rounded_rectangle([sx1, sy1, sx2, sy2], radius=16, fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), width=2)
        
        pad = 25
        available_w = (sx2 - sx1) - (pad * 2)
        available_h = (sy2 - sy1) - (pad * 2) - 30

        im_w, im_h = img.size
        scale = min(available_w / im_w, available_h / im_h)
        new_w = max(10, int(im_w * scale))
        new_h = max(10, int(im_h * scale))
        resized_im = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        paste_x = sx1 + (sx2 - sx1 - new_w) // 2
        paste_y = sy1 + 15 + (available_h - new_h) // 2
        canvas.paste(resized_im, (paste_x, paste_y), resized_im)

        # Number Badge (Circle 1, 2, 3...)
        badge_r = 18
        bx = sx1 + 20
        by = sy1 + 20
        draw.ellipse([bx, by, bx + (badge_r * 2), by + (badge_r * 2)], fill=(239, 28, 37, 255))
        num_str = str(idx + 1)
        nb = font_num.getbbox(num_str)
        nw = nb[2] - nb[0]
        nh = nb[3] - nb[1]
        draw.text((bx + badge_r - nw // 2, by + badge_r - nh // 2 - 2), num_str, font=font_num, fill=(255, 255, 255, 255))

    # Footer Bar
    footer_box = [30, 1125, CANVAS_SIZE - 30, 1175]
    draw.rounded_rectangle(footer_box, radius=12, fill=(241, 245, 249, 255))
    footer_text = "🛡️ รับประกันสินค้าของแท้ 100% • เช็คอุปกรณ์ครบถ้วนก่อนจัดส่งทุกกล่อง • บริการหลังการขายมาตรฐานศูนย์"
    ft_b = font_tag.getbbox(footer_text)
    ft_w = ft_b[2] - ft_b[0]
    draw.text(((CANVAS_SIZE - ft_w) // 2, 1138), footer_text, font=font_tag, fill=(71, 85, 105, 255))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    canvas.convert('RGB').save(output_path, "JPEG", quality=92)
    return output_path


# ==============================================================================
# FEATURE 2: AUTO SPEC COMPARISON MATRIX CARD
# ==============================================================================

def extract_key_specs(detail):
    specs = {}
    if not detail:
        return specs
    classifs = detail.get('classifications', [])
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
                    specs['น้ำหนักเครื่อง'] = val_str
                elif 'ขนาดแกน' in name or 'spindle' in f.get('code', ''):
                    specs['ขนาดแกนเกลียว'] = val_str
                elif 'สายไฟ' in name or 'cord' in f.get('code', ''):
                    specs['ความยาวสายไฟ'] = val_str

    if 'น้ำหนักเครื่อง' not in specs:
        units = detail.get('conversionUnits', [])
        if units:
            net_w = units[0].get('netWeight', 0)
            if net_w:
                specs['น้ำหนักเครื่อง'] = f"{round(net_w / 1000.0, 2)} กก."
                
    return specs

def generate_comparison_card(
    items,
    output_path,
    parent_title="เปรียบเทียบสเปกและฟังก์ชันแต่ละรุ่น",
    shop_name="MEGATOOL"
):
    """
    items: list of dicts: [{'sku': '...', 'name': '...', 'price': 1550, 'image': '...', 'variation_name': '...'}]
    Generates a crisp 1200x1200px comparison matrix card
    """
    from app.ktw_service import get_product_detail

    CANVAS_SIZE = 1200
    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    BORDER_W = 16
    draw.rectangle([0, 0, CANVAS_SIZE - 1, CANVAS_SIZE - 1], outline=(239, 28, 37, 255), width=BORDER_W)

    font_title = load_font("leelawdb.ttf", 34)
    font_sub = load_font("leelawdb.ttf", 20)
    font_model = load_font("leelawdb.ttf", 22)
    font_price = load_font("tahomabd.ttf", 26)
    font_label = load_font("leelawdb.ttf", 20)
    font_val = load_font("leelawdb.ttf", 19)
    font_footer = load_font("leelawdb.ttf", 19)

    # 1. Header (y: 25 to 110)
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
    default_keys = ['กำลังไฟฟ้า', 'ความเร็วรอบ', 'ขนาดใบตัด/เจียร์', 'น้ำหนักเครื่อง', 'ขนาดแกนเกลียว', 'ความยาวสายไฟ']

    for item in items[:4]:
        sku = item.get('sku')
        detail = get_product_detail(sku)
        specs = extract_key_specs(detail)
        for k in specs.keys():
            if k not in all_spec_keys:
                all_spec_keys.append(k)
        
        img_url = item.get('image') or item.get('selected_image')
        if not img_url and detail:
            imgs = detail.get('images', [])
            if imgs:
                img_url = imgs[0].get('url')

        thumb_im = None
        if img_url:
            try:
                raw_im = fetch_image_safe(img_url)
                thumb_im = trim_white_space(raw_im)
            except Exception as e:
                print("Error fetching thumb:", e)

        processed_items.append({
            'sku': sku,
            'name': item.get('variation_name') or item.get('name') or sku,
            'price': item.get('price', 0),
            'specs': specs,
            'thumb': thumb_im
        })

    if not all_spec_keys:
        all_spec_keys = ['รหัสสินค้า (SKU)', 'ราคาจำหน่าย', 'ความเหมาะสมในการใช้งาน', 'มาตรฐานการรับประกัน']
    else:
        all_spec_keys = [k for k in default_keys if k in all_spec_keys] + [k for k in all_spec_keys if k not in default_keys]
        all_spec_keys = all_spec_keys[:6]

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

    draw.text((tbl_left + 25, tbl_top + 120), "เปรียบเทียบ", font=font_title, fill=(30, 41, 59, 255))
    draw.text((tbl_left + 25, tbl_top + 165), "สเปกแต่ละรุ่น", font=font_model, fill=(100, 116, 139, 255))

    for idx, m in enumerate(processed_items):
        col_x = tbl_left + label_col_w + (idx * model_col_w)
        draw.line([col_x, tbl_top, col_x, tbl_bottom], fill=(226, 232, 240, 255), width=2)

        if m['thumb']:
            tw, th = m['thumb'].size
            max_th = 150
            scale = min((model_col_w - 40) / tw, max_th / th)
            new_w = int(tw * scale)
            new_h = int(th * scale)
            r_im = m['thumb'].resize((new_w, new_h), Image.Resampling.LANCZOS)
            px = col_x + (model_col_w - new_w) // 2
            py = tbl_top + 15 + (max_th - new_h) // 2
            canvas.paste(r_im, (px, py), r_im)

        m_name = m['name']
        if len(m_name) > 22:
            m_name = m_name[:20] + "..."
        pill_w = min(model_col_w - 20, 260)
        pill_x1 = col_x + (model_col_w - pill_w) // 2
        pill_y1 = tbl_top + 185
        draw.rounded_rectangle([pill_x1, pill_y1, pill_x1 + pill_w, pill_y1 + 40], radius=10, fill=(234, 88, 12, 255))
        nb = font_model.getbbox(m_name)
        nw = nb[2] - nb[0]
        draw.text((pill_x1 + (pill_w - nw) // 2, pill_y1 + 7), m_name, font=font_model, fill=(255, 255, 255, 255))

        price_str = f"฿{m['price']:,.0f}" if m['price'] else "-"
        pb = font_price.getbbox(price_str)
        pw = pb[2] - pb[0]
        draw.text((col_x + (model_col_w - pw) // 2, tbl_top + 238), price_str, font=font_price, fill=(239, 28, 37, 255))

    rows_h = (tbl_bottom - (tbl_top + thumb_row_h))
    row_count = len(all_spec_keys) + 1
    row_h = rows_h // row_count

    for r_idx, key in enumerate(all_spec_keys):
        ry1 = tbl_top + thumb_row_h + (r_idx * row_h)
        ry2 = ry1 + row_h
        
        bg_color = (255, 255, 255, 255) if r_idx % 2 == 0 else (248, 250, 252, 255)
        draw.rectangle([tbl_left + 2, ry1, tbl_right - 2, ry2], fill=bg_color)
        draw.line([tbl_left, ry2, tbl_right, ry2], fill=(226, 232, 240, 255), width=1)

        draw.text((tbl_left + 25, ry1 + (row_h - 24) // 2), f"• {key}", font=font_label, fill=(51, 65, 85, 255))

        for idx, m in enumerate(processed_items):
            col_x = tbl_left + label_col_w + (idx * model_col_w)
            val = m['specs'].get(key, "-")
            if len(val) > 28:
                val = val[:26] + "..."
            vb = font_val.getbbox(val)
            vw = vb[2] - vb[0]
            draw.text((col_x + (model_col_w - vw) // 2, ry1 + (row_h - 22) // 2), val, font=font_val, fill=(15, 23, 42, 255))

    last_ry1 = tbl_top + thumb_row_h + (len(all_spec_keys) * row_h)
    draw.rectangle([tbl_left + 2, last_ry1, tbl_right - 2, tbl_bottom - 2], fill=(241, 245, 249, 255))
    draw.text((tbl_left + 25, last_ry1 + (row_h - 24) // 2), "• การรับประกันศูนย์", font=font_label, fill=(51, 65, 85, 255))
    for idx, m in enumerate(processed_items):
        col_x = tbl_left + label_col_w + (idx * model_col_w)
        w_text = "ของแท้ 100% ประกันศูนย์"
        wb = font_val.getbbox(w_text)
        ww = wb[2] - wb[0]
        draw.text((col_x + (model_col_w - ww) // 2, last_ry1 + (row_h - 22) // 2), w_text, font=font_val, fill=(16, 185, 129, 255))

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
