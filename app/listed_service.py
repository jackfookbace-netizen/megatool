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
    all_items = get_all_listed()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    clean_url = shopee_url.strip()
    if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
        clean_url = "https://" + clean_url
        
    item_data = {
        "sku": sku,
        "shopee_url": clean_url,
        "name": name or sku,
        "brand": brand or "OTHER",
        "price": price,
        "image_url": image_url,
        "created_at": all_items.get(sku, {}).get("created_at", now_str),
        "updated_at": now_str
    }
    
    all_items[sku] = item_data
    
    # Save atomically
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
    
    # Brand counters
    brand_counts = {}
    total_value = 0.0
    
    for item in all_items.values():
        b = (item.get("brand") or "OTHER").upper()
        brand_counts[b] = brand_counts.get(b, 0) + 1
        total_value += float(item.get("price") or 0.0)
        
    # Recent listed items (sorted by updated_at descending)
    recent_items = sorted(list(all_items.values()), key=lambda x: x.get("updated_at", ""), reverse=True)[:10]
    
    return {
        "total_listed": total_listed,
        "total_catalog": 96437,
        "in_stock_catalog": 52792,
        "estimated_store_value": round(total_value, 2),
        "brand_counts": brand_counts,
        "recent_listed": recent_items
    }
