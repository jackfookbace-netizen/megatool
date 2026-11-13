import os
import json
import time
from typing import Dict, List, Optional
from datetime import datetime
from app.shop_service import get_shop, calculate_shop_price, generate_shop_title

DATA_DIR = "app/data"
DATA_FILE = os.path.join(DATA_DIR, "listed_products.json")

os.makedirs(DATA_DIR, exist_ok=True)

def _init_storage():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"shop_1": {}, "shop_2": {}}, f, ensure_ascii=False, indent=2)

_init_storage()

_LAST_STOCK_REFRESH = 0
_STOCK_REFRESH_INTERVAL = 30  # refresh live warehouse stock every 30s

def _read_all_raw() -> Dict[str, Dict[str, dict]]:
    """
    Reads the persistent JSON and ensures it is structured as:
    {
      "shop_1": { "SKU": {...} },
      "shop_2": { "SKU": {...} }
    }
    Automatically migrates legacy single-shop format.
    """
    try:
        if not os.path.exists(DATA_FILE):
            return {"shop_1": {}, "shop_2": {}}
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        # Detect legacy format (root keys are SKUs instead of shop IDs)
        if data and isinstance(data, dict):
            first_key = next(iter(data.keys()))
            if not first_key.startswith("shop_"):
                # Migrate legacy single shop to shop_1
                migrated = {"shop_1": data, "shop_2": {}}
                _write_all_raw(migrated)
                return migrated
            # Ensure at least shop_1 and shop_2 exist
            if "shop_1" not in data:
                data["shop_1"] = {}
            if "shop_2" not in data:
                data["shop_2"] = {}
            return data
    except Exception as e:
        print("Error reading raw listed_products.json:", e)
    return {"shop_1": {}, "shop_2": {}}

def _write_all_raw(data: Dict[str, Dict[str, dict]]):
    tmp_file = DATA_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, DATA_FILE)

import threading

_SYNC_IN_PROGRESS = False
_SYNC_LOCK = threading.Lock()

def _enrich_listed_item(item: dict) -> dict:
    """Computes live net profit, margin percentage, stock alerts, and margin alerts."""
    price = float(item.get("price") or 0.0)
    cost = float(item.get("cost_price") or 0.0)
    stock = int(item.get("stock") or 0)
    net_after_fee = round(price * 0.72, 2)  # Shopee ~28% fee
    net_profit = round(net_after_fee - cost, 2) if cost > 0 else 0.0
    margin_pct = round((net_profit / cost) * 100.0, 1) if cost > 0 else 0.0

    item["net_profit"] = net_profit
    item["margin_pct"] = margin_pct
    if stock <= 0:
        item["stock_alert"] = "out_of_stock"
    elif stock <= 5:
        item["stock_alert"] = "low_stock"
    else:
        item["stock_alert"] = "ok"

    if cost > 0 and net_profit <= 0:
        item["margin_alert"] = "loss"
    elif cost > 0 and (net_profit < 30.0 and margin_pct < 7.0):
        item["margin_alert"] = "low"
    else:
        item["margin_alert"] = "ok"
    return item

def _sync_live_ktw_stock_and_cost(force_refresh: bool = False):
    global _LAST_STOCK_REFRESH, _SYNC_IN_PROGRESS
    with _SYNC_LOCK:
        if _SYNC_IN_PROGRESS:
            return
        _SYNC_IN_PROGRESS = True
        _LAST_STOCK_REFRESH = time.time()

    try:
        from app.ktw_service import get_product_detail, clean_brand_name, extract_product_images
        from concurrent.futures import ThreadPoolExecutor

        raw_data = _read_all_raw()
        all_skus = set()
        for s_id, s_items in raw_data.items():
            all_skus.update(s_items.keys())
        if not all_skus:
            return

        def _fetch_live(sku):
            try:
                return sku, get_product_detail(sku, force_refresh=force_refresh)
            except Exception:
                return sku, None

        with ThreadPoolExecutor(max_workers=min(max(len(all_skus), 1), 8)) as executor:
            results = list(executor.map(_fetch_live, list(all_skus)))

        live_results = {s: d for s, d in results if d}
        if not live_results:
            return

        # Re-read latest raw_data before writing to avoid overwriting concurrent edits
        raw_data = _read_all_raw()
        needs_save = False
        for s_id, s_items in raw_data.items():
            for sku, item in s_items.items():
                detail = live_results.get(sku)
                if not detail:
                    continue
                if not item.get("image_url") or item.get("brand") == "OTHER" or item.get("name") == sku:
                    item["name"] = detail.get("name") or item.get("name") or sku
                    item["brand"] = clean_brand_name(detail.get("manufacturer"), sku)
                    imgs = extract_product_images(detail)
                    item["image_url"] = imgs[0] if imgs else item.get("image_url", "")
                    needs_save = True
                live_stock = detail.get("stock", {}).get("stockLevel")
                if live_stock is not None and item.get("stock") != live_stock:
                    item["stock"] = live_stock
                    needs_save = True
                live_cost = detail.get("price", {}).get("value")
                if live_cost and float(live_cost) > 0:
                    current_cost = float(item.get("cost_price", 0.0) or 0.0)
                    if float(live_cost) > current_cost or current_cost <= 0:
                        item["cost_price"] = 100.0 if sku == "Z053-0073" else float(live_cost)
                        needs_save = True

        if needs_save:
            _write_all_raw(raw_data)
    except Exception as e:
        print("Background KTW stock/cost sync error:", e)
    finally:
        with _SYNC_LOCK:
            _SYNC_IN_PROGRESS = False

def get_all_listed(shop_id: str = "shop_1", refresh_stock: bool = True, force_sync_blocking: bool = False) -> Dict[str, dict]:
    global _LAST_STOCK_REFRESH
    try:
        now = time.time()
        if force_sync_blocking:
            _sync_live_ktw_stock_and_cost(force_refresh=True)
        elif refresh_stock and (now - _LAST_STOCK_REFRESH > _STOCK_REFRESH_INTERVAL):
            threading.Thread(target=_sync_live_ktw_stock_and_cost, args=(False,), daemon=True).start()

        raw_data = _read_all_raw()
        items = raw_data.get(shop_id, {})
        from app.title_service import get_all_custom_shopee_titles
        from app.seo_service import build_shopee_seo_title
        custom_titles_db = get_all_custom_shopee_titles()
        for sku, item in items.items():
            if not item.get("ktw_url"):
                item["ktw_url"] = f"https://shop.ktw.co.th/p/{sku}"
            raw_ktw = (item.get("ktw_name") or item.get("name") or sku).strip()
            item["ktw_name"] = raw_ktw
            rec_seo = build_shopee_seo_title(
                item.get("brand") or "",
                raw_ktw,
                sku,
                is_variation_group=False
            )
            item["recommended_seo_title"] = rec_seo
            saved_t = (custom_titles_db.get(sku) or {}).get("title")
            if saved_t and saved_t.strip() != raw_ktw and saved_t.strip() != rec_seo:
                item["shopee_title"] = saved_t.strip()
                item["has_custom_seo_title"] = True
            else:
                item["shopee_title"] = rec_seo
                item["has_custom_seo_title"] = False
            _enrich_listed_item(item)
        return items
    except Exception as e:
        print(f"Error reading listed products for {shop_id}:", e)
        return {}

def get_listed_product(sku: str, shop_id: str = "shop_1") -> Optional[dict]:
    all_items = get_all_listed(shop_id=shop_id)
    return all_items.get(sku)

def update_listed_product_price(sku: str, price: float, shop_id: str = "shop_1") -> Optional[dict]:
    raw_data = _read_all_raw()
    items = raw_data.get(shop_id, {})
    clean_sku = sku.strip()
    if clean_sku in items:
        items[clean_sku]["price"] = round(float(price), 2)
        items[clean_sku]["updated_at"] = datetime.now().isoformat()
        _write_all_raw(raw_data)
        return items[clean_sku]
    return None

AUTHENTIC_MASTER_COSTS = {
    "Z053-0073": 100.0,
    "M011-M9513B": 1086.4,
    "P271-PL411C": 1490.0,
    "M316-0020": 85.0,
    "P231-0070AE": 2500.0,
    "M011-M5801B": 2240.7,
    "I081-T0102EL4": 305.0,
    "KT-J019-ARC200D+": 5650.0,
    "M316-0030": 150.0,
    "N241-NOVO200": 2490.0,
    "M011-M8701B": 2725.7,
    "P041-2300": 850.0,
    "M011-M0910B": 843.9,
    "M011-M0900B": 843.9,
    "P171-WARRIOR90": 1350.0,
    "P171-WARRIOR101N": 1775.0,
    "P171-RANGER120": 2150.0,
    "P171-COMMANDO135N": 2925.0
}

def save_listed_product(
    sku: str, 
    shopee_url: str, 
    name: str = "", 
    brand: str = "", 
    price: float = 0.0, 
    image_url: str = "", 
    variation_name: str = "",
    cost_price: Optional[float] = None,
    shop_id: str = "shop_1"
) -> dict:
    from app.ktw_service import get_product_detail, clean_brand_name, extract_product_images
    
    clean_sku = sku.strip()
    clean_url = shopee_url.strip()
    if clean_url and not clean_url.startswith("http://") and not clean_url.startswith("https://"):
        clean_url = "https://" + clean_url
        
    raw_data = _read_all_raw()
    if shop_id not in raw_data:
        raw_data[shop_id] = {}
    items = raw_data[shop_id]
    existing = items.get(clean_sku, {})

    detail = None
    try:
        detail = get_product_detail(clean_sku)
    except Exception as e:
        print(f"Error fetching KTW detail for {clean_sku}:", e)
        
    if detail:
        real_name = detail.get("name") or clean_sku
        real_brand = clean_brand_name(detail.get("manufacturer"), clean_sku)
        imgs = extract_product_images(detail)
        real_img = imgs[0] if imgs else ""
        ktw_price = detail.get("price", {}).get("value", 0.0) or 0.0
        stock_val = detail.get("stock", {}).get("stockLevel", 0) or 0
        
        raw_ktw_name = real_name
        brand = brand or existing.get("brand") or real_brand
        image_url = image_url or existing.get("image_url") or real_img
    else:
        raw_ktw_name = existing.get("ktw_name") or existing.get("name") or clean_sku
        ktw_price = 0.0
        stock_val = existing.get("stock", 0)

    # Determine accurate wholesale dealer cost (never overwrite with 0)
    if cost_price is not None and float(cost_price) > 0:
        cost_val = float(cost_price)
    elif existing.get("cost_price") and float(existing.get("cost_price", 0)) > 0:
        cost_val = float(existing.get("cost_price"))
    elif clean_sku in AUTHENTIC_MASTER_COSTS:
        cost_val = AUTHENTIC_MASTER_COSTS[clean_sku]
    elif clean_sku == "Z053-0073":
        cost_val = 100.0
    elif ktw_price > 0:
        cost_val = ktw_price
    else:
        cost_val = 0.0

    # Selling price logic: respect explicit price or existing price, never force auto recalculation
    final_price = float(price or 0.0)
    if final_price <= 0:
        final_price = float(existing.get("price", 0.0))
    if final_price <= 0:
        final_price = calculate_shop_price(cost_val, shop_id)
        
    now_str = datetime.now().isoformat()
    from app.seo_service import build_shopee_seo_title
    rec_seo_title = build_shopee_seo_title(brand or "OTHER", raw_ktw_name, clean_sku, is_variation_group=False)
    submitted_title = (name or "").strip()

    # If user submitted a customized SEO title (different from raw KTW name and different from recommended default)
    is_custom_seo = bool(
        submitted_title and
        submitted_title != clean_sku and
        submitted_title != raw_ktw_name.strip() and
        submitted_title != rec_seo_title
    )
    active_shopee_title = submitted_title if is_custom_seo else rec_seo_title
    
    item_data = {
        "sku": clean_sku,
        "shopee_url": clean_url or existing.get("shopee_url", ""),
        "variation_name": (variation_name or existing.get("variation_name", "")).strip(),
        "name": raw_ktw_name or clean_sku,
        "ktw_name": raw_ktw_name or clean_sku,
        "shopee_title": active_shopee_title,
        "recommended_seo_title": rec_seo_title,
        "has_custom_seo_title": is_custom_seo,
        "brand": brand or "OTHER",
        "price": final_price,
        "image_url": image_url,
        "cost_price": cost_val,
        "stock": stock_val,
        "ktw_url": f"https://shop.ktw.co.th/p/{clean_sku}",
        "shop_id": shop_id,
        "created_at": existing.get("created_at", now_str),
        "updated_at": now_str
    }
    
    items[clean_sku] = item_data
    _write_all_raw(raw_data)

    # Permanently remember custom title in shopee_custom_titles.json ONLY if user customized it
    if is_custom_seo:
        try:
            from app.title_service import save_custom_shopee_title
            save_custom_shopee_title(clean_sku, submitted_title, source="listed_save")
        except Exception as e_t:
            print("Error saving custom title from listed_service:", e_t)
    elif submitted_title == rec_seo_title:
        try:
            from app.title_service import delete_custom_shopee_title
            delete_custom_shopee_title(clean_sku)
        except Exception:
            pass
    
    return item_data

def delete_listed_product(sku: str, shop_id: str = "shop_1") -> bool:
    raw_data = _read_all_raw()
    items = raw_data.get(shop_id, {})
    if sku in items:
        del items[sku]
        _write_all_raw(raw_data)
        return True
    return False

def clone_product_to_shop(
    sku: str, 
    from_shop_id: str = "shop_1", 
    to_shop_id: str = "shop_2",
    price_mode: str = "auto",
    custom_price: Optional[float] = None,
    custom_name: Optional[str] = None,
    custom_image: Optional[str] = None
) -> dict:
    """
    Clones a product from one shop to another with safety checks:
    - Auto recalculates price based on destination shop formula (or custom price)
    - Auto tunes title with distinct SEO keyword structure to avoid Shopee duplicate penalties
    - Picks alternative angle / collage image if available
    """
    clean_sku = sku.strip()
    source_items = get_all_listed(shop_id=from_shop_id, refresh_stock=False)
    src = source_items.get(clean_sku)
    
    from app.ktw_service import get_product_detail, clean_brand_name, extract_product_images
    detail = None
    try:
        detail = get_product_detail(clean_sku)
    except Exception as e:
        print("KTW detail lookup for clone:", e)

    brand = src.get("brand") if src else (clean_brand_name(detail.get("manufacturer"), clean_sku) if detail else "OTHER")
    raw_name = src.get("name") if src else (detail.get("name") if detail else clean_sku)
    cost = src.get("cost_price", 0.0) if src else (detail.get("price", {}).get("value", 0.0) if detail else 0.0)
    stock = src.get("stock", 0) if src else (detail.get("stock", {}).get("stockLevel", 0) if detail else 0)

    # 1. Determine Price for Destination Shop
    if custom_price and float(custom_price) > 0:
        target_price = float(custom_price)
    elif price_mode == "match_source" and src and src.get("price"):
        target_price = float(src["price"])
    else:
        # Calculate using to_shop_id formula (e.g. Shop 2 with 8% profit margin)
        target_price = calculate_shop_price(cost, to_shop_id)

    # 2. Smart Title Generation (Prevents Shopee Duplicate Listing Penalty)
    if custom_name and custom_name.strip():
        final_name = custom_name.strip()
    else:
        final_name = generate_shop_title(clean_sku, raw_name, brand, to_shop_id)

    # 3. Select Alternate Cover Image
    final_img = custom_image
    if not final_img:
        # Check custom collages or comparison cards in product_collages.json
        try:
            collages_file = os.path.join(DATA_DIR, "product_collages.json")
            if os.path.exists(collages_file):
                with open(collages_file, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    c_list = cdata.get(clean_sku, [])
                    if c_list and len(c_list) > 0:
                        final_img = c_list[0].get("cdn_url") or c_list[0].get("url")
        except Exception as e:
            print("Error loading custom collages:", e)

    if not final_img and detail:
        imgs = extract_product_images(detail)
        if len(imgs) > 1:
            # Pick 2nd image angle so cover image is different from Shop 1!
            final_img = imgs[1]
        elif len(imgs) > 0:
            final_img = imgs[0]
            
    if not final_img and src:
        final_img = src.get("image_url", "")

    # Save to destination shop
    return save_listed_product(
        sku=clean_sku,
        shopee_url="", # New shop doesn't have live URL yet
        name=final_name,
        brand=brand,
        price=target_price,
        image_url=final_img,
        variation_name=src.get("variation_name", "") if src else "",
        shop_id=to_shop_id
    )

def get_dashboard_summary(shop_id: str = "shop_1") -> dict:
    raw_data = _read_all_raw()
    items = raw_data.get(shop_id, {})
    total_listed = len(items)
    
    brand_counts = {}
    total_value = 0.0
    
    for item in items.values():
        b = (item.get("brand") or "OTHER").upper()
        brand_counts[b] = brand_counts.get(b, 0) + 1
        total_value += float(item.get("price") or 0.0)
        
    recent_items = sorted(list(items.values()), key=lambda x: x.get("updated_at", ""), reverse=True)[:10]
    
    # Store summaries for all shops
    shops_summary = {}
    for s_id, s_items in raw_data.items():
        s_val = sum(float(it.get("price") or 0.0) for it in s_items.values())
        shops_summary[s_id] = {
            "count": len(s_items),
            "estimated_value": round(s_val, 2)
        }
        
    return {
        "active_shop_id": shop_id,
        "total_listed": total_listed,
        "total_catalog": 96437,
        "in_stock_catalog": 52792,
        "estimated_store_value": round(total_value, 2),
        "brand_counts": brand_counts,
        "recent_listed": recent_items,
        "shops_summary": shops_summary
    }
