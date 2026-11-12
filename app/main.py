import os
import sys
import threading
import uuid
import time
from fastapi import FastAPI, Query, HTTPException, Request, Response, Depends, Header, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from app.ktw_service import search_products, get_product_detail, extract_product_images, detect_brand_from_sku
from app.image_service import (
    generate_cover, generate_collage, generate_comparison_card, upload_to_cdn,
    save_custom_product_image, get_custom_product_images, delete_custom_product_image
)
from app.shopee_service import export_shopee_batch
from app.auth_service import verify_user, create_token, verify_token
from app.shop_service import get_all_shops, get_shop, save_shop
from app.listed_service import (
    get_all_listed, get_listed_product, save_listed_product,
    delete_listed_product, get_dashboard_summary, update_listed_product_price,
    clone_product_to_shop
)
from app.title_service import (
    save_custom_shopee_title, get_custom_shopee_title,
    get_all_custom_shopee_titles, import_shopee_titles_from_excel
)

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="KTW to Shopee Automation Center")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure static folders
os.makedirs("app/static/covers", exist_ok=True)

SAVED_COVERS_FILE = "app/data/saved_covers.json"

def _load_saved_covers_db() -> dict:
    if os.path.exists(SAVED_COVERS_FILE):
        try:
            import json
            with open(SAVED_COVERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_saved_covers_db(db: dict):
    os.makedirs(os.path.dirname(SAVED_COVERS_FILE), exist_ok=True)
    import json
    with open(SAVED_COVERS_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

@app.get("/static/covers/{filename}")
def serve_cover_image(filename: str):
    file_path = os.path.join("app/static/covers", filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="image/jpeg")

    # Self-Healing: Re-generate on demand if missing after container deploy/reboot
    db = _load_saved_covers_db()
    clean_target = f"/static/covers/{filename}"
    matched_entry = None
    for sku, items in db.items():
        for item in items:
            u = (item.get("url") if isinstance(item, dict) else str(item)).split("?")[0]
            if u == clean_target or filename in u:
                matched_entry = item
                break
        if matched_entry:
            break

    # Fallback: check if SKU can be inferred from filename
    if not matched_entry:
        possible_sku = filename.split("_")[0]
        if possible_sku in db and db[possible_sku]:
            matched_entry = db[possible_sku][0]

    if matched_entry and isinstance(matched_entry, dict):
        try:
            specs = matched_entry.get("specs", {})
            sku = matched_entry.get("sku") or filename.split("_")[0]
            raw_url = matched_entry.get("image_url")
            if not raw_url:
                from app.ktw_service import fetch_ktw_detail, extract_product_images
                ktw_det = fetch_ktw_detail(sku)
                imgs = extract_product_images(ktw_det)
                raw_url = imgs[0] if imgs else None

            if raw_url:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                from app.image_service import generate_cover
                generate_cover(
                    raw_url,
                    file_path,
                    brand=matched_entry.get("brand") or detect_brand_from_sku(sku),
                    sku=sku,
                    badge_text=matched_entry.get("badge_text", "มีสต็อกพร้อมส่งทันที"),
                    shop_name=matched_entry.get("shop_name", "MEGATOOL"),
                    template_type=matched_entry.get("template_type", "auto_spec"),
                    custom_model=specs.get("custom_model"),
                    custom_category=specs.get("custom_category"),
                    custom_hero_pills=specs.get("custom_hero_pills"),
                    custom_spec_cards=specs.get("custom_spec_cards"),
                    custom_trust_s1=specs.get("custom_trust_s1"),
                    custom_trust_s2=specs.get("custom_trust_s2")
                )
                if os.path.exists(file_path):
                    return FileResponse(file_path, media_type="image/jpeg")
        except Exception as e:
            print(f"Auto-heal cover {filename} failed:", e)

        # Fallback to CDN redirect if available so image NEVER fails to open
        if matched_entry.get("cdn_url"):
            from fastapi.responses import RedirectResponse
            return RedirectResponse(matched_entry["cdn_url"], status_code=302)

    raise HTTPException(status_code=404, detail="Cover not found")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

def get_current_user(request: Request, authorization: Optional[str] = Header(None)) -> Optional[dict]:
    token = None
    # Check Authorization header (Bearer <token>)
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1].strip()
    # Or check cookie
    if not token:
        token = request.cookies.get("megatool_token")
    if token:
        return verify_token(token)
    return None

def require_auth(request: Request, authorization: Optional[str] = Header(None)) -> dict:
    user = get_current_user(request, authorization)
    if not user:
        raise HTTPException(status_code=401, detail="จำเป็นต้องเข้าสู่ระบบก่อนใช้งาน")
    return user

@app.get("/")
def get_index():
    response = FileResponse("app/static/index.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

class LoginRequest(BaseModel):
    email: str
    password: str
    remember_me: Optional[bool] = True

@app.post("/api/login")
def api_login(req: LoginRequest, response: Response):
    user = verify_user(req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="อีเมลหรือรหัสผ่านไม่ถูกต้อง")
    
    token = create_token(user, remember_me=bool(req.remember_me))
    max_age = (30 * 24 * 3600) if req.remember_me else (24 * 3600)
    
    response.set_cookie(
        key="megatool_token",
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=False
    )
    return {
        "success": True,
        "token": token,
        "user": user
    }

@app.get("/api/me")
def api_me(user: dict = Depends(require_auth)):
    return user

@app.post("/api/logout")
def api_logout(response: Response):
    response.delete_cookie("megatool_token")
    return {"success": True, "message": "ออกจากระบบเรียบร้อยแล้ว"}

class AttachShopeeRequest(BaseModel):
    sku: str
    shopee_url: str
    name: Optional[str] = ""
    brand: Optional[str] = ""
    price: Optional[float] = 0.0
    cost_price: Optional[float] = None
    image_url: Optional[str] = ""
    variation_name: Optional[str] = ""
    shop_id: Optional[str] = "shop_1"

@app.get("/api/shops")
def api_get_shops():
    return {"shops": get_all_shops()}

@app.post("/api/shops")
def api_save_shop(shop_data: dict, request: Request, authorization: Optional[str] = Header(None)):
    user = require_auth(request, authorization)
    updated = save_shop(shop_data)
    return {"success": True, "shop": updated}

@app.get("/api/listed")
def api_get_listed(shop_id: Optional[str] = Query("shop_1")):
    items = get_all_listed(shop_id=shop_id or "shop_1")
    for item in items.values():
        if not item.get("ktw_url"):
            item["ktw_url"] = f"https://shop.ktw.co.th/p/{item.get('sku')}"
    return {"items": list(items.values()), "total": len(items), "shop_id": shop_id}

@app.post("/api/listed/sync-now")
def api_sync_listed_now(shop_id: Optional[str] = Query("shop_1")):
    items = get_all_listed(shop_id=shop_id or "shop_1", refresh_stock=True, force_sync_blocking=True)
    items_list = list(items.values())
    out_of_stock = sum(1 for x in items_list if x.get("stock_alert") == "out_of_stock")
    low_stock = sum(1 for x in items_list if x.get("stock_alert") == "low_stock")
    low_margin = sum(1 for x in items_list if x.get("margin_alert") in ("loss", "low"))
    return {
        "success": True,
        "items": items_list,
        "total": len(items_list),
        "shop_id": shop_id,
        "out_of_stock_count": out_of_stock,
        "low_stock_count": low_stock,
        "low_margin_count": low_margin
    }

@app.post("/api/listed")
def api_save_listed(req: AttachShopeeRequest, request: Request, authorization: Optional[str] = Header(None)):
    user = require_auth(request, authorization)
    if not req.sku or not req.shopee_url:
        raise HTTPException(status_code=400, detail="กรุณาระบุรหัส SKU และลิงก์ Shopee")
    item = save_listed_product(
        sku=req.sku,
        shopee_url=req.shopee_url,
        name=req.name,
        brand=req.brand,
        price=req.price or 0.0,
        image_url=req.image_url or "",
        variation_name=req.variation_name or "",
        cost_price=req.cost_price,
        shop_id=req.shop_id or "shop_1"
    )
    return {"success": True, "item": item}

class UpdatePriceRequest(BaseModel):
    sku: str
    price: float
    shop_id: Optional[str] = "shop_1"

@app.post("/api/listed/price")
def api_update_listed_price(req: UpdatePriceRequest, request: Request, authorization: Optional[str] = Header(None)):
    user = require_auth(request, authorization)
    if not req.sku or req.price <= 0:
        raise HTTPException(status_code=400, detail="กรุณาระบุ SKU และราคาที่ถูกต้อง")
    item = update_listed_product_price(req.sku, req.price, shop_id=req.shop_id or "shop_1")
    if not item:
        raise HTTPException(status_code=404, detail="ไม่พบสินค้าในรายการที่ลงขาย")
    return {"success": True, "item": item}

@app.delete("/api/listed/{sku}")
def api_delete_listed(sku: str, request: Request, authorization: Optional[str] = Header(None), shop_id: Optional[str] = Query("shop_1")):
    user = require_auth(request, authorization)
    deleted = delete_listed_product(sku, shop_id=shop_id or "shop_1")
    return {"success": deleted}

class CloneProductRequest(BaseModel):
    skus: List[str]
    from_shop_id: Optional[str] = "shop_1"
    to_shop_id: Optional[str] = "shop_2"
    price_mode: Optional[str] = "auto"
    custom_price: Optional[float] = None
    custom_name: Optional[str] = None
    custom_image: Optional[str] = None

@app.post("/api/shops/clone")
def api_clone_products(req: CloneProductRequest, request: Request, authorization: Optional[str] = Header(None)):
    require_auth(request, authorization)
    if not req.skus:
        raise HTTPException(status_code=400, detail="กรุณาระบุอย่างน้อย 1 SKU เพื่อ Clone")
    cloned_items = []
    for sku in req.skus:
        item = clone_product_to_shop(
            sku=sku,
            from_shop_id=req.from_shop_id or "shop_1",
            to_shop_id=req.to_shop_id or "shop_2",
            price_mode=req.price_mode or "auto",
            custom_price=req.custom_price,
            custom_name=req.custom_name,
            custom_image=req.custom_image
        )
        cloned_items.append(item)
    return {"success": True, "cloned_count": len(cloned_items), "items": cloned_items}

class SaveCartRequest(BaseModel):
    shop_id: Optional[str] = "shop_1"
    items: List[dict]

@app.get("/api/cart")
def api_get_cart(shop_id: Optional[str] = Query("shop_1")):
    cart_file = "app/data/cart.json"
    if os.path.exists(cart_file):
        try:
            import json
            from app.ktw_service import DEALER_MASTER_COSTS
            with open(cart_file, "r", encoding="utf-8") as f:
                cdata = json.load(f)
            items = cdata.get(shop_id, [])
            listed_map = get_all_listed(shop_id=shop_id or "shop_1", refresh_stock=False)
            for it in items:
                sku = (it.get("sku") or "").strip()
                if not it.get("cost_price") or float(it.get("cost_price") or 0) <= 0:
                    if sku.upper() in DEALER_MASTER_COSTS:
                        it["cost_price"] = DEALER_MASTER_COSTS[sku.upper()]["cost"]
                    elif sku in listed_map and listed_map[sku].get("cost_price"):
                        it["cost_price"] = listed_map[sku]["cost_price"]
            return {"success": True, "items": items}
        except Exception as e:
            print("Error reading cart.json:", e)
    return {"success": True, "items": []}

@app.post("/api/cart")
def api_save_cart(req: SaveCartRequest):
    cart_file = "app/data/cart.json"
    cdata = {}
    if os.path.exists(cart_file):
        try:
            import json
            with open(cart_file, "r", encoding="utf-8") as f:
                cdata = json.load(f)
        except Exception:
            cdata = {}
    sid = req.shop_id or "shop_1"
    cdata[sid] = req.items
    try:
        import json
        with open(cart_file, "w", encoding="utf-8") as f:
            json.dump(cdata, f, ensure_ascii=False, indent=2)
        return {"success": True, "saved_count": len(req.items)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/dashboard/stats")
def api_dashboard_stats(shop_id: Optional[str] = Query("shop_1")):
    return get_dashboard_summary(shop_id=shop_id or "shop_1")

@app.get("/api/search")
def api_search(
    request: Request,
    authorization: Optional[str] = Header(None),
    q: str = Query("*", description="Search query"),
    brand: Optional[str] = Query(None, description="Brand filter"),
    in_stock: bool = Query(True, description="In stock only"),
    exclude_spares: bool = Query(True, description="Filter out spare parts"),
    bestseller_only: bool = Query(False, description="Filter KTW bestseller items only"),
    exclude_listed: bool = Query(False, description="Filter out products already live on Shopee"),
    page: int = Query(0, description="Page index"),
    page_size: int = Query(20, description="Page size")
):
    user = get_current_user(request, authorization)
    listed_map = get_all_listed()
    exclude_skus = set(listed_map.keys()) if exclude_listed else None

    # Perform search with pre-filtered listed items
    data = search_products(
        query=q,
        brand=brand,
        in_stock_only=in_stock,
        exclude_spare_parts=exclude_spares,
        bestseller_only=bestseller_only,
        page=page,
        page_size=page_size,
        exclude_listed_skus=exclude_skus
    )
    
    # Cost is visible when logged in, hidden otherwise
    is_hidden = (user is None)
    filtered_products = []
    for p in data.get("products", []):
        p["is_cost_hidden"] = is_hidden
        sku = p.get("sku")
        if sku in listed_map:
            p["is_listed"] = True
            p["shopee_url"] = listed_map[sku].get("shopee_url")
        else:
            p["is_listed"] = False
            p["shopee_url"] = None
            
        if exclude_listed and p["is_listed"]:
            continue
        filtered_products.append(p)
            
    data["products"] = filtered_products
    return data

@app.get("/api/product/{sku}")
def api_product(sku: str, request: Request, authorization: Optional[str] = Header(None)):
    detail = get_product_detail(sku)
    if not detail:
        raise HTTPException(status_code=404, detail="Product not found")
    user = get_current_user(request, authorization)
    detail["is_cost_hidden"] = (user is None)
    detail["custom_images"] = get_custom_product_images(sku)
        
    return detail

@app.get("/api/product-images/{sku}")
def api_product_images(sku: str):
    detail = get_product_detail(sku)
    images = extract_product_images(detail) if detail else []
    custom_images = get_custom_product_images(sku)
    for c_img in custom_images:
        c_fname = c_img.split('/')[-1].split('?')[0]
        if not any(c_fname in u for u in images):
            images.append(c_img)
    return {"sku": sku, "images": images, "custom_images": custom_images}

class DeleteCustomImageRequest(BaseModel):
    sku: str
    image_url: str

@app.post("/api/delete-custom-image")
def api_delete_custom_image(req: DeleteCustomImageRequest):
    removed = delete_custom_product_image(req.sku, req.image_url)
    return {"status": "ok", "removed": removed}

class SaveCustomTitleRequest(BaseModel):
    sku: str
    title: str
    source: Optional[str] = "manual"

@app.get("/api/shopee/custom-titles")
def api_get_custom_titles():
    return {"success": True, "titles": get_all_custom_shopee_titles()}

@app.post("/api/shopee/save-custom-title")
def api_save_custom_title(req: SaveCustomTitleRequest):
    ok = save_custom_shopee_title(req.sku, req.title, source=req.source or "manual")
    return {"success": ok}

@app.post("/api/shopee/import-titles-excel")
async def api_import_titles_excel(file: UploadFile = File(...)):
    try:
        content = await file.read()
        res = import_shopee_titles_from_excel(content, filename=file.filename or "")
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class PreviewRequest(BaseModel):
    sku: str
    image_url: str
    brand: Optional[str] = None
    badge_text: Optional[str] = None
    custom_footer: Optional[str] = None
    shop_name: Optional[str] = "MEGATOOL"
    template_type: Optional[str] = "standard"
    custom_model: Optional[str] = None
    custom_category: Optional[str] = None
    custom_hero_pills: Optional[List[str]] = None
    custom_spec_cards: Optional[List[Dict[str, Any]]] = None
    custom_trust_s1: Optional[str] = None
    custom_trust_s2: Optional[str] = None

@app.get("/api/cover-spec-defaults/{sku}")
def api_cover_spec_defaults(sku: str, shop_name: Optional[str] = "MEGATOOL"):
    try:
        from app.image_service import get_auto_cover_defaults
        defaults = get_auto_cover_defaults(sku, shop_name=shop_name or "MEGATOOL")
        return defaults
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class CoverCustomizationRequest(BaseModel):
    sku: str
    custom_model: Optional[str] = None
    custom_category: Optional[str] = None
    custom_hero_pills: Optional[List[str]] = None
    custom_spec_cards: Optional[List[Dict[str, Any]]] = None
    custom_trust_s1: Optional[str] = None
    custom_trust_s2: Optional[str] = None
    shopee_title: Optional[str] = None

@app.get("/api/cover-customizations/{sku}")
def api_get_cover_customizations(sku: str):
    file_path = "app/data/cover_customizations.json"
    if os.path.exists(file_path):
        try:
            import json
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {"success": True, "customizations": data.get(sku)}
        except Exception:
            pass
    return {"success": True, "customizations": None}

@app.post("/api/cover-customizations")
def api_save_cover_customizations(req: CoverCustomizationRequest):
    import time
    file_path = "app/data/cover_customizations.json"
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    data = {}
    if os.path.exists(file_path):
        try:
            import json
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data[req.sku] = {
        "custom_model": req.custom_model,
        "custom_category": req.custom_category,
        "custom_hero_pills": req.custom_hero_pills,
        "custom_spec_cards": req.custom_spec_cards,
        "custom_trust_s1": req.custom_trust_s1,
        "custom_trust_s2": req.custom_trust_s2,
        "shopee_title": req.shopee_title,
        "updated_at": int(time.time())
    }
    try:
        import json
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class SaveCoverRequest(BaseModel):
    sku: str
    url: str
    cdn_url: Optional[str] = None
    image_url: Optional[str] = None
    specs: Optional[Dict[str, Any]] = None

@app.get("/api/saved-covers/{sku}")
def api_get_saved_covers(sku: str):
    db = _load_saved_covers_db()
    items = db.get(sku, [])
    # Return all saved covers with specs and CDN urls (self-healing route handles disk misses)
    return {"success": True, "sku": sku, "covers": items}

@app.post("/api/saved-covers")
def api_save_cover_entry(req: SaveCoverRequest):
    if not req.sku or not req.url:
        raise HTTPException(status_code=400, detail="Missing sku or url")
    db = _load_saved_covers_db()
    if req.sku not in db:
        db[req.sku] = []
    
    clean_url = req.url.split("?")[0]
    exists = False
    for existing in db[req.sku]:
        existing_url = (existing.get("url") if isinstance(existing, dict) else str(existing)).split("?")[0]
        if existing_url == clean_url:
            exists = True
            if isinstance(existing, dict):
                if req.specs: existing["specs"] = req.specs
                if req.cdn_url: existing["cdn_url"] = req.cdn_url
                if req.image_url: existing["image_url"] = req.image_url
            break
            
    if not exists:
        from datetime import datetime
        db[req.sku].insert(0, {
            "url": req.url,
            "cdn_url": req.cdn_url,
            "image_url": req.image_url,
            "specs": req.specs or {},
            "created_at": datetime.now().isoformat()
        })
        db[req.sku] = db[req.sku][:15]
        
    _save_saved_covers_db(db)
    return {"success": True, "covers": db[req.sku]}

class DeleteCoverRequest(BaseModel):
    sku: str
    url: str

@app.delete("/api/saved-covers")
def api_delete_saved_cover(req: DeleteCoverRequest):
    if not req.sku or not req.url:
        raise HTTPException(status_code=400, detail="Missing sku or url")
    db = _load_saved_covers_db()
    if req.sku in db:
        clean_target = req.url.split("?")[0]
        db[req.sku] = [
            it for it in db[req.sku]
            if (it.get("url") if isinstance(it, dict) else str(it)).split("?")[0] != clean_target
        ]
        _save_saved_covers_db(db)
    if "/static/covers/" in req.url:
        fname = req.url.split("/static/covers/")[-1].split("?")[0]
        fpath = f"app/static/covers/{fname}"
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass
    return {"success": True}

@app.post("/api/preview-cover")
def api_preview_cover(req: PreviewRequest):
    import hashlib, re, time
    brand = req.brand or detect_brand_from_sku(req.sku)
    shop_str = re.sub(r'[^a-zA-Z0-9]', '', (req.shop_name or 'MEGATOOL').lower())
    tmpl_type = req.template_type or "standard"
    custom_str = f"{req.custom_category}_{req.custom_hero_pills}_{req.custom_spec_cards}_{req.custom_trust_s1}_{req.custom_trust_s2}"
    url_hash = hashlib.md5(f"{req.image_url}_{shop_str}_{tmpl_type}_{req.badge_text}_{req.custom_model}_{custom_str}".encode('utf-8')).hexdigest()[:8]
    output_filename = f"{req.sku}_{shop_str}_{tmpl_type}_{url_hash}_preview.jpg"
    output_path = f"app/static/covers/{output_filename}"
    try:
        generate_cover(
            req.image_url,
            output_path,
            brand=brand,
            sku=req.sku,
            badge_text=req.badge_text,
            custom_footer=req.custom_footer,
            shop_name=req.shop_name or "MEGATOOL",
            overwrite=True,
            template_type=tmpl_type,
            custom_model=req.custom_model,
            custom_category=req.custom_category,
            custom_hero_pills=req.custom_hero_pills,
            custom_spec_cards=req.custom_spec_cards,
            custom_trust_s1=req.custom_trust_s1,
            custom_trust_s2=req.custom_trust_s2
        )
        t_stamp = int(time.time())
        preview_url = f"/static/covers/{output_filename}?t={t_stamp}"

        # Auto-register newly generated cover into saved_covers.json and launch CDN backup
        try:
            from datetime import datetime
            import threading
            db = _load_saved_covers_db()
            if req.sku not in db:
                db[req.sku] = []
            clean_url = f"/static/covers/{output_filename}"
            existing_entry = next((c for c in db[req.sku] if isinstance(c, dict) and c.get("url", "").split("?")[0] == clean_url), None)
            if existing_entry:
                existing_entry["image_url"] = req.image_url
                existing_entry["brand"] = brand
                existing_entry["badge_text"] = req.badge_text
                existing_entry["shop_name"] = req.shop_name or "MEGATOOL"
                existing_entry["template_type"] = tmpl_type
                existing_entry["specs"] = {
                    "custom_category": req.custom_category,
                    "custom_model": req.custom_model,
                    "custom_hero_pills": req.custom_hero_pills,
                    "custom_spec_cards": req.custom_spec_cards,
                    "custom_trust_s1": req.custom_trust_s1,
                    "custom_trust_s2": req.custom_trust_s2
                }
                existing_entry["created_at"] = datetime.now().isoformat()
            else:
                new_cover_entry = {
                    "url": clean_url,
                    "cdn_url": None,
                    "sku": req.sku,
                    "image_url": req.image_url,
                    "brand": brand,
                    "badge_text": req.badge_text,
                    "shop_name": req.shop_name or "MEGATOOL",
                    "template_type": tmpl_type,
                    "specs": {
                        "custom_category": req.custom_category,
                        "custom_model": req.custom_model,
                        "custom_hero_pills": req.custom_hero_pills,
                        "custom_spec_cards": req.custom_spec_cards,
                        "custom_trust_s1": req.custom_trust_s1,
                        "custom_trust_s2": req.custom_trust_s2
                    },
                    "created_at": datetime.now().isoformat()
                }
                db[req.sku].insert(0, new_cover_entry)
                db[req.sku] = db[req.sku][:15]
            _save_saved_covers_db(db)

            # Auto-save customizations to app/data/cover_customizations.json
            try:
                cust_file = "app/data/cover_customizations.json"
                cust_data = {}
                if os.path.exists(cust_file):
                    with open(cust_file, "r", encoding="utf-8") as f:
                        cust_data = json.load(f)
                cust_data[req.sku] = {
                    "custom_model": req.custom_model,
                    "custom_category": req.custom_category,
                    "custom_hero_pills": req.custom_hero_pills,
                    "custom_spec_cards": req.custom_spec_cards,
                    "custom_trust_s1": req.custom_trust_s1,
                    "custom_trust_s2": req.custom_trust_s2,
                    "updated_at": int(time.time())
                }
                with open(cust_file, "w", encoding="utf-8") as f:
                    json.dump(cust_data, f, ensure_ascii=False, indent=2)
            except Exception as ce:
                print("Auto-save cover_customizations error:", ce)

            # Background CDN upload so the cover has a permanent global URL
            def bg_upload_cover(target_file, target_sku, target_clean_url):
                try:
                    from app.image_service import upload_to_cdn
                    cdn_res = upload_to_cdn(target_file, force=True)
                    if cdn_res and cdn_res.startswith("http"):
                        cur_db = _load_saved_covers_db()
                        if target_sku in cur_db:
                            for it in cur_db[target_sku]:
                                if isinstance(it, dict) and it.get("url", "").split("?")[0] == target_clean_url:
                                    it["cdn_url"] = cdn_res
                                    break
                            _save_saved_covers_db(cur_db)
                except Exception as ex:
                    print("Background CDN upload error:", ex)

            threading.Thread(target=bg_upload_cover, args=(output_path, req.sku, clean_url), daemon=True).start()
        except Exception as e:
            print("Auto-save cover failed:", e)

        cdn_cached = None
        try:
            with open("app/static/covers/cdn_cache.json", "r", encoding="utf-8") as f:
                import json
                c_data = json.load(f)
                cdn_cached = c_data.get(output_filename)
        except Exception:
            pass

        return {"preview_url": preview_url, "cdn_url": cdn_cached}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class CollageRequest(BaseModel):
    sku: str
    image_urls: List[str]
    model_text: Optional[str] = ""
    title: Optional[str] = ""
    badge_text: Optional[str] = "มีสต็อกพร้อมส่งทันที"
    shop_name: Optional[str] = "MEGATOOL"
    font_size: Optional[int] = 34
    position: Optional[str] = "top-left"
    text_color: Optional[str] = "#FFFFFF"
    badge_style: Optional[str] = "solid"

@app.post("/api/generate-collage")
def api_generate_collage(req: CollageRequest):
    import hashlib
    if not req.image_urls or len(req.image_urls) < 1:
        raise HTTPException(status_code=400, detail="กรุณาเลือกรูปภาพอย่างน้อย 1 รูปภาพครับ")
    
    clean_model = (req.model_text if req.model_text is not None else "").strip()
    clean_title = (req.title if req.title is not None else "").strip()
    clean_badge = (req.badge_text or "มีสต็อกพร้อมส่งทันที").strip()
    font_sz = int(req.font_size or 38)
    pos = (req.position or "top-left").lower().strip()
    color = (req.text_color or "#FFFFFF").strip()
    b_style = (req.badge_style or "solid").lower().strip()
    raw_hash_str = f"{req.sku}_{'_'.join(req.image_urls[:4])}_{clean_model}_{clean_title}_{clean_badge}_{font_sz}_{pos}_{color}_{b_style}"
    url_hash = hashlib.md5(raw_hash_str.encode('utf-8')).hexdigest()[:8]
    filename = f"collage_{req.sku}_{url_hash}.jpg"
    local_path = f"app/static/covers/{filename}"
    
    try:
        generate_collage(
            req.image_urls[:4],
            local_path,
            model_text=clean_model,
            title=clean_title,
            badge_text=clean_badge,
            shop_name=req.shop_name or "MEGATOOL",
            font_size=font_sz,
            position=pos,
            text_color=color,
            badge_style=b_style
        )
        
        cdn_url = upload_to_cdn(local_path, force=True)
        public_url = cdn_url if (cdn_url and cdn_url.startswith('http')) else f"https://megatool-yrho.onrender.com/static/covers/{filename}"
        
        # Save to persistent storage permanently
        save_custom_product_image(req.sku, f"/static/covers/{filename}", cdn_url=public_url)
        
        return {
            "collage_url": f"/static/covers/{filename}",
            "cdn_url": public_url,
            "filename": filename
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ComparisonCardRequest(BaseModel):
    items: List[dict]
    parent_title: Optional[str] = "เปรียบเทียบสเปกและฟังก์ชันแต่ละรุ่น"
    shop_name: Optional[str] = "MEGATOOL"

@app.post("/api/generate-comparison")
def api_generate_comparison(req: ComparisonCardRequest):
    import hashlib
    import time
    if not req.items or len(req.items) < 2:
        raise HTTPException(status_code=400, detail="จำเป็นต้องมีสินค้าอย่างน้อย 2 รุ่นเพื่อสร้างตารางเปรียบเทียบ")
    
    items_sig = "_".join([f"{item.get('sku', '')}:{item.get('price', '')}:{item.get('name', '')}" for item in req.items])
    url_hash = hashlib.md5(f"{items_sig}_{req.parent_title}_{time.time()}".encode('utf-8')).hexdigest()[:8]
    filename = f"comparison_{url_hash}.jpg"
    local_path = f"app/static/covers/{filename}"
    
    try:
        generate_comparison_card(
            req.items,
            local_path,
            parent_title=req.parent_title or "เปรียบเทียบสเปกและฟังก์ชันแต่ละรุ่น",
            shop_name=req.shop_name or "MEGATOOL"
        )
        
        cdn_url = upload_to_cdn(local_path, force=True)
        public_url = cdn_url if (cdn_url and cdn_url.startswith('http')) else f"https://megatool-yrho.onrender.com/static/covers/{filename}"
        
        return {
            "card_url": f"/static/covers/{filename}",
            "cdn_url": public_url,
            "filename": filename
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ExportItem(BaseModel):
    sku: str
    price: Optional[float] = None
    badge: Optional[str] = None
    variation_name: Optional[str] = None
    shopee_title: Optional[str] = None
    selected_image: Optional[str] = None
    selected_images: Optional[List[str]] = None
    use_template: Optional[bool] = True
    template_type: Optional[str] = "auto_spec"
    unframed_images: Optional[List[str]] = None
    custom_model: Optional[str] = None
    custom_category: Optional[str] = None
    custom_hero_pills: Optional[List[str]] = None
    custom_spec_cards: Optional[List[Dict[str, Any]]] = None
    custom_trust_s1: Optional[str] = None
    custom_trust_s2: Optional[str] = None

class ExportRequest(BaseModel):
    items: List[ExportItem]
    filename: Optional[str] = "Shopee_Mass_Upload_Batch_Auto.xlsx"
    shop_id: Optional[str] = "shop_1"
    shop_name: Optional[str] = None
    is_variation_group: Optional[bool] = False
    parent_title: Optional[str] = None
    variation_group_name: Optional[str] = "รุ่นสินค้า"
    comparison_card_url: Optional[str] = None
    include_comparison: Optional[bool] = True

export_tasks = {}

@app.post("/api/export")
def api_export(req: ExportRequest, request: Request, authorization: Optional[str] = Header(None)):
    # Requires logged-in user
    require_auth(request, authorization)
    if not req.items:
        raise HTTPException(status_code=400, detail="No items to export")
    items_data = [item.dict() for item in req.items]
    target_shop = get_shop(req.shop_id or "shop_1")
    eff_shop_name = req.shop_name or target_shop.get("brand_display") or "MEGATOOL"
    
    task_id = str(uuid.uuid4())[:12]
    export_tasks[task_id] = {
        "status": "processing",
        "current": 0,
        "total": len(items_data),
        "percent": 0,
        "sku": "",
        "download_url": None,
        "created_at": time.time()
    }

    def run_worker():
        def progress(cur, tot, sku):
            if task_id in export_tasks:
                export_tasks[task_id]["current"] = cur
                export_tasks[task_id]["total"] = tot
                export_tasks[task_id]["percent"] = min(int((cur / max(tot, 1)) * 95), 95)
                export_tasks[task_id]["sku"] = sku

        try:
            file_url = export_shopee_batch(
                items_data, 
                req.filename, 
                shop_name=eff_shop_name,
                is_variation_group=req.is_variation_group or False,
                parent_title=req.parent_title,
                variation_group_name=req.variation_group_name or "รุ่นสินค้า",
                comparison_card_url=req.comparison_card_url,
                include_comparison=req.include_comparison if req.include_comparison is not None else True,
                progress_callback=progress
            )
            export_tasks[task_id]["status"] = "completed"
            export_tasks[task_id]["current"] = len(items_data)
            export_tasks[task_id]["total"] = len(items_data)
            export_tasks[task_id]["percent"] = 100
            export_tasks[task_id]["download_url"] = file_url
            export_tasks[task_id]["sku"] = ""
        except Exception as e:
            print(f"Export task {task_id} failed:", e)
            export_tasks[task_id]["status"] = "error"
            export_tasks[task_id]["message"] = str(e)

    threading.Thread(target=run_worker, daemon=True).start()
    return {"task_id": task_id}

@app.get("/api/export-progress/{task_id}")
def api_export_progress(task_id: str):
    task = export_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Export task not found")
    return task

class BatchAutoSpecRequest(BaseModel):
    shop_id: Optional[str] = "shop_1"
    shop_name: Optional[str] = "MEGATOOL"
    skus: Optional[List[str]] = None
    force_regenerate: Optional[bool] = False

@app.post("/api/cart/batch-auto-spec")
def api_batch_auto_spec_cart(req: BatchAutoSpecRequest):
    """Generates Ultra-HD 2400x2400 Auto-Spec covers for all items in the cart, uploads to CDN, and saves 100% online."""
    import hashlib
    from datetime import datetime
    from concurrent.futures import ThreadPoolExecutor
    from app.ktw_service import get_product_detail, prefetch_product_details, clean_brand_name, extract_product_images
    from app.image_service import generate_cover, upload_to_cdn

    sid = req.shop_id or "shop_1"
    s_name = req.shop_name or ("BIGPOWER TOOLS" if sid == "shop_2" else "MEGATOOL")

    cart_file = "app/data/cart.json"
    cart_data = {"shop_1": [], "shop_2": []}
    if os.path.exists(cart_file):
        try:
            with open(cart_file, "r", encoding="utf-8") as f:
                cart_data = json.load(f)
        except Exception:
            pass
    items_list = cart_data.get(sid, [])
    if not items_list:
        return {"success": True, "processed": 0, "items": []}

    cust_file = "app/data/cover_customizations.json"
    cust_db = {}
    if os.path.exists(cust_file):
        try:
            with open(cust_file, "r", encoding="utf-8") as f:
                cust_db = json.load(f)
        except Exception:
            pass

    saved_db = _load_saved_covers_db()
    target_skus = set(req.skus) if req.skus else {it.get("sku") for it in items_list if it.get("sku")}
    prefetch_product_details(list(target_skus))

    def _process_cart_item(item):
        sku = item.get("sku")
        if not sku or sku not in target_skus:
            return False

        # If item already has an active saved cover on iili.io and not force_regenerate, reuse it
        existing_covers = saved_db.get(sku, [])
        if not req.force_regenerate and existing_covers:
            top_cov = existing_covers[0]
            if isinstance(top_cov, dict) and top_cov.get("cdn_url", "").startswith("https://iili.io/"):
                cdn_u = top_cov["cdn_url"]
                item["selected_image"] = cdn_u
                item["image"] = cdn_u
                item["cdn_url"] = cdn_u
                item["use_template"] = True
                item["template_type"] = "auto_spec"
                return True

        detail = get_product_detail(sku) or {}
        imgs = extract_product_images(detail)
        raw_img = imgs[0] if imgs else (item.get("image") or item.get("selected_image") or "")
        # Ensure we use original KTW photo as source, not an already-framed cover
        if "iili.io" in str(raw_img) or "/static/covers/" in str(raw_img):
            if imgs:
                raw_img = imgs[0]
        if not raw_img:
            return False

        brand = item.get("brand") or clean_brand_name(detail.get("manufacturer"), sku)
        cust = cust_db.get(sku, {})
        c_model = item.get("custom_model") or cust.get("custom_model")
        c_cat = item.get("custom_category") or cust.get("custom_category")
        c_pills = item.get("custom_hero_pills") or cust.get("custom_hero_pills")
        c_cards = item.get("custom_spec_cards") or cust.get("custom_spec_cards")
        c_s1 = item.get("custom_trust_s1") or cust.get("custom_trust_s1")
        c_s2 = item.get("custom_trust_s2") or cust.get("custom_trust_s2")
        badge = item.get("badge") or "มีสต็อกพร้อมส่งทันที"

        shop_str = re.sub(r'[^a-zA-Z0-9]', '', s_name).lower()[:12] or "megatool"
        extra_hash = f"{c_model}_{c_cat}_{c_pills}_{c_cards}_{c_s1}_{c_s2}"
        url_hash = hashlib.md5(f"{raw_img}_{badge}_{s_name}_auto_spec_{extra_hash}".encode('utf-8')).hexdigest()[:8]
        out_fn = f"{sku}_{shop_str}_auto_spec_{url_hash}_preview.jpg"
        out_path = f"app/static/covers/{out_fn}"
        clean_url = f"/static/covers/{out_fn}"

        generate_cover(
            raw_img,
            out_path,
            brand=brand,
            sku=sku,
            badge_text=badge,
            shop_name=s_name,
            overwrite=True,
            template_type="auto_spec",
            custom_model=c_model,
            custom_category=c_cat,
            custom_hero_pills=c_pills,
            custom_spec_cards=c_cards,
            custom_trust_s1=c_s1,
            custom_trust_s2=c_s2
        )
        cdn_u = upload_to_cdn(out_path, max_retries=2)
        final_u = cdn_u if (cdn_u and cdn_u.startswith("http")) else clean_url

        entry = {
            "url": clean_url,
            "cdn_url": cdn_u,
            "sku": sku,
            "image_url": raw_img,
            "brand": brand,
            "badge_text": badge,
            "shop_name": s_name,
            "template_type": "auto_spec",
            "specs": {
                "custom_category": c_cat,
                "custom_model": c_model,
                "custom_hero_pills": c_pills,
                "custom_spec_cards": c_cards,
                "custom_trust_s1": c_s1,
                "custom_trust_s2": c_s2
            },
            "created_at": datetime.now().isoformat()
        }
        if sku not in saved_db:
            saved_db[sku] = []
        saved_db[sku] = [c for c in saved_db[sku] if isinstance(c, dict) and c.get("url", "").split("?")[0] != clean_url]
        saved_db[sku].insert(0, entry)
        saved_db[sku] = saved_db[sku][:15]

        item["selected_image"] = final_u
        item["image"] = final_u
        item["cdn_url"] = cdn_u
        item["use_template"] = True
        item["template_type"] = "auto_spec"
        return True

    processed_count = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(_process_cart_item, items_list))
        processed_count = sum(1 for r in results if r)

    _save_saved_covers_db(saved_db)
    with open(cart_file, "w", encoding="utf-8") as f:
        json.dump(cart_data, f, ensure_ascii=False, indent=2)

    return {
        "success": True,
        "processed": processed_count,
        "items": items_list,
        "saved_covers": saved_db
    }

@app.get("/api/stats")
def api_stats():
    return {
        "total_catalog": 96280,
        "in_stock_catalog": 52792,
        "brands": [
            {"name": "Makita", "count": 17203, "color": "teal"},
            {"name": "POLO", "count": 4890, "color": "red"},
            {"name": "Karcher", "count": 8065, "color": "yellow"},
            {"name": "Nachi", "count": 5445, "color": "red"},
            {"name": "Force", "count": 2898, "color": "blue"},
            {"name": "DongCheng", "count": 2781, "color": "indigo"},
            {"name": "INGCO", "count": 1956, "color": "orange"},
            {"name": "3M", "count": 1500, "color": "rose"}
        ]
    }
