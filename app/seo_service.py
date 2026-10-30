import re
from typing import List, Dict

SEO_KEYWORD_RULES: List[Dict] = [
    {
        "triggers": ["เครื่องเจียร์", "หินเจียร์", "ลูกหมู", "เจียร์ 4", "เจียร์ 5", "เจียร์ 7"],
        "keywords": ["ลูกหมู", "หินเจียร์", "ตัดขัดเหล็ก"],
    },
    {
        "triggers": ["เครื่องฉีดน้ำ", "ปั๊มอัดฉีด", "เครื่องฉีด"],
        "keywords": ["ปั๊มอัดฉีด", "แรงดันสูง", "ล้างรถ"],
    },
    {
        "triggers": ["ตัดหญ้า"],
        "keywords": ["สะพายบ่า", "ตัดหญ้าสวน"],
    },
    {
        "triggers": ["สว่านโรตารี่", "โรตารี่", "sds"],
        "keywords": ["สว่านกระแทก", "เจาะปูน"],
    },
    {
        "triggers": ["สว่าน", "สว่านไฟฟ้า", "สว่านไขควง", "สว่านแบต"],
        "keywords": ["เจาะปูน/เหล็ก/ไม้"],
    },
    {
        "triggers": ["ปั๊มจุ่ม", "ปั๊มแช่", "ไดโว่"],
        "keywords": ["ไดโว่", "สูบน้ำ", "ดูดน้ำ"],
    },
    {
        "triggers": ["เลื่อยวงเดือน"],
        "keywords": ["เลื่อยตัดไม้"],
    },
    {
        "triggers": ["แท่นตัด", "เครื่องตัด 14", "ไฟเบอร์ตัด"],
        "keywords": ["แท่นไฟเบอร์", "ตัดเหล็ก"],
    },
    {
        "triggers": ["เทปพันสายไฟ", "temflex"],
        "keywords": ["ฉนวนกันไฟฟ้า", "เนื้อกาวเหนียวแน่น"],
    },
    {
        "triggers": ["ปั๊มลม"],
        "keywords": ["ถังลม", "เติมลม พ่นสี"],
    },
    {
        "triggers": ["ตู้เชื่อม", "เครื่องเชื่อม"],
        "keywords": ["ตู้เชื่อมอินเวอร์เตอร์", "เชื่อมเหล็ก"],
    },
    {
        "triggers": ["โบลเวอร์", "เครื่องเป่าลม"],
        "keywords": ["โบลเวอร์", "เป่าฝุ่น ดูดฝุ่น"],
    },
    {
        "triggers": ["กบไสไม้"],
        "keywords": ["ไสไม้ไฟฟ้า", "ปรับหน้าไม้"],
    },
    {
        "triggers": ["จิ๊กซอ", "เลื่อยชัก"],
        "keywords": ["ตัดไม้ ฉลุลาย"],
    },
    {
        "triggers": ["เครื่องขัดกระดาษทราย", "ขัดกระดาษทราย", "ขัดสี"],
        "keywords": ["ขัดไม้", "ขัดสีรถ"],
    },
]

def build_shopee_seo_title(brand: str, raw_name: str, sku: str = "", is_variation_group: bool = False) -> str:
    brand = (brand or "KTW").strip()
    raw_name = (raw_name or "").strip()
    
    # Clean redundant brand from the beginning of product name
    clean_name = re.sub(rf"^\[?{re.escape(brand)}\]?\s*", "", raw_name, flags=re.IGNORECASE).strip()
    # Remove existing square brackets e.g. [xxx]
    clean_name = re.sub(r"\[.*?\]", "", clean_name).strip()
    clean_name = re.sub(r"\s+", " ", clean_name)
    clean_lower = clean_name.lower()
    
    # Collect SEO keywords not yet in title
    added_kw: List[str] = []
    for rule in SEO_KEYWORD_RULES:
        if any(tr.lower() in clean_lower for tr in rule["triggers"]):
            for kw in rule["keywords"]:
                if kw.lower() not in clean_lower and kw.lower() not in [k.lower() for k in added_kw]:
                    added_kw.append(kw)
    
    prefix = f"[{brand} แท้ 100%]"
    trust_suffix = "ประกันศูนย์"
    
    if is_variation_group:
        var_suffix = "รวมทุกรุ่นตัวเลือก ประกันศูนย์"
        parts = [prefix, clean_name] + added_kw + [var_suffix]
        title = " ".join(parts)
        while len(title) > 120 and added_kw:
            added_kw.pop()
            parts = [prefix, clean_name] + added_kw + [var_suffix]
            title = " ".join(parts)
        if len(title) > 120:
            title = f"{prefix} {clean_name} รวมรุ่นตัวเลือก"
            if len(title) > 120:
                title = title[:117] + "..."
    else:
        sku_part = f"รหัส {sku}" if sku else ""
        parts = [prefix, clean_name] + added_kw + [trust_suffix, sku_part]
        title = " ".join([p for p in parts if p])
        while len(title) > 120 and added_kw:
            added_kw.pop()
            parts = [prefix, clean_name] + added_kw + [trust_suffix, sku_part]
            title = " ".join([p for p in parts if p])
        if len(title) > 120:
            title = f"{prefix} {clean_name} {trust_suffix} {sku_part}".strip()
            if len(title) > 120:
                title = title[:117] + "..."
                
    return title.strip()

SHOPEE_CAT_RULES = [
    # 1. หมวดเครื่องมือไฟฟ้าหลัก (Power Tools)
    (["ฉีดน้ำ", "อัดฉีด"], 101802),                           # เครื่องฉีดน้ำ
    (["เจียร์", "ลูกหมู", "ขัดสี", "ขัดกระดาษทราย", "เครื่องขัด"], 101808),  # เครื่องขัด และอุปกรณ์
    (["เลื่อย", "วงเดือน", "แท่นตัด", "ตัด 14", "ไฟเบอร์ตัด", "จิ๊กซอ", "เลื่อยชัก", "ตัดกระเบื้อง"], 101801), # เครื่องตัด เลื่อย และอุปกรณ์
    (["สว่าน", "โรตารี่", "ไขควง", "สว่านแบต", "ดอกสว่าน", "สว่านแท่น"], 101800),     # สว่าน และอุปกรณ์
    (["ปั๊มลม", "ถังลม"], 101807),                              # เครื่องปั๊มลม และอุปกรณ์
    (["เชื่อม", "บัดกรี", "ลวดเชื่อม", "ตู้เชื่อม"], 101809),       # เครื่องเชื่อม บัดกรี และอุปกรณ์
    (["เป่าลม", "โบลเวอร์", "เป่าฝุ่น"], 101810),                  # เครื่องเป่าลม
    (["เครื่องกำเนิด", "ปั่นไฟ", "เครื่องกำเนิดไฟฟ้า"], 101803),     # เครื่องกำเนิดไฟฟ้า

    # 2. หมวดสวนและเกษตร (Garden)
    (["ตัดหญ้า", "เครื่องตัดหญ้า", "กรรไกรตัดหญ้า", "กรรไกรตัดกิ่ง"], 101185), # สวน/เครื่องตัดหญ้า
    (["ปุ๋ย", "ดิน", "เพาะปลูก"], 101179),
    (["กระถาง", "อุปกรณ์จัดสวน", "หัวรดน้ำ", "สายยาง"], 101183),

    # 3. หมวดระบบน้ำ ปั๊มน้ำ (Plumbing & Pumps)
    (["ปั๊มจุ่ม", "ปั๊มแช่", "ไดโว่", "ปั๊มน้ำ", "สูบน้ำ", "แช่ดูดโคลน", "ปั๊มอัตโนมัติ", "ปั๊มเปลอย"], 101192), # ปั๊มน้ำ ถังน้ำ และอุปกรณ์เสริม

    # 4. หมวดเครื่องมือช่างพื้นฐาน (Hand Tools)
    (["ประแจ", "บล็อก", "ชุดบล็อก", "ด้ามฟรี", "ประแจปอนด์"], 101796), # ประแจ
    (["คีม", "คีมล็อค", "คีมตัด", "คีมปากจิ้งจก", "คีมปากแหลม"], 101798), # คีม
    (["ค้อน", "ค้อนหงอน", "ค้อนปอนด์", "ค้อนยาง"], 101797),     # ค้อน
    (["ตลับเมตร", "สายวัด", "ไม้บรรทัด"], 101795),                # ตลับเมตรและสายวัด
    (["ระดับน้ำ", "เลเซอร์วัด", "วัดระดับ", "เครื่องวัดระยะ", "เวอร์เนีย"], 101805), # เครื่องมือวัด และระดับวัด
    (["กล่องเครื่องมือ", "กระเป๋าเครื่องมือ", "แผงเครื่องมือ"], 101794), # กล่องเครื่องมือช่าง
    (["ตะปู", "สกรู", "พุก", "น็อต", "ตัวยึด", "รีเวท"], 101799),   # ตะปู สกรู และตัวยึด
    (["มิเตอร์", "มัลติมิเตอร์", "เช็คไฟ", "วัดไฟ"], 101804),      # เครื่องทดสอบไฟฟ้า

    # 5. หมวดงานช่างทั่วไป ปรับปรุงบ้าน และเซฟตี้ (Home Improvement & Safety)
    (["บันได", "บันไดช่าง", "บันไดอลูมิเนียม"], 101194),          # บันได
    (["รถเข็น", "ล้อรถเข็น"], 101195),                          # รถเข็น
    (["ถุงมือ", "หน้ากาก", "แว่นตานิรภัย", "รองเท้าเซฟตี้", "หมวกนิรภัย"], 101187), # ถุงมือและหน้ากาก
    (["เทป", "กาว", "ซิลิโคน", "กาวตะปู", "กาวช้าง"], 101186),      # เทปและกาว
    (["สี", "แปรงทาสี", "ลูกกลิ้ง", "ทินเนอร์"], 101190),          # สีและอุปกรณ์ทาสี
    (["แม่แรง", "ยกรถ", "ประแจถอดล้อ"], 102511),                 # เครื่องมือช่างยานยนต์
]

def detect_shopee_category(raw_name: str, brand: str = "") -> int:
    name_l = (raw_name or "").lower()
    for triggers, cat_id in SHOPEE_CAT_RULES:
        if any(t in name_l for t in triggers):
            return cat_id
    if (brand or "").upper() == "3M":
        return 101186
    # Fallback to general tools category (เครื่องมือช่าง/อื่นๆ) so it never mistags as drill
    return 101811

def auto_clean_option_name(raw_name: str, sku: str = "", brand: str = "") -> str:
    name = (raw_name or "").strip()
    if brand:
        name = re.sub(rf"^\[?{re.escape(brand)}\]?\s*", "", name, flags=re.IGNORECASE).strip()
    name = re.sub(r"\[.*?\]", "", name).strip()
    
    # Try finding model code
    model_match = re.match(r"^([A-Za-z0-9\-_/]+(?:\s*[0-9]+[A-Za-z0-9\-]*)?)", name)
    model = model_match.group(1).strip() if model_match else ""
    
    spec = ""
    bar_m = re.search(r"(\d+)\s*(?:bar|บาร์)", name, re.IGNORECASE)
    watt_m = re.search(r"(\d+)\s*(?:w|วัตต์)", name, re.IGNORECASE)
    inch_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:นิ้ว|\"|'')", name)
    stroke_m = re.search(r"([24]\s*จังหวะ)", name)
    
    if bar_m:
        spec = f"{bar_m.group(1)}บาร์"
    elif watt_m:
        spec = f"{watt_m.group(1)}W"
    elif inch_m:
        spec = f"{inch_m.group(1)}นิ้ว"
    elif stroke_m:
        spec = stroke_m.group(1).replace(" ", "")
        
    candidate = ""
    if model and spec:
        candidate = f"{model} ({spec})"
        if len(candidate) > 20:
            candidate = f"{model}({spec})"
    elif model:
        candidate = model
    else:
        clean_sku = sku.split("-")[-1] if "-" in sku else sku
        candidate = f"รุ่น {clean_sku}" if clean_sku else name
        
    if len(candidate) > 20:
        candidate = candidate[:20]
    return candidate.strip()
