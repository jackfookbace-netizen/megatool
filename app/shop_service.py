import os
import json
from typing import Dict, List, Optional

DATA_DIR = "app/data"
SHOPS_FILE = os.path.join(DATA_DIR, "shops.json")

DEFAULT_SHOPS = {
    "shop_1": {
        "id": "shop_1",
        "name": "MEGATOOL (ร้านหลัก)",
        "code": "SHOP1",
        "brand_display": "MEGATOOL",
        "profit_margin": 0.15,
        "fee_rate": 0.28,
        "min_profit": 50.0,
        "title_prefix": "[{brand} แท้ 100%]",
        "title_suffix": "ของแท้มาตรฐานโรงงาน ประกันศูนย์",
        "tag": "ร้านหลัก / Official",
        "theme_color": "orange",
        "is_default": True,
        "description": "ร้านค้าหลัก เน้นภาพลักษณ์แบรนด์ทางการ สินค้าแท้ศูนย์ 100% พร้อมบริการหลังการขายครบวงจร"
    },
    "shop_2": {
        "id": "shop_2",
        "name": "MEGATOOL Store 2 (สาขา 2)",
        "code": "SHOP2",
        "brand_display": "MEGATOOL ECO",
        "profit_margin": 0.08,
        "fee_rate": 0.28,
        "min_profit": 30.0,
        "title_prefix": "[ส่งด่วนแท้ศูนย์]",
        "title_suffix": "พร้อมส่งทันที มีสต็อกจริง ออกใบกำกับภาษีได้",
        "tag": "สาขา 2 / Eco Outlet",
        "theme_color": "blue",
        "is_default": False,
        "description": "ร้านสาขาที่ 2 เน้นทำราคาแข่งขัน ดึงลูกค้าสายประหยัด ใช้คีย์เวิร์ดและรูปมุมมองพิเศษเพื่อไม่ให้ซ้ำกับร้านแรก"
    }
}

def _init_shops():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(SHOPS_FILE):
        with open(SHOPS_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_SHOPS, f, ensure_ascii=False, indent=2)

_init_shops()

def get_all_shops() -> Dict[str, dict]:
    try:
        if os.path.exists(SHOPS_FILE):
            with open(SHOPS_FILE, "r", encoding="utf-8") as f:
                shops = json.load(f)
                if shops and isinstance(shops, dict):
                    return shops
    except Exception as e:
        print("Error reading shops.json:", e)
    return DEFAULT_SHOPS.copy()

def get_shop(shop_id: str) -> dict:
    shops = get_all_shops()
    if shop_id in shops:
        return shops[shop_id]
    return shops.get("shop_1", DEFAULT_SHOPS["shop_1"])

def save_shop(shop_data: dict) -> dict:
    import time
    shop_id = shop_data.get("id")
    if not shop_id:
        shop_id = f"shop_{int(time.time())}"
        shop_data["id"] = shop_id
    shops = get_all_shops()
    if "profit_margin" in shop_data:
        shop_data["profit_margin"] = round(float(shop_data["profit_margin"]), 4)
    if "fee_rate" in shop_data:
        shop_data["fee_rate"] = round(float(shop_data["fee_rate"]), 4)
    if "min_profit" in shop_data:
        shop_data["min_profit"] = round(float(shop_data["min_profit"]), 2)
    shops[shop_id] = shop_data
    with open(SHOPS_FILE, "w", encoding="utf-8") as f:
        json.dump(shops, f, ensure_ascii=False, indent=2)
    return shop_data

def calculate_shop_price(cost_price: float, shop_id: str = "shop_1") -> float:
    shop = get_shop(shop_id)
    cost = float(cost_price or 0.0)
    if cost <= 0:
        return 0.0
    margin = float(shop.get("profit_margin", 0.15))
    fee_rate = float(shop.get("fee_rate", 0.28))
    min_profit = float(shop.get("min_profit", 30.0))
    
    target_net = max(cost * (1.0 + margin), cost + min_profit)
    fee_factor = max(0.1, 1.0 - fee_rate)
    sale_price = round(target_net / fee_factor)
    return sale_price

from app.seo_service import build_shopee_seo_title

def generate_shop_title(sku: str, raw_name: str, brand: str, shop_id: str = "shop_1") -> str:
    shop = get_shop(shop_id)
    suffix = shop.get("title_suffix", "")
    # If custom user suffix is specified and not default legacy, respect it
    if suffix and suffix not in ("ของแท้มาตรฐานโรงงาน", "ของแท้มาตรฐานโรงงาน ประกันศูนย์"):
        prefix_tpl = shop.get("title_prefix", "[{brand} แท้ 100%]")
        prefix = prefix_tpl.format(brand=brand)
        clean_name = raw_name.replace(f"[{brand}]", "").strip()
        title = f"{prefix} {clean_name} รหัส {sku} {suffix}"
        if len(title) > 120:
            title = title[:117] + "..."
        return title.strip()
    return build_shopee_seo_title(brand, raw_name, sku, is_variation_group=False)
