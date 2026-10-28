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

def get_all_listed(shop_id: str = "shop_1", refresh_stock: bool = True) -> Dict[str, dict]:
    global _LAST_STOCK_REFRESH
    try:
        raw_data = _read_all_raw()
        items = raw_data.get(shop_id, {})
        
        now = time.time()
        needs_save = False
        from app.ktw_service import get_product_detail, clean_brand_name, extract_product_images
        
        # 1. Self-healing for incomplete records
        for sku, item in items.items():
            if not item.get("image_url") or item.get("brand") == "OTHER" or item.get("name") == sku or not item.get("price"):
                detail = get_product_detail(sku)
                if detail:
                    item["name"] = detail.get("name") or item.get("name") or sku
                    item["brand"] = clean_brand_name(detail.get("manufacturer"), sku)
                    imgs = extract_product_images(detail)
                    item["image_url"] = imgs[0] if imgs else item.get("image_url", "")
                    cost_val = detail.get("price", {}).get("value", 0.0) or 0.0
                    item["cost_price"] = 100.0 if sku == "Z053-0073" else cost_val
                    item["stock"] = detail.get("stock", {}).get("stockLevel", 0) or 0
                    if not item.get("price") or item["price"] <= 0:
                        item["price"] = calculate_shop_price(cost_val, shop_id)
                    item["ktw_url"] = f"https://shop.ktw.co.th/p/{sku}"
                    needs_save = True

        # 2. Real-time Live Warehouse Stock & Cost Sync with KTW
        if refresh_stock and (now - _LAST_STOCK_REFRESH > _STOCK_REFRESH_INTERVAL) and len(items) > 0:
            _LAST_STOCK_REFRESH = now
            from concurrent.futures import ThreadPoolExecutor

            def _fetch_live(sku):
                try:
                    return sku, get_product_detail(sku)
                except Exception:
                    return sku, None

            # Collect all distinct SKUs across ALL shops for efficient batch lookup
            all_skus = set()
            for s_id, s_items in raw_data.items():
                all_skus.update(s_items.keys())

            with ThreadPoolExecutor(max_workers=min(max(len(all_skus), 1), 6)) as executor:
                results = list(executor.map(_fetch_live, list(all_skus)))

            live_results = {s: d for s, d in results if d}
            
            for s_id, s_items in raw_data.items():
                for sku, item in s_items.items():
                    detail = live_results.get(sku)
                    if detail:
                        live_stock = detail.get("stock", {}).get("stockLevel")
                        if live_stock is not None and item.get("stock") != live_stock:
                            item["stock"] = live_stock
                            needs_save = True
                        if sku != "Z053-0073":
                            live_cost = detail.get("price", {}).get("value")
                            if live_cost and item.get("cost_price") != live_cost:
                                item["cost_price"] = live_cost
                                needs_save = True

        if needs_save:
            _write_all_raw(raw_data)
            
        return raw_data.get(shop_id, {})
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

def save_listed_product(
    sku: str, 
    shopee_url: str, 
    name: str = "", 
    brand: str = "", 
    price: float = 0.0, 
    image_url: str = "", 
    variation_name: str = "",
    shop_id: str = "shop_1"
) -> dict:
    from app.ktw_service import get_product_detail, clean_brand_name, extract_product_images
    
    clean_sku = sku.strip()
    clean_url = shopee_url.strip()
    if clean_url and not clean_url.startswith("http://") and not clean_url.startswith("https://"):
        clean_url = "https://" + clean_url
        
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
        cost_val = 100.0 if clean_sku == "Z053-0073" else (detail.get("price", {}).get("value", 0.0) or 0.0)
        stock_val = detail.get("stock", {}).get("stockLevel", 0) or 0
        
        name = name or real_name
        brand = brand or real_brand
        image_url = image_url or real_img
        if not price or price <= 0:
            price = calculate_shop_price(cost_val, shop_id)
    else:
        cost_val = 100.0 if clean_sku == "Z053-0073" else 0.0
        stock_val = 0
        
    raw_data = _read_all_raw()
    if shop_id not in raw_data:
        raw_data[shop_id] = {}
        
    items = raw_data[shop_id]
    now_str = datetime.now().isoformat()
    
    item_data = {
        "sku": clean_sku,
        "shopee_url": clean_url,
        "variation_name": (variation_name or "").strip(),
        "name": name or clean_sku,
        "brand": brand or "OTHER",
        "price": price,
        "image_url": image_url,
        "cost_price": cost_val,
        "stock": stock_val,
        "ktw_url": f"https://shop.ktw.co.th/p/{clean_sku}",
        "shop_id": shop_id,
        "created_at": items.get(clean_sku, {}).get("created_at", now_str),
        "updated_at": now_str
    }
    
    items[clean_sku] = item_data
    _write_all_raw(raw_data)
    
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
