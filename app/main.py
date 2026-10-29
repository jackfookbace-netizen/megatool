import os
import sys
import threading
import uuid
import time
from fastapi import FastAPI, Query, HTTPException, Request, Response, Depends, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional

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

class PreviewRequest(BaseModel):
    sku: str
    image_url: str
    brand: Optional[str] = None
    badge_text: Optional[str] = None
    custom_footer: Optional[str] = None
    shop_name: Optional[str] = "MEGATOOL"

@app.post("/api/preview-cover")
def api_preview_cover(req: PreviewRequest):
    import hashlib
    brand = req.brand or detect_brand_from_sku(req.sku)
    url_hash = hashlib.md5(req.image_url.encode('utf-8')).hexdigest()[:8]
    output_filename = f"{req.sku}_{url_hash}_preview.jpg"
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
            overwrite=True
        )
        return {"preview_url": f"/static/covers/{output_filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class CollageRequest(BaseModel):
    sku: str
    image_urls: List[str]
    model_text: Optional[str] = ""
    title: Optional[str] = "อุปกรณ์มาตรฐานในกล่องครบชุด"
    badge_text: Optional[str] = "มีสต็อกพร้อมส่งทันที"
    shop_name: Optional[str] = "MEGATOOL"
    font_size: Optional[int] = 34
    position: Optional[str] = "top-left"

@app.post("/api/generate-collage")
def api_generate_collage(req: CollageRequest):
    import hashlib
    if not req.image_urls or len(req.image_urls) < 2:
        raise HTTPException(status_code=400, detail="กรุณาเลือกรูปภาพอย่างน้อย 2 รูปเพื่อรวมเป็นภาพเดียว")
    
    clean_model = (req.model_text or "").strip()
    clean_title = (req.title or "อุปกรณ์มาตรฐานในกล่องครบชุด").strip()
    clean_badge = (req.badge_text or "มีสต็อกพร้อมส่งทันที").strip()
    font_sz = int(req.font_size or 38)
    pos = (req.position or "top-left").lower().strip()
    raw_hash_str = f"{req.sku}_{'_'.join(req.image_urls[:4])}_{clean_model}_{clean_title}_{clean_badge}_{font_sz}_{pos}"
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
            position=pos
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
    selected_image: Optional[str] = None
    selected_images: Optional[List[str]] = None
    use_template: Optional[bool] = True
    unframed_images: Optional[List[str]] = None

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
