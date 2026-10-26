import os
import sys
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
from app.image_service import generate_cover
from app.shopee_service import export_shopee_batch
from app.auth_service import verify_user, create_token, verify_token
from app.listed_service import (
    get_all_listed, get_listed_product, save_listed_product,
    delete_listed_product, get_dashboard_summary, update_listed_product_price
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

@app.get("/api/listed")
def api_get_listed():
    items = get_all_listed()
    for item in items.values():
        if not item.get("ktw_url"):
            item["ktw_url"] = f"https://shop.ktw.co.th/p/{item.get('sku')}"
    return {"items": list(items.values()), "total": len(items)}

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
        variation_name=req.variation_name or ""
    )
    return {"success": True, "item": item}

class UpdatePriceRequest(BaseModel):
    sku: str
    price: float

@app.post("/api/listed/price")
def api_update_listed_price(req: UpdatePriceRequest, request: Request, authorization: Optional[str] = Header(None)):
    user = require_auth(request, authorization)
    if not req.sku or req.price <= 0:
        raise HTTPException(status_code=400, detail="กรุณาระบุ SKU และราคาที่ถูกต้อง")
    item = update_listed_product_price(req.sku, req.price)
    if not item:
        raise HTTPException(status_code=404, detail="ไม่พบสินค้าในรายการที่ลงขาย")
    return {"success": True, "item": item}

@app.delete("/api/listed/{sku}")
def api_delete_listed(sku: str, request: Request, authorization: Optional[str] = Header(None)):
    user = require_auth(request, authorization)
    deleted = delete_listed_product(sku)
    return {"success": deleted}

@app.get("/api/dashboard/stats")
def api_dashboard_stats():
    return get_dashboard_summary()

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
    # Perform search
    data = search_products(query=q, brand=brand, in_stock_only=in_stock, exclude_spare_parts=exclude_spares, bestseller_only=bestseller_only, page=page, page_size=page_size)
    
    listed_map = get_all_listed()
    
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
        
    return detail

@app.get("/api/product-images/{sku}")
def api_product_images(sku: str):
    detail = get_product_detail(sku)
    if not detail:
        return {"sku": sku, "images": []}
    return {"sku": sku, "images": extract_product_images(detail)}

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

class ExportItem(BaseModel):
    sku: str
    price: Optional[float] = None
    badge: Optional[str] = None
    variation_name: Optional[str] = None
    selected_image: Optional[str] = None
    selected_images: Optional[List[str]] = None
    use_template: Optional[bool] = True

class ExportRequest(BaseModel):
    items: List[ExportItem]
    filename: Optional[str] = "Shopee_Mass_Upload_Batch_Auto.xlsx"
    shop_name: Optional[str] = "MEGATOOL"
    is_variation_group: Optional[bool] = False
    parent_title: Optional[str] = None
    variation_group_name: Optional[str] = "รุ่นสินค้า"

@app.post("/api/export")
def api_export(req: ExportRequest, request: Request, authorization: Optional[str] = Header(None)):
    # Requires logged-in user
    require_auth(request, authorization)
    if not req.items:
        raise HTTPException(status_code=400, detail="No items to export")
    items_data = [item.dict() for item in req.items]
    try:
        file_url = export_shopee_batch(
            items_data, 
            req.filename, 
            shop_name=req.shop_name or "MEGATOOL",
            is_variation_group=req.is_variation_group or False,
            parent_title=req.parent_title,
            variation_group_name=req.variation_group_name or "รุ่นสินค้า"
        )
        return {"download_url": file_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
