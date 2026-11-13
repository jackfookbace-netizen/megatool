import os
import json
import io
import time
from typing import Dict, Optional, Tuple, List

DATA_DIR = "app/data"
TITLES_FILE = os.path.join(DATA_DIR, "shopee_custom_titles.json")
LISTED_FILE = os.path.join(DATA_DIR, "listed_products.json")
CART_FILE = os.path.join(DATA_DIR, "cart.json")
CUST_FILE = os.path.join(DATA_DIR, "cover_customizations.json")

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
        os.replace(tmp, TITLES_FILE)
    except Exception as e:
        print("Error saving shopee_custom_titles.json:", e)


def get_custom_shopee_title(sku: str, raw_ktw_name: str = "") -> Optional[str]:
    if not sku:
        return None
    db = _load_titles()
    clean_sku = sku.strip()
    raw_clean = (raw_ktw_name or "").strip()
    entry = db.get(clean_sku)
    if not isinstance(entry, dict):
        for k, v in db.items():
            if k.lower() == clean_sku.lower() and isinstance(v, dict):
                entry = v
                break
    if isinstance(entry, dict):
        t = str(entry.get("title") or "").strip()
        if t and t != clean_sku and (not raw_clean or t != raw_clean):
            return t
    return None


def get_all_custom_shopee_titles() -> Dict[str, dict]:
    return _load_titles()


def delete_custom_shopee_title(sku: str) -> Optional[str]:
    """Removes custom override for SKU and restores the system's recommended SEO title everywhere."""
    if not sku:
        return None
    clean_sku = sku.strip()
    db = _load_titles()
    keys_to_remove = [k for k in db.keys() if k.lower() == clean_sku.lower()]
    for k in keys_to_remove:
        del db[k]
    _save_titles(db)

    from app.seo_service import build_shopee_seo_title
    recommended_title = None

    # 1. Restore recommended SEO title in listed_products.json
    try:
        if os.path.exists(LISTED_FILE):
            with open(LISTED_FILE, "r", encoding="utf-8") as f:
                listed = json.load(f)
            updated = False
            for shop_id in ["shop_1", "shop_2"]:
                shop_items = listed.get(shop_id, {})
                if clean_sku in shop_items:
                    it = shop_items[clean_sku]
                    raw_n = it.get("ktw_name") or it.get("name") or clean_sku
                    brand = it.get("brand") or ""
                    rec_t = build_shopee_seo_title(brand, raw_n, clean_sku, is_variation_group=False)
                    recommended_title = rec_t
                    it["shopee_title"] = rec_t
                    it["has_custom_seo_title"] = False
                    updated = True
            if updated:
                tmp = LISTED_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(listed, f, ensure_ascii=False, indent=2)
                os.replace(tmp, LISTED_FILE)
    except Exception as e:
        print("Error restoring recommended title in listed_products.json:", e)

    # 2. Restore recommended SEO title in cart.json
    try:
        if os.path.exists(CART_FILE):
            with open(CART_FILE, "r", encoding="utf-8") as f:
                cart_data = json.load(f)
            c_updated = False
            for shop_id in ["shop_1", "shop_2"]:
                for it in cart_data.get(shop_id, []):
                    if isinstance(it, dict) and (it.get("sku") or "").strip().lower() == clean_sku.lower():
                        raw_n = it.get("ktw_name") or it.get("name") or clean_sku
                        brand = it.get("brand") or ""
                        rec_t = recommended_title or build_shopee_seo_title(brand, raw_n, clean_sku, is_variation_group=False)
                        recommended_title = rec_t
                        it["shopee_title"] = rec_t
                        it["has_custom_seo_title"] = False
                        c_updated = True
            if c_updated:
                tmp = CART_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(cart_data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, CART_FILE)
    except Exception as e:
        print("Error restoring recommended title in cart.json:", e)

    # 3. Clear custom shopee_title in cover_customizations.json
    try:
        if os.path.exists(CUST_FILE):
            with open(CUST_FILE, "r", encoding="utf-8") as f:
                cust_data = json.load(f)
            if clean_sku in cust_data and isinstance(cust_data[clean_sku], dict):
                cust_data[clean_sku].pop("shopee_title", None)
                tmp = CUST_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(cust_data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, CUST_FILE)
    except Exception as e:
        print("Error clearing custom title in cover_customizations.json:", e)

    return recommended_title


def save_custom_shopee_title(sku: str, title: str, source: str = "manual") -> bool:
    if not sku or not title or not title.strip():
        return False
    clean_sku = sku.strip()
    clean_title = title.strip()

    # Check if clean_title is merely the raw KTW catalog name or identical to system recommended title
    raw_ktw_name = ""
    brand_val = ""
    try:
        if os.path.exists(LISTED_FILE):
            with open(LISTED_FILE, "r", encoding="utf-8") as f:
                listed_check = json.load(f)
            for s_id in ["shop_1", "shop_2"]:
                if clean_sku in listed_check.get(s_id, {}):
                    it_c = listed_check[s_id][clean_sku]
                    raw_ktw_name = (it_c.get("ktw_name") or it_c.get("name") or "").strip()
                    brand_val = (it_c.get("brand") or "").strip()
                    break
    except Exception:
        pass

    # Never overwrite custom SEO title with the raw KTW catalog short name
    if raw_ktw_name and clean_title == raw_ktw_name and not clean_title.startswith("["):
        return False

    from app.seo_service import build_shopee_seo_title
    rec_title = build_shopee_seo_title(brand_val, raw_ktw_name or clean_title, clean_sku, is_variation_group=False) if raw_ktw_name else ""

    db = _load_titles()
    if rec_title and clean_title == rec_title and source != "manual_lock":
        # User set/kept the exact system recommended SEO title -> remove custom override if any
        if clean_sku in db:
            del db[clean_sku]
            _save_titles(db)
    else:
        db[clean_sku] = {
            "title": clean_title,
            "source": source,
            "updated_at": int(time.time())
        }
        _save_titles(db)

    # 1. Sync into listed_products.json if SKU is present
    try:
        if os.path.exists(LISTED_FILE):
            with open(LISTED_FILE, "r", encoding="utf-8") as f:
                listed = json.load(f)
            updated = False
            for shop_id in ["shop_1", "shop_2"]:
                shop_items = listed.get(shop_id, {})
                if clean_sku in shop_items:
                    old_n = (shop_items[clean_sku].get("ktw_name") or shop_items[clean_sku].get("name") or "").strip()
                    if old_n and not old_n.startswith("[") and not shop_items[clean_sku].get("ktw_name"):
                        shop_items[clean_sku]["ktw_name"] = old_n
                    shop_items[clean_sku]["shopee_title"] = clean_title
                    updated = True
            if updated:
                tmp = LISTED_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(listed, f, ensure_ascii=False, indent=2)
                os.replace(tmp, LISTED_FILE)
    except Exception as e:
        print("Error syncing title to listed_products.json:", e)

    # 2. Sync into cart.json if SKU is present
    try:
        if os.path.exists(CART_FILE):
            with open(CART_FILE, "r", encoding="utf-8") as f:
                cart_data = json.load(f)
            c_updated = False
            for shop_id in ["shop_1", "shop_2"]:
                for it in cart_data.get(shop_id, []):
                    if isinstance(it, dict) and (it.get("sku") or "").strip().lower() == clean_sku.lower():
                        if it.get("shopee_title") != clean_title:
                            it["shopee_title"] = clean_title
                            c_updated = True
            if c_updated:
                tmp = CART_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(cart_data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, CART_FILE)
    except Exception as e:
        print("Error syncing title to cart.json:", e)

    # 3. Sync into cover_customizations.json if SKU is present
    try:
        cust_data = {}
        if os.path.exists(CUST_FILE):
            with open(CUST_FILE, "r", encoding="utf-8") as f:
                cust_data = json.load(f)
        if clean_sku not in cust_data or not isinstance(cust_data.get(clean_sku), dict):
            cust_data[clean_sku] = {}
        if cust_data[clean_sku].get("shopee_title") != clean_title:
            cust_data[clean_sku]["shopee_title"] = clean_title
            cust_data[clean_sku]["updated_at"] = int(time.time())
            tmp = CUST_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cust_data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, CUST_FILE)
    except Exception as e:
        print("Error syncing title to cover_customizations.json:", e)

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
