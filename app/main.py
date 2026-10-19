import os
import sys
from fastapi import FastAPI, Query, HTTPException
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

app = FastAPI(title="KTW to Shopee Automation Center")

# Ensure static folders
os.makedirs("app/static/covers", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/")
def get_index():
    return FileResponse("app/static/index.html")

@app.get("/api/search")
def api_search(
    q: str = Query("*", description="Search query"),
    brand: Optional[str] = Query(None, description="Brand filter"),
    in_stock: bool = Query(True, description="In stock only"),
    exclude_spares: bool = Query(True, description="Filter out spare parts"),
    page: int = Query(0, description="Page index"),
    page_size: int = Query(20, description="Page size")
):
    return search_products(query=q, brand=brand, in_stock_only=in_stock, exclude_spare_parts=exclude_spares, page=page, page_size=page_size)

@app.get("/api/product/{sku}")
def api_product(sku: str):
    detail = get_product_detail(sku)
    if not detail:
        raise HTTPException(status_code=404, detail="Product not found")
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
    brand = req.brand or detect_brand_from_sku(req.sku)
    output_filename = f"{req.sku}_preview.jpg"
    output_path = f"app/static/covers/{output_filename}"
    try:
        generate_cover(
            req.image_url,
            output_path,
            brand=brand,
            sku=req.sku,
            badge_text=req.badge_text,
            custom_footer=req.custom_footer,
            shop_name=req.shop_name or "MEGATOOL"
        )
        return {"preview_url": f"/static/covers/{output_filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ExportItem(BaseModel):
    sku: str
    price: Optional[float] = None
    badge: Optional[str] = None

class ExportRequest(BaseModel):
    items: List[ExportItem]
    filename: Optional[str] = "Shopee_Mass_Upload_Batch_Auto.xlsx"
    shop_name: Optional[str] = "MEGATOOL"

@app.post("/api/export")
def api_export(req: ExportRequest):
    if not req.items:
        raise HTTPException(status_code=400, detail="No items to export")
    items_data = [item.dict() for item in req.items]
    try:
        file_url = export_shopee_batch(items_data, req.filename, shop_name=req.shop_name or "MEGATOOL")
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
            {"name": "Kärcher", "count": 8065, "color": "yellow"},
            {"name": "Nachi", "count": 5445, "color": "red"},
            {"name": "Force", "count": 2898, "color": "blue"},
            {"name": "DongCheng", "count": 2781, "color": "indigo"},
            {"name": "INGCO", "count": 1956, "color": "orange"},
            {"name": "3M", "count": 1500, "color": "rose"}
        ]
    }
