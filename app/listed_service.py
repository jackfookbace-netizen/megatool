import os
import json
import time
from typing import Dict, List, Optional
from datetime import datetime

DATA_DIR = "app/data"
DATA_FILE = os.path.join(DATA_DIR, "listed_products.json")

os.makedirs(DATA_DIR, exist_ok=True)

def _init_storage():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)

_init_storage()

def get_all_listed() -> Dict[str, dict]:
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("Error reading listed products:", e)
        return {}

def get_listed_product(sku: str) -> Optional[dict]:
    all_items = get_all_listed()
    return all_items.get(sku)

def save_listed_product(sku: str, shopee_url: str, name: str = "", brand: str = "", price: float = 0.0, image_url: str = "") -> dict:
    from app.ktw_service import get_product_detail, clean_brand_name, extract_product_images
    
    clean_sku = sku.strip()
    clean_url = shopee_url.strip()
    if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
        clean_url = "https://" + clean_url
        
    # Auto-enrich from KTW Catalog to ensure 100% real warehouse product info
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
        cost_val = detail.get("price", {}).get("value", 0.0) or 0.0
        stock_val = detail.get("stock", {}).get("stockLevel", 0) or 0
        
        name = real_name
        brand = real_brand
        image_url = real_img or image_url
        if not price or price <= 0:
            price = round(cost_val * 1.25) if cost_val > 0 else 0.0
    else:
        cost_val = 0.0
        stock_val = 0
        
    all_items = get_all_listed()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    item_data = {
        "sku": clean_sku,
        "shopee_url": clean_url,
        "name": name or clean_sku,
        "brand": brand or "OTHER",
        "price": price,
        "image_url": image_url,
        "cost_price": cost_val,
        "stock": stock_val,
        "created_at": all_items.get(clean_sku, {}).get("created_at", now_str),
        "updated_at": now_str
    }
    
    all_items[clean_sku] = item_data
    
    tmp_file = DATA_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, DATA_FILE)
    
    return item_data

def delete_listed_product(sku: str) -> bool:
    all_items = get_all_listed()
    if sku in all_items:
        del all_items[sku]
        tmp_file = DATA_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(all_items, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, DATA_FILE)
        return True
    return False

def get_dashboard_summary() -> dict:
    all_items = get_all_listed()
    total_listed = len(all_items)
    
    brand_counts = {}
    total_value = 0.0
    
    for item in all_items.values():
        b = (item.get("brand") or "OTHER").upper()
        brand_counts[b] = brand_counts.get(b, 0) + 1
        total_value += float(item.get("price") or 0.0)
        
    recent_items = sorted(list(all_items.values()), key=lambda x: x.get("updated_at", ""), reverse=True)[:10]
    
    return {
        "total_listed": total_listed,
        "total_catalog": 96437,
        "in_stock_catalog": 52792,
        "estimated_store_value": round(total_value, 2),
        "brand_counts": brand_counts,
        "recent_listed": recent_items
    }
