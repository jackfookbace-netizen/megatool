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
                    "store_name": item.get('stock', {}).get('storestock', {}).get('storeName', 'คลังหลัก')
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
    Extracts high-res distinct angle images and accessories from KTW product detail.
    Avoids duplicate resolutions and sorts naturally (-1.jpg, -2.jpg, ...).
    """
    if not detail:
        return []
        
    raw_images = []
    seen_endings = set()

    # 1. Primary image (high-res zoom)
    for im in detail.get('images', []):
        if im.get('format') in ['superZoom', 'zoom']:
            u = im.get('url', '').replace('/ktwcommercewebservices/v2', '')
            if u:
                m = re.search(r'-(\d+)\.(jpg|jpeg|png)', u, re.IGNORECASE)
                tag = m.group(1) if m else u.split('/')[-1]
                seen_endings.add(tag)
                raw_images.append(f"https://shop.ktw.co.th{u}")
            break

    # 2. DataSheets (different angles / accessories / features)
    sheet_imgs = []
    for ds in detail.get('dataSheets', []):
        u = ds.get('url', '').replace('/ktwcommercewebservices/v2', '')
        if u and u.lower().endswith(('.jpg', '.jpeg', '.png')) and 'vdo' not in u.lower():
            m = re.search(r'-(\d+)\.(jpg|jpeg|png)', u, re.IGNORECASE)
            tag = m.group(1) if m else u.split('/')[-1]
            if tag not in seen_endings:
                seen_endings.add(tag)
                sheet_imgs.append(f"https://shop.ktw.co.th{u}")

    def natural_sort_key(s):
        match = re.search(r'-(\d+)\.(jpg|jpeg|png)', s, re.IGNORECASE)
        return int(match.group(1)) if match else 999

    sheet_imgs = sorted(sheet_imgs, key=natural_sort_key)
    for img in sheet_imgs:
        raw_images.append(img)

    # Fallback to any images if none found
    if not raw_images:
        for im in detail.get('images', []):
            u = im.get('url', '').replace('/ktwcommercewebservices/v2', '')
            if u:
                full_u = f"https://shop.ktw.co.th{u}"
                if full_u not in raw_images:
                    raw_images.append(full_u)

    return raw_images

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
            return r.json()
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

