import requests
import json
import urllib.parse

AUTH_URL = "https://shop.ktw.co.th/authorizationserver/oauth/token"
API_BASE = "https://shop.ktw.co.th/rest/v2/ktw"

HEADERS_AUTH = {
    "User-Agent": "Dart",
    "Content-Type": "application/x-www-form-urlencoded"
}

AUTH_DATA = {
    "client_id": "asm",
    "client_secret": "secret",
    "grant_type": "password",
    "username": "11253",
    "password": "12341234"
}

_cached_token = None

def refresh_token():
    global _cached_token
    try:
        r = requests.post(AUTH_URL, data=AUTH_DATA, headers=HEADERS_AUTH, timeout=10)
        if r.status_code == 200:
            token_json = r.json()
            _cached_token = token_json.get("access_token", _cached_token)
            return _cached_token
    except Exception as e:
        print("KTW auth token refresh error:", e)
    return _cached_token

def get_token():
    global _cached_token
    if not _cached_token:
        refresh_token()
    return _cached_token

def get_headers():
    return {
        "User-Agent": "Dart",
        "Authorization": f"Bearer {get_token()}"
    }

IMMUNE_PATTERNS = [
    r'เครื่อง', r'สว่าน', r'ตู้', r'ปั๊ม', r'ชุด', r'คีม', r'ประแจ', r'ไขควง', r'กรรไกร',
    r'ระดับน้ำ', r'ตลับเมตร', r'ดอก', r'ใบเลื่อย', r'ใบตัด', r'ใบเจียร', r'ใบขัด', r'เทป',
    r'น้ำยา', r'สเปรย์', r'กาว', r'จาระบี', r'ถุงมือ', r'หน้ากาก', r'แว่นตา', r'พัดลม',
    r'บันได', r'รอก', r'แม่แรง', r'กาพ่นสี', r'สายยาง', r'สายลม'
]

SPARE_PREFIXES = (
    'MA', 'MF', 'MP', 'DP-', 'DA-', 'I122-', 'KT-M022-', 'K032-', 'K192-', 
    'K272-', 'P172-', 'P132-', 'P282-', 'P182-', 'P192-', 'P272-', 'P042-', 'P222-', 
    'P232-', 'P342-', 'P352-', 'P114-', 'P122-', 'V102-', 'V103P-', 'V104P-', 'V107P-', 'V108P-',
    'V110P-', 'P283-', 'S372-', 'P652-', 'H212-', 'H214-', 'J072-', 'M222-', 'C062-', 'E062-', 'K062-'
)

def is_spare_part(item):
    name = (item.get('name') or '').strip()
    sku = (item.get('code') or '').strip()

    # 1. Explicit spare keywords in Name or Category (100% spare parts)
    if any(k in name for k in ['อะไหล่', 'SPARE PART', 'SPAREPART', 'ทุ่นไฟฟ้า', 'ฟิลคอยล์', 'ฟิลด์คอยล์', 'แปรงถ่าน']):
        return True
    for cat in item.get('categories', []):
        cname = cat.get('name', '') if isinstance(cat, dict) else str(cat)
        if 'อะไหล่' in cname or 'SPARE' in cname.upper():
            return True

    # 2. Whitelist: Finished Tools & Commercial Accessories are IMMUNE (Never filtered out)
    for pat in IMMUNE_PATTERNS:
        if re.search(pat, name):
            return False

    # 3. Check spare SKU prefixes only for non-whitelisted items
    if sku.startswith(SPARE_PREFIXES):
        return True
    if len(sku) >= 4 and sku.startswith('P') and sku[3] == '2':
        return True

    return False

def search_products(query="*", brand=None, in_stock_only=False, exclude_spare_parts=True, page=0, page_size=20):
    headers = get_headers()
    
    clean_q = query.strip() if query and query.strip() != "*" else ""
    if brand:
        if clean_q:
            base_q = f"{brand} {clean_q}"
        else:
            base_q = f"{brand}"
    else:
        if clean_q:
            base_q = f"{clean_q}"
        else:
            base_q = ""

    if base_q:
        final_query = f"{base_q}:name-asc"
        if in_stock_only:
            final_query += ":inStockFlag_boolean:true"
    else:
        final_query = "*"

    multiplier = 1
    if exclude_spare_parts:
        multiplier += 2
    if in_stock_only:
        multiplier += 3

    fetch_size = min(page_size * multiplier, 100)
    url = f"{API_BASE}/products/search?query={urllib.parse.quote(final_query)}&pageSize={fetch_size}&currentPage={page}"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 401:
            refresh_token()
            headers = get_headers()
            r = requests.get(url, headers=headers, timeout=15)

        if r.status_code == 200:
            data = r.json()
            products = []
            for item in data.get('products', []):
                # 1. Spare parts filter
                if exclude_spare_parts and is_spare_part(item):
                    continue

                # 2. Strict In-stock filter
                stock_qty = item.get('stock', {}).get('stockLevel', 0) or 0
                stock_status = item.get('stock', {}).get('stockLevelStatus', '')
                if in_stock_only:
                    if stock_qty <= 0 or stock_status == 'outOfStock':
                        continue

                p_code = item.get('code')
                p_name = item.get('name', p_code)
                p_price = item.get('price', {}).get('value', 0)
                p_was_price = item.get('price', {}).get('wasPrice', p_price)
                
                # Image
                raw_img = ""
                images = item.get('images', [])
                all_imgs = []
                for im in images:
                    u = im.get('url', '').replace('/ktwcommercewebservices/v2', '')
                    if u:
                        full_u = f"https://shop.ktw.co.th{u}"
                        if full_u not in all_imgs:
                            all_imgs.append(full_u)
                if all_imgs:
                    raw_img = all_imgs[0]
                        
                products.append({
                    "sku": p_code,
                    "name": p_name,
                    "cost_price": p_price,
                    "was_price": p_was_price,
                    "image": raw_img,
                    "all_images": all_imgs,
                    "brand": clean_brand_name(item.get('manufacturer'), p_code),
                    "is_spare_part": is_spare_part(item),
                    "stock": item.get('stock', {}).get('stockLevel', 0),
                    "stock_status": item.get('stock', {}).get('stockLevelStatus', 'outOfStock'),
                    "store_name": item.get('stock', {}).get('storestock', {}).get('storeName', 'คลังหลัก'),
                    "ktw_url": f"https://shop.ktw.co.th/p/{p_code}"
                })
                if len(products) >= page_size:
                    break
                
            return {
                "total": data.get('pagination', {}).get('totalResults', 0),
                "page": page,
                "page_size": page_size,
                "products": products
            }
    except Exception as e:
        print("Search error:", e)
        
    return {"total": 0, "page": page, "page_size": page_size, "products": []}

def extract_product_images(detail):
    """
    Extracts all high-res distinct angle images and promo/spec sheets from KTW product detail.
    Deduplicates by filename, prioritizes superZoom > zoom > dataSheets > product,
    and sorts naturally (primary / -1.jpg first, numbered angles in order, then promo/spec sheets).
    """
    if not detail:
        return []
        
    candidates = {}

    # 1. From detail['images'] (GALLERY & PRIMARY images across formats)
    for im in detail.get('images', []):
        u = im.get('url', '').replace('/ktwcommercewebservices/v2', '')
        if not u or not u.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) or 'vdo' in u.lower():
            continue
        fmt = im.get('format', '').lower()
        score = 10
        if fmt == 'superzoom': score = 100
        elif fmt == 'zoom': score = 80
        elif fmt == 'product': score = 50
        elif fmt == 'thumbnail': score = 20

        is_primary = (im.get('imageType') == 'PRIMARY')
        fn = u.split('/')[-1].lower()

        if fn not in candidates or score > candidates[fn]['score']:
            candidates[fn] = {
                'score': score,
                'url': f"https://shop.ktw.co.th{u}",
                'is_primary': is_primary or candidates.get(fn, {}).get('is_primary', False),
                'fn': fn
            }

    # 2. From detail['dataSheets'] (high-res specification sheets and alternate angles)
    for ds in detail.get('dataSheets', []):
        u = ds.get('url', '').replace('/ktwcommercewebservices/v2', '')
        if not u or not u.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) or 'vdo' in u.lower():
            continue
        fn = u.split('/')[-1].lower()
        score = 70  # dataSheets are usually 1200x1200
        if fn not in candidates or score > candidates[fn]['score']:
            candidates[fn] = {
                'score': score,
                'url': f"https://shop.ktw.co.th{u}",
                'is_primary': candidates.get(fn, {}).get('is_primary', False),
                'fn': fn
            }

    # Fallback if no images collected
    if not candidates:
        fallback = []
        for im in detail.get('images', []):
            u = im.get('url', '').replace('/ktwcommercewebservices/v2', '')
            if u:
                full_u = f"https://shop.ktw.co.th{u}"
                if full_u not in fallback:
                    fallback.append(full_u)
        return fallback

    # Natural sorting:
    # Primary / Cover (-1.jpg or un-suffixed) first -> numbered angles (-2, -3, ...) -> promo/specs (-Nprice, -last, etc.)
    def sort_key(item):
        fn = item['fn']
        is_pri = item['is_primary']
        m = re.search(r'[-_](\d+)\.(jpg|jpeg|png|webp)$', fn, re.IGNORECASE)
        num = int(m.group(1)) if m else None

        # Primary image (usually #1 or marked PRIMARY)
        if is_pri and (num == 1 or num is None):
            return (0, 0, fn)
        # Numbered angle images
        if num is not None:
            return (1, num, fn)
        # Base SKU photo without suffixes (e.g. -MAKITA-M011-M6501B.jpg)
        if not any(k in fn for k in ['nprice', 'last', 'spec', 'dim', 'promo']):
            return (1, 0, fn)
        # Promo / Nprice / last sheets
        return (2, 999, fn)

    sorted_items = sorted(candidates.values(), key=sort_key)
    return [x['url'] for x in sorted_items]

def get_product_detail(sku):
    headers = get_headers()
    url = f"{API_BASE}/products/{sku}?fields=FULL"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 401:
            refresh_token()
            headers = get_headers()
            r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            data["ktw_url"] = f"https://shop.ktw.co.th/p/{sku}"
            return data
    except Exception as e:
        print(f"Error fetching detail {sku}:", e)
    return None

import re

def clean_brand_name(manufacturer_str, sku=""):
    """
    Extracts authentic brand name directly from KTW manufacturer field.
    e.g. 'POLO (WASHERS)/โปโล(เครื่องฉีดน้ำ)' -> 'POLO'
         '3M/3 เอ็ม' -> '3M'
         'MAKITA/มากีต้า' -> 'MAKITA'
    """
    if manufacturer_str:
        eng_part = manufacturer_str.split('/')[0].strip()
        clean = re.sub(r'\(.*?\)', '', eng_part).strip().upper()
        if clean:
            return clean

    # Heuristic fallback if manufacturer is not provided in response
    sku_u = (sku or "").upper()
    if sku_u.startswith('Z'):
        return '3M'
    elif sku_u.startswith('P'):
        return 'POLO'
    elif sku_u.startswith('M'):
        return 'MAKITA'
    elif sku_u.startswith('K'):
        return 'KARCHER'
    elif sku_u.startswith('I'):
        return 'INGCO'
    elif sku_u.startswith('D'):
        return 'DONGCHENG'
    elif sku_u.startswith('F'):
        return 'FORCE'
    elif sku_u.startswith('N'):
        return 'NACHI'
    elif sku_u.startswith('V'):
        return 'VALU'
    return 'GENUINE'

def detect_brand_from_sku(sku):
    return clean_brand_name(None, sku)

