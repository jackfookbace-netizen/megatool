import os
import json
import io
import time
from typing import Dict, Optional, Tuple, List

DATA_DIR = "app/data"
TITLES_FILE = os.path.join(DATA_DIR, "shopee_custom_titles.json")
LISTED_FILE = os.path.join(DATA_DIR, "listed_products.json")

os.makedirs(DATA_DIR, exist_ok=True)

def _load_titles() -> Dict[str, dict]:
    if os.path.exists(TITLES_FILE):
        try:
            with open(TITLES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print("Error loading shopee_custom_titles.json:", e)
    return {}

def _save_titles(data: Dict[str, dict]):
    tmp = TITLES_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if os.path.exists(TITLES_FILE):
            os.remove(TITLES_FILE)
        os.rename(tmp, TITLES_FILE)
    except Exception as e:
        print("Error saving shopee_custom_titles.json:", e)

def get_custom_shopee_title(sku: str) -> Optional[str]:
    if not sku:
        return None
    db = _load_titles()
    clean_sku = sku.strip()
    if clean_sku in db:
        return db[clean_sku].get("title")
    # Check case-insensitive
    for k, v in db.items():
        if k.lower() == clean_sku.lower():
            return v.get("title")
    return None

def get_all_custom_shopee_titles() -> Dict[str, dict]:
    return _load_titles()

def save_custom_shopee_title(sku: str, title: str, source: str = "manual") -> bool:
    if not sku or not title or not title.strip():
        return False
    clean_sku = sku.strip()
    clean_title = title.strip()
    db = _load_titles()
    db[clean_sku] = {
        "title": clean_title,
        "source": source,
        "updated_at": int(time.time())
    }
    _save_titles(db)

    # Also sync into listed_products.json if SKU is present
    try:
        if os.path.exists(LISTED_FILE):
            with open(LISTED_FILE, "r", encoding="utf-8") as f:
                listed = json.load(f)
            updated = False
            for shop_id in ["shop_1", "shop_2"]:
                shop_items = listed.get(shop_id, {})
                if clean_sku in shop_items:
                    shop_items[clean_sku]["name"] = clean_title
                    shop_items[clean_sku]["shopee_title"] = clean_title
                    updated = True
            if updated:
                tmp = LISTED_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(listed, f, ensure_ascii=False, indent=2)
                if os.path.exists(LISTED_FILE):
                    os.remove(LISTED_FILE)
                os.rename(tmp, LISTED_FILE)
    except Exception as e:
        print("Error syncing to listed_products.json:", e)

    return True

def import_shopee_titles_from_excel(file_bytes: bytes, filename: str = "") -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    sheet = wb.active

    header_row = None
    sku_col = None
    name_col = None

    for r in range(1, min(10, sheet.max_row + 1)):
        for c in range(1, min(35, sheet.max_column + 1)):
            v = str(sheet.cell(r, c).value or '').strip()
            v_low = v.lower()
            if any(k in v_low for k in ['ชื่อสินค้า', 'product name', 'item name']):
                name_col = c
            if any(k in v_low for k in ['parent sku', 'sku หลัก', 'เลขที่อ้างอิง sku', 'รหัสสินค้า', 'sku']):
                if not sku_col or 'parent' in v_low or 'หลัก' in v_low:
                    sku_col = c
        if sku_col and name_col:
            header_row = r
            break

    if not sku_col or not name_col:
        return {
            "success": False,
            "error": "ไม่พบคอลัมน์ 'SKU' หรือ 'ชื่อสินค้า' ในไฟล์ Excel ของ Shopee ครับ กรุณาตรวจสอบไฟล์อีกครั้ง"
        }

    imported_items = []
    for r in range(header_row + 1, sheet.max_row + 1):
        raw_sku = sheet.cell(r, sku_col).value
        raw_name = sheet.cell(r, name_col).value
        if not raw_sku or not raw_name:
            continue
        s_sku = str(raw_sku).strip()
        s_name = str(raw_name).strip()
        if s_sku and s_name and len(s_sku) >= 2 and len(s_name) >= 3:
            save_custom_shopee_title(s_sku, s_name, source="shopee_excel_import")
            imported_items.append({"sku": s_sku, "title": s_name})

    return {
        "success": True,
        "updated_count": len(imported_items),
        "items": imported_items[:50]
    }
