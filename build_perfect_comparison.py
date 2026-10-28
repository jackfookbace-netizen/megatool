import os
from PIL import Image, ImageDraw, ImageFont
from app.image_service import load_font, trim_white_space, upload_to_cdn

CANVAS_SIZE = 1200
WHITE = (255, 255, 255, 255)
SLATE_DARK = (15, 23, 42, 255)
SLATE_TEXT = (30, 41, 59, 255)
SLATE_MUTED = (100, 116, 139, 255)
RED = (220, 38, 38, 255)
DARK_RED = (185, 28, 28, 255)
TEAL_MAKITA = (0, 137, 150, 255)
AMBER_BG = (217, 119, 6, 255)
AMBER_LIGHT = (254, 243, 199, 255)
CYAN_BG = (2, 132, 199, 255)
CYAN_LIGHT = (224, 242, 254, 255)
CARD_BG = (248, 250, 252, 255)
BORDER_GRAY = (226, 232, 240, 255)

canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), WHITE)
draw = ImageDraw.Draw(canvas)

# Fonts (NO EMOJIS! ONLY CLEAN THAI AND ENGLISH FONTS)
f_makita = load_font("arialbd.ttf", 52)
f_new = load_font("arialbd.ttf", 26)
f_tagline = load_font("leelawdb.ttf", 28)
f_sub = load_font("leelawdb.ttf", 21)
f_card_title = load_font("leelawdb.ttf", 36)
f_card_sub = load_font("leelawdb.ttf", 19)
f_badge = load_font("leelawdb.ttf", 22)
f_callout = load_font("leelawdb.ttf", 18)
f_spec_lbl = load_font("leelawdb.ttf", 19)
f_spec_val = load_font("tahomabd.ttf", 19)
f_reco_title = load_font("leelawdb.ttf", 21)
f_reco_txt = load_font("leelawdb.ttf", 19)
f_guide_title = load_font("leelawdb.ttf", 23)
f_guide_txt = load_font("leelawdb.ttf", 20)
f_trust = load_font("leelawdb.ttf", 20)

# -------------------------------------------------------------
# 1. HEADER (y: 24 to 125) - ABSOLUTELY NO MEGATOOL LOGO
# -------------------------------------------------------------
# Red [ NEW ] Badge
draw.rounded_rectangle([36, 28, 125, 68], radius=10, fill=RED)
draw.text((47, 34), "NEW", font=f_new, fill=WHITE)

# Makita Logo text
draw.text((140, 22), "Makita", font=f_makita, fill=TEAL_MAKITA)

# Top Right Catchy Tagline Box
hdr_box = [330, 24, 1164, 74]
draw.rounded_rectangle(hdr_box, radius=12, fill=(240, 253, 250, 255), outline=TEAL_MAKITA, width=2)
draw.text((350, 32), "รุ่นใหม่! ประหยัด ทนทาน ประสิทธิภาพสูง", font=f_tagline, fill=TEAL_MAKITA)

# Subtitle line under brand
draw.text((36, 84), "เครื่องเจียร์ไฟฟ้า 4 นิ้ว (540 วัตต์) แท้ศูนย์ 100% | เปรียบเทียบชัด 2 รุ่นยอดนิยม ต่างกันที่ตำแหน่งสวิตช์", font=f_sub, fill=SLATE_MUTED)

# Dividing line below header
draw.line([(36, 122), (1164, 122)], fill=BORDER_GRAY, width=2)

# -------------------------------------------------------------
# 2. TWO COMPARISON CARDS (y: 135 to 920)
# -------------------------------------------------------------
card_w = 552
card_h = 780
card_top = 135
left_x = 36
right_x = 612

art_dir = r"C:\Users\apisit\.gemini\antigravity\brain\4503571c-f901-4482-b8c6-178ffafb101a"

# Load real high-res images
im0_raw = Image.open(os.path.join(art_dir, "m0900_1.jpg")).convert("RGBA")
im0_trimmed = trim_white_space(im0_raw)

im1_raw = Image.open(os.path.join(art_dir, "m0910_1.jpg")).convert("RGBA")
im1_trimmed = trim_white_space(im1_raw)

# Real switch crops
# For M0910B: real tail switch photo from official flyer
sw1_real = Image.open(os.path.join(art_dir, "exact_switch_m0910.png")).convert("RGBA")
# For M0900B: exact slide switch crop from tool body
sw0_real = Image.open("exact_switch_m0900_perfect.png").convert("RGBA")

# ================= LEFT CARD: M0900B (สวิตช์ข้าง) =================
cx = left_x
# Card Outer Border
draw.rounded_rectangle([cx, card_top, cx + card_w, card_top + card_h], radius=18, fill=WHITE, outline=BORDER_GRAY, width=2)

# Card Header Bar (Dark slate with amber badge)
hdr_h = 88
draw.rounded_rectangle([cx, card_top, cx + card_w, card_top + hdr_h], radius=18, fill=SLATE_DARK)
draw.rectangle([cx, card_top + hdr_h - 18, cx + card_w, card_top + hdr_h], fill=SLATE_DARK)

draw.text((cx + 18, card_top + 12), "รุ่น M0900B", font=f_card_title, fill=WHITE)
draw.rounded_rectangle([cx + card_w - 186, card_top + 14, cx + card_w - 16, card_top + 50], radius=8, fill=AMBER_BG)
draw.text((cx + card_w - 176, card_top + 19), "สวิตช์สไลด์ (ข้าง)", font=f_badge, fill=WHITE)
draw.text((cx + 18, card_top + 54), "สวิตช์อยู่ด้านข้างตัวเครื่อง เปิด-ปิดคล่องตัวด้วยมือเดียว", font=f_card_sub, fill=(203, 213, 225, 255))

# Photo Box
p_box = [cx + 14, card_top + 98, cx + card_w - 14, card_top + 410]
draw.rounded_rectangle(p_box, radius=14, fill=WHITE)

# Paste M0900B tool image
avail_w = p_box[2] - p_box[0] - 140
avail_h = p_box[3] - p_box[1] - 40
iw, ih = im0_trimmed.size
scale0 = min(avail_w / iw, avail_h / ih)
nw0, nh0 = int(iw * scale0), int(ih * scale0)
im0_resized = im0_trimmed.resize((nw0, nh0), Image.Resampling.LANCZOS)
px0 = p_box[0] + 10
py0 = p_box[1] + (p_box[3] - p_box[1] - nh0) // 2
canvas.paste(im0_resized, (px0, py0), im0_resized)

# M0900B Switch Inset Photo Box (Top-Right of card photo area)
ins_w = 136
ins_h = 156
ins_x0 = cx + card_w - ins_w - 20
ins_y0 = card_top + 108

# Inset container
draw.rounded_rectangle([ins_x0 - 2, ins_y0 - 2, ins_x0 + ins_w + 2, ins_y0 + ins_h + 2], radius=12, fill=WHITE, outline=AMBER_BG, width=2)
sw0_resized = sw0_real.resize((ins_w, ins_h - 32), Image.Resampling.LANCZOS)
canvas.paste(sw0_resized, (ins_x0, ins_y0))

# Badge banner under M0900 switch inset
draw.rounded_rectangle([ins_x0, ins_y0 + ins_h - 30, ins_x0 + ins_w, ins_y0 + ins_h], radius=6, fill=AMBER_BG)
draw.text((ins_x0 + 12, ins_y0 + ins_h - 26), "สวิตช์สไลด์ ข้าง", font=load_font("leelawdb.ttf", 16), fill=WHITE)

# Pointer from switch on tool body to inset box
# Calibrated exact slide switch knob position:
dot0_x = px0 + int(nw0 * 0.48)
dot0_y = py0 + int(nh0 * 0.23)
draw.line([(dot0_x, dot0_y), (ins_x0, ins_y0 + 70)], fill=AMBER_BG, width=3)
draw.ellipse([dot0_x - 6, dot0_y - 6, dot0_x + 6, dot0_y + 6], fill=AMBER_BG, outline=WHITE, width=2)

# M0900B Spec Table (Clean 5 Rows with colored vector bullets)
tbl_top = card_top + 420
draw.rounded_rectangle([cx + 14, tbl_top, cx + card_w - 14, tbl_top + 230], radius=14, fill=CARD_BG, outline=BORDER_GRAY, width=1)

specs_m0900 = [
    ("กำลังไฟฟ้าเข้า", "540 W (วัตต์แท้)"),
    ("เส้นผ่านศูนย์กลางใบตัด", "100 มม. (4 นิ้ว)"),
    ("ความเร็วรอบตัวเปล่า", "12,000 RPM (รอบ/นาที)"),
    ("น้ำหนักตัวเครื่องสุทธิ", "1.6 กก. (น้ำหนักเบา)"),
    ("ตำแหน่งสวิตช์เปิด-ปิด", "สวิตช์สไลด์ด้านข้าง")
]

sy = tbl_top + 10
for i, (lbl, val) in enumerate(specs_m0900):
    if i % 2 == 1:
        draw.rounded_rectangle([cx + 18, sy - 2, cx + card_w - 18, sy + 38], radius=6, fill=(241, 245, 249, 255))
    
    bullet_color = AMBER_BG if i == 4 else TEAL_MAKITA
    draw.ellipse([cx + 26, sy + 12, cx + 34, sy + 20], fill=bullet_color)
    draw.text((cx + 42, sy + 6), lbl, font=f_spec_lbl, fill=SLATE_TEXT)
    
    val_w = draw.textbbox((0, 0), val, font=f_spec_val)[2]
    val_color = DARK_RED if i == 4 else SLATE_DARK
    draw.text((cx + card_w - 26 - val_w, sy + 6), val, font=f_spec_val, fill=val_color)
    sy += 44

# M0900B Recommendation Box
reco_y = card_top + 665
draw.rounded_rectangle([cx + 14, reco_y, cx + card_w - 14, reco_y + 98], radius=12, fill=AMBER_LIGHT, outline=(253, 230, 138, 255), width=2)
draw.rounded_rectangle([cx + 14, reco_y, cx + 22, reco_y + 98], radius=4, fill=AMBER_BG)
draw.text((cx + 32, reco_y + 12), "จุดเด่นและการใช้งาน M0900B:", font=f_reco_title, fill=(180, 83, 9, 255))
draw.text((cx + 32, reco_y + 40), "- สวิตช์อยู่ข้างตัวเครื่อง ใช้นิ้วโป้งเลื่อนเปิด-ปิด ได้ทันที", font=f_reco_txt, fill=SLATE_TEXT)
draw.text((cx + 32, reco_y + 66), "- เหมาะมากสำหรับช่างที่เน้นความคล่องตัว ใช้งานมือเดียวบ่อย", font=f_reco_txt, fill=SLATE_TEXT)


# ================= RIGHT CARD: M0910B (สวิตช์ท้าย) =================
cx = right_x
# Card Outer Border
draw.rounded_rectangle([cx, card_top, cx + card_w, card_top + card_h], radius=18, fill=WHITE, outline=BORDER_GRAY, width=2)

# Card Header Bar (Dark slate with cyan badge)
draw.rounded_rectangle([cx, card_top, cx + card_w, card_top + hdr_h], radius=18, fill=SLATE_DARK)
draw.rectangle([cx, card_top + hdr_h - 18, cx + card_w, card_top + hdr_h], fill=SLATE_DARK)

draw.text((cx + 18, card_top + 12), "รุ่น M0910B", font=f_card_title, fill=WHITE)
draw.rounded_rectangle([cx + card_w - 186, card_top + 14, cx + card_w - 16, card_top + 50], radius=8, fill=CYAN_BG)
draw.text((cx + card_w - 176, card_top + 19), "สวิตช์ท้าย (ก้น)", font=f_badge, fill=WHITE)
draw.text((cx + 18, card_top + 54), "สวิตช์อยู่ท้ายตัวเครื่อง ปลอดภัยสูงสุด มือไม่เผลอโดน", font=f_card_sub, fill=(203, 213, 225, 255))

# Photo Box
p_box = [cx + 14, card_top + 98, cx + card_w - 14, card_top + 410]
draw.rounded_rectangle(p_box, radius=14, fill=WHITE)

# Paste M0910B tool image
avail_w = p_box[2] - p_box[0] - 140
avail_h = p_box[3] - p_box[1] - 40
iw, ih = im1_trimmed.size
scale1 = min(avail_w / iw, avail_h / ih)
nw1, nh1 = int(iw * scale1), int(ih * scale1)
im1_resized = im1_trimmed.resize((nw1, nh1), Image.Resampling.LANCZOS)
px1 = p_box[0] + 10
py1 = p_box[1] + (p_box[3] - p_box[1] - nh1) // 2
canvas.paste(im1_resized, (px1, py1), im1_resized)

# M0910B Switch Inset Photo Box (Top-Right of card photo area)
ins_x1 = cx + card_w - ins_w - 20
ins_y1 = card_top + 108

# Inset container
draw.rounded_rectangle([ins_x1 - 2, ins_y1 - 2, ins_x1 + ins_w + 2, ins_y1 + ins_h + 2], radius=12, fill=WHITE, outline=CYAN_BG, width=2)
sw1_resized = sw1_real.resize((ins_w, ins_h - 32), Image.Resampling.LANCZOS)
canvas.paste(sw1_resized, (ins_x1, ins_y1))

# Badge banner under M0910 switch inset
draw.rounded_rectangle([ins_x1, ins_y1 + ins_h - 30, ins_x1 + ins_w, ins_y1 + ins_h], radius=6, fill=CYAN_BG)
draw.text((ins_x1 + 12, ins_y1 + ins_h - 26), "สวิตช์ท้าย เปิด/ปิด", font=load_font("leelawdb.ttf", 16), fill=WHITE)

# Pointer from tail on tool body to inset box
dot1_x = px1 + int(nw1 * 0.90)
dot1_y = py1 + int(nh1 * 0.62)
draw.line([(dot1_x, dot1_y), (ins_x1, ins_y1 + 70)], fill=CYAN_BG, width=3)
draw.ellipse([dot1_x - 6, dot1_y - 6, dot1_x + 6, dot1_y + 6], fill=CYAN_BG, outline=WHITE, width=2)

# M0910B Spec Table (Clean 5 Rows with colored vector bullets)
draw.rounded_rectangle([cx + 14, tbl_top, cx + card_w - 14, tbl_top + 230], radius=14, fill=CARD_BG, outline=BORDER_GRAY, width=1)

specs_m0910 = [
    ("กำลังไฟฟ้าเข้า", "540 W (วัตต์แท้)"),
    ("เส้นผ่านศูนย์กลางใบตัด", "100 มม. (4 นิ้ว)"),
    ("ความเร็วรอบตัวเปล่า", "12,000 RPM (รอบ/นาที)"),
    ("น้ำหนักตัวเครื่องสุทธิ", "1.6 กก. (น้ำหนักเบา)"),
    ("ตำแหน่งสวิตช์เปิด-ปิด", "สวิตช์เปิด-ปิดท้ายเครื่อง")
]

sy = tbl_top + 10
for i, (lbl, val) in enumerate(specs_m0910):
    if i % 2 == 1:
        draw.rounded_rectangle([cx + 18, sy - 2, cx + card_w - 18, sy + 38], radius=6, fill=(241, 245, 249, 255))
    
    bullet_color = CYAN_BG if i == 4 else TEAL_MAKITA
    draw.ellipse([cx + 26, sy + 12, cx + 34, sy + 20], fill=bullet_color)
    draw.text((cx + 42, sy + 6), lbl, font=f_spec_lbl, fill=SLATE_TEXT)
    
    val_w = draw.textbbox((0, 0), val, font=f_spec_val)[2]
    val_color = DARK_RED if i == 4 else SLATE_DARK
    draw.text((cx + card_w - 26 - val_w, sy + 6), val, font=f_spec_val, fill=val_color)
    sy += 44

# M0910B Recommendation Box
draw.rounded_rectangle([cx + 14, reco_y, cx + card_w - 14, reco_y + 98], radius=12, fill=CYAN_LIGHT, outline=(186, 230, 253, 255), width=2)
draw.rounded_rectangle([cx + 14, reco_y, cx + 22, reco_y + 98], radius=4, fill=CYAN_BG)
draw.text((cx + 32, reco_y + 12), "จุดเด่นและการใช้งาน M0910B:", font=f_reco_title, fill=(3, 105, 161, 255))
draw.text((cx + 32, reco_y + 40), "- สวิตช์อยู่ที่ก้นเครื่อง ปลอดภัยสูง มือไม่เผลอโดนขณะเจียร์", font=f_reco_txt, fill=SLATE_TEXT)
draw.text((cx + 32, reco_y + 66), "- เหมาะสำหรับผู้ที่เน้นความปลอดภัย มั่นใจสวิตช์ไม่ลั่นแน่นอน", font=f_reco_txt, fill=SLATE_TEXT)


# -------------------------------------------------------------
# 3. BOTTOM DECISION GUIDE (y: 930 to 1170)
# -------------------------------------------------------------
guide_y1 = 930
guide_y2 = 1170
draw.rounded_rectangle([36, guide_y1, 1164, guide_y2], radius=16, fill=SLATE_DARK)

# Red accent bar on left
draw.rounded_rectangle([36, guide_y1, 52, guide_y2], radius=16, fill=RED)
draw.rectangle([44, guide_y1, 52, guide_y2], fill=RED)

# Content inside Decision Box (CLEAN TEXT, NO EMOJIS!)
draw.text((70, guide_y1 + 18), "สรุปข้อแนะนำการเลือกซื้อ (สเปก 540W แรงเท่ากัน ต่างแค่ตำแหน่งสวิตช์):", font=f_guide_title, fill=(253, 224, 71, 255))

# Row 1: M0900B
draw.rounded_rectangle([70, guide_y1 + 58, 154, guide_y1 + 92], radius=6, fill=AMBER_BG)
draw.text((78, guide_y1 + 63), " M0900B ", font=load_font("tahomabd.ttf", 18), fill=WHITE)
draw.text((168, guide_y1 + 64), "เลือกตัวนี้ -> ถ้าชอบความสะดวกรวดเร็ว สวิตช์สไลด์ด้านข้าง เลื่อนเปิด-ปิดมือเดียวคล่องตัว", font=f_guide_txt, fill=WHITE)

# Row 2: M0910B
draw.rounded_rectangle([70, guide_y1 + 104, 154, guide_y1 + 138], radius=6, fill=CYAN_BG)
draw.text((78, guide_y1 + 109), " M0910B ", font=load_font("tahomabd.ttf", 18), fill=WHITE)
draw.text((168, guide_y1 + 110), "เลือกตัวนี้ -> ถ้าเน้นความปลอดภัยสูงสุด สวิตช์อยู่ท้ายเครื่อง ป้องกันมือเผลอเปิดสวิตช์", font=f_guide_txt, fill=WHITE)

# Row 3: Trust Bar
draw.line([(70, guide_y1 + 154), (1130, guide_y1 + 154)], fill=(51, 65, 85, 255), width=1)

trust_items = [
    "[ ของแท้ 100% ]",
    "[ รับประกันศูนย์ 6 เดือน ]",
    "[ สต็อกพร้อมส่งทันที ]",
    "[ ออกใบกำกับภาษีได้ ]"
]
tx_curr = 70
for item in trust_items:
    draw.text((tx_curr, guide_y1 + 172), item, font=f_trust, fill=(203, 213, 225, 255))
    tx_curr += 270

out_path = "app/static/covers/makita_marketing_perfect_comparison.jpg"
os.makedirs(os.path.dirname(out_path), exist_ok=True)
canvas.convert("RGB").save(out_path, "JPEG", quality=98)
print("SUCCESS: Generated PERFECT comparison card at:", out_path)

cdn = upload_to_cdn(out_path, force=True)
print("CDN URL:", cdn)
