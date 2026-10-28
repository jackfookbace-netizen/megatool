import os
import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from app.image_service import load_font, trim_white_space, upload_to_cdn

CANVAS_SIZE = 1200
RED = (239, 28, 37, 255)
DARK_RED = (185, 28, 28, 255)
WHITE = (255, 255, 255, 255)
SLATE_DARK = (15, 23, 42, 255)
SLATE_MUTED = (71, 85, 105, 255)
TEAL_MAKITA = (0, 137, 150, 255)
TEAL_LIGHT = (240, 253, 250, 255)
GOLD = (234, 179, 8, 255)
BG_GRAY = (248, 250, 252, 255)

canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), WHITE)
draw = ImageDraw.Draw(canvas)

# Fonts
f_makita = load_font("arialbd.ttf", 46)
f_h1 = load_font("leelawdb.ttf", 34)
f_sub = load_font("leelawdb.ttf", 20)
f_tag = load_font("leelawdb.ttf", 18)
f_model = load_font("leelawdb.ttf", 32)
f_badge = load_font("leelawdb.ttf", 20)
f_bold = load_font("leelawdb.ttf", 22)
f_body = load_font("leelawdb.ttf", 19)
f_spec_lbl = load_font("leelawdb.ttf", 17)
f_spec_val = load_font("tahomabd.ttf", 21)
f_footer = load_font("leelawdb.ttf", 21)
f_pill = load_font("leelawdb.ttf", 16)
f_logo_prefix = load_font("arialbd.ttf", 44)
f_logo_tool = load_font("ariblk.ttf", 44)

# 1. Header Area (y: 30 to 142)
# Draw NEW badge
draw.rounded_rectangle([36, 32, 115, 68], radius=8, fill=RED)
draw.text((45, 37), "NEW", font=load_font("arialbd.ttf", 24), fill=WHITE)

# Draw Makita text in Makita teal
draw.text((128, 28), "Makita", font=f_makita, fill=TEAL_MAKITA)
draw.text((290, 34), "เครื่องเจียร์ 4\" (540W)", font=f_h1, fill=SLATE_DARK)

# Sub banner: "รุ่นใหม่! ประหยัด ทนทาน ประสิทธิภาพสูง คุ้มค่าเกินราคา"
draw.rounded_rectangle([36, 80, 680, 134], radius=12, fill=(241, 245, 249, 255), outline=(203, 213, 225, 255), width=1)
draw.text((50, 85), "🔥 รุ่นใหม่ล่าสุด! ประหยัด ทนทาน ประสิทธิภาพสูง", font=f_bold, fill=DARK_RED)
draw.text((50, 110), "มอเตอร์ทองแดงแท้ 100% ทรงพลัง แข็งแรง ทนงานหนักต่อเนื่อง", font=f_body, fill=SLATE_MUTED)

# MEGATOOL Logo at top right
part_prefix = "MEGA"
part_tool = "TOOL"
w_pre = draw.textbbox((0, 0), part_prefix, font=f_logo_prefix)[2]
w_tool = draw.textbbox((0, 0), part_tool, font=f_logo_tool)[2]
logo_total = w_pre + w_tool + 8
x_logo_start = 1164 - logo_total
draw.text((x_logo_start, 35), part_prefix, fill=RED, font=f_logo_prefix)
draw.text((x_logo_start + w_pre + 4, 35), part_tool, fill=RED, font=f_logo_tool)

# "ของแท้ 100% ประกันศูนย์ 6 เดือน" under logo
draw.rounded_rectangle([1164 - 280, 92, 1164, 132], radius=8, fill=(254, 242, 242, 255), outline=(254, 202, 202, 255), width=1)
draw.text((1164 - 270, 99), "🛡️ ของแท้ 100% ประกันศูนย์ KTW", font=load_font("leelawdb.ttf", 17), fill=DARK_RED)

# 2. Main Two Column Cards (y: 148 to 915)
card_w = 552
card_h = 760
left_x = 36
right_x = 612
card_top = 148

# Helper to load and trim product image
im0_raw = Image.open('temp_m0900_1.jpg').convert('RGBA')
im0_trimmed = trim_white_space(im0_raw)

im1_raw = Image.open('temp_m0910_1.jpg').convert('RGBA')
im1_trimmed = trim_white_space(im1_raw)

# Switch crops
sw0 = Image.open('switch_m0900_crop.jpg').convert('RGBA')
sw1 = Image.open('switch_m0910_exact.jpg').convert('RGBA')

# Function to draw each card
def draw_card(cx, model_code, switch_type, switch_sub, switch_bg, switch_fg, badge_text, img_obj, switch_crop, switch_label, reco_text, is_slide=True):
    # Card outer
    draw.rounded_rectangle([cx, card_top, cx + card_w, card_top + card_h], radius=18, fill=WHITE, outline=(226, 232, 240, 255), width=2)

    # Card Header
    hdr_h = 88
    draw.rounded_rectangle([cx, card_top, cx + card_w, card_top + hdr_h], radius=18, fill=SLATE_DARK)
    draw.rectangle([cx, card_top + hdr_h - 18, cx + card_w, card_top + hdr_h], fill=SLATE_DARK)

    # Model Title
    draw.text((cx + 18, card_top + 12), model_code, font=f_model, fill=WHITE)
    
    # Switch Badge
    sb_box = draw.textbbox((0, 0), switch_type, font=f_badge)
    sb_w = sb_box[2] - sb_box[0] + 20
    sb_x1 = cx + card_w - 18 - sb_w
    draw.rounded_rectangle([sb_x1, card_top + 12, cx + card_w - 18, card_top + 46], radius=8, fill=switch_bg)
    draw.text((sb_x1 + 10, card_top + 16), switch_type, font=f_badge, fill=switch_fg)

    # Subtitle under model
    draw.text((cx + 18, card_top + 52), switch_sub, font=f_sub, fill=(203, 213, 225, 255))

    # Product Image Box
    p_box = [cx + 16, card_top + 98, cx + card_w - 16, card_top + 390]
    draw.rounded_rectangle(p_box, radius=12, fill=(255, 255, 255, 255), outline=(241, 245, 249, 255), width=1)
    
    # Resize and paste product image
    avail_w = p_box[2] - p_box[0] - 20
    avail_h = p_box[3] - p_box[1] - 20
    iw, ih = img_obj.size
    scale = min(avail_w / iw, avail_h / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    resized_im = img_obj.resize((nw, nh), Image.Resampling.LANCZOS)
    px = p_box[0] + (p_box[2] - p_box[0] - nw) // 2
    py = p_box[1] + (p_box[3] - p_box[1] - nh) // 2
    canvas.paste(resized_im, (px, py), resized_im)

    # Inset Switch Close-up Callout
    # Circle callout on bottom-right of image
    ins_size = 135
    ins_x = cx + card_w - 16 - ins_size - 10
    ins_y = card_top + 390 - ins_size - 10

    # Draw callout container
    draw.rounded_rectangle([ins_x - 3, ins_y - 3, ins_x + ins_size + 3, ins_y + ins_size + 24], radius=14, fill=WHITE, outline=RED, width=3)
    
    # Resize switch crop
    sw_fit = switch_crop.resize((ins_size, ins_size), Image.Resampling.LANCZOS)
    canvas.paste(sw_fit, (ins_x, ins_y))
    
    # Callout label pill below crop
    draw.rounded_rectangle([ins_x, ins_y + ins_size - 4, ins_x + ins_size, ins_y + ins_size + 22], radius=6, fill=RED)
    sl_w = draw.textbbox((0, 0), switch_label, font=f_pill)[2]
    draw.text((ins_x + (ins_size - sl_w) // 2, ins_y + ins_size + 1), switch_label, font=f_pill, fill=WHITE)

    # Pointer line connecting switch callout to machine
    if is_slide:
        # pointer to slide switch
        draw.line([(ins_x, ins_y + 40), (px + int(nw * 0.42), py + int(nh * 0.45))], fill=RED, width=3)
        draw.ellipse([px + int(nw * 0.42) - 5, py + int(nh * 0.45) - 5, px + int(nw * 0.42) + 5, py + int(nh * 0.45) + 5], fill=RED)
    else:
        # pointer to tail switch
        draw.line([(ins_x, ins_y + 40), (px + int(nw * 0.78), py + int(nh * 0.52))], fill=RED, width=3)
        draw.ellipse([px + int(nw * 0.78) - 5, py + int(nh * 0.52) - 5, px + int(nw * 0.78) + 5, py + int(nh * 0.52) + 5], fill=RED)

    # Specs Grid Box (y: 405 to 640)
    spec_top = card_top + 405
    draw.rounded_rectangle([cx + 16, spec_top, cx + card_w - 16, spec_top + 235], radius=14, fill=BG_GRAY, outline=(226, 232, 240, 255), width=1)

    # Spec rows
    specs = [
        ("⚡ กำลังไฟฟ้าเข้า (Power)", "540 W (วัตต์แท้)"),
        ("💿 เส้นผ่านศูนย์กลางใบตัด", "100 มม. (4 นิ้ว)"),
        ("⚙️ ความเร็วรอบตัวเปล่า", "12,000 RPM (รอบ/นาที)"),
        ("⚖️ น้ำหนักตัวเครื่องสุทธิ", "1.6 กก. (เบาพิเศษ คล่องมือ)"),
        ("🔌 รูปแบบการเปิด-ปิด", switch_type)
    ]
    
    curr_sy = spec_top + 10
    for idx, (lbl, val) in enumerate(specs):
        # alternating zebra rows
        if idx % 2 == 1:
            draw.rounded_rectangle([cx + 20, curr_sy - 2, cx + card_w - 20, curr_sy + 36], radius=6, fill=(241, 245, 249, 255))
        draw.text((cx + 28, curr_sy + 4), lbl, font=f_spec_lbl, fill=SLATE_DARK)
        
        val_w = draw.textbbox((0, 0), val, font=f_spec_val)[2]
        val_color = RED if idx == 4 else SLATE_DARK
        draw.text((cx + card_w - 28 - val_w, curr_sy + 4), val, font=f_spec_val, fill=val_color)
        curr_sy += 44

    # Recommendation Box at bottom of card (y: 652 to 745)
    reco_y = card_top + 652
    draw.rounded_rectangle([cx + 16, reco_y, cx + card_w - 16, reco_y + 92], radius=12, fill=(238, 242, 255, 255), outline=(199, 210, 254, 255), width=1)
    draw.text((cx + 26, reco_y + 10), "💡 คำแนะนำการเลือกใช้งาน:", font=f_bold, fill=(67, 56, 202, 255))
    draw.text((cx + 26, reco_y + 38), reco_text[0], font=f_body, fill=SLATE_DARK)
    draw.text((cx + 26, reco_y + 64), reco_text[1], font=f_body, fill=SLATE_DARK)

# Draw Left Card: M0900B
draw_card(
    cx=left_x,
    model_code="รุ่น M0900B",
    switch_type="สวิตช์สไลด์ (ข้างตัว)",
    switch_sub="สวิตช์อยู่ด้านข้าง เปิด-ปิดง่าย สะดวกรวดเร็ว",
    switch_bg=(254, 240, 138, 255),
    switch_fg=(133, 77, 14, 255),
    badge_text="ยอดนิยม",
    img_obj=im0_trimmed,
    switch_crop=sw0,
    switch_label="สวิตช์สไลด์ด้านข้าง",
    reco_text=[
        "• เหมาะสำหรับ: ผู้ที่ต้องการความคล่องตัวสูง",
        "• ใช้งานมือเดียวสะดวก เปิด-ปิดได้ทันใจขณะทำงาน"
    ],
    is_slide=True
)

# Draw Right Card: M0910B
draw_card(
    cx=right_x,
    model_code="รุ่น M0910B",
    switch_type="สวิตช์ท้าย (ก้นเครื่อง)",
    switch_sub="สวิตช์อยู่ท้ายตัวเครื่อง ปลอดภัยสูงสุด",
    switch_bg=(207, 250, 254, 255),
    switch_fg=(14, 116, 144, 255),
    badge_text="เน้นปลอดภัย",
    img_obj=im1_trimmed,
    switch_crop=sw1,
    switch_label="สวิตช์ท้าย เปิด-ปิด",
    reco_text=[
        "• เหมาะสำหรับ: งานที่เน้นความปลอดภัยเป็นหลัก",
        "• สวิตช์อยู่ท้ายเครื่อง ป้องกันมือเผลอโดนสวิตช์ขณะเจียร์"
    ],
    is_slide=False
)

# 3. Bottom Decision Summary & Selling Banner (y: 924 to 1164)
# Decision Banner Box (y: 924 to 1045)
draw.rounded_rectangle([36, 924, 1164, 1040], radius=16, fill=SLATE_DARK)

# Red accent left bar
draw.rounded_rectangle([36, 924, 56, 1040], radius=16, fill=RED)
draw.rectangle([46, 924, 56, 1040], fill=RED)

draw.text((75, 936), "🎯 สรุปความต่าง: สเปกแรงเท่ากัน 540W เต็ม ใบ 4 นิ้ว 12,000 รอบ/นาที", font=load_font("leelawdb.ttf", 25), fill=GOLD)
draw.text((75, 972), "👉 ต่างกันเพียง 'ตำแหน่งสวิตช์': ชอบเปิดปิดคล่องตัวเลือก M0900B | เน้นความปลอดภัยสูงสุดเลือก M0910B", font=f_bold, fill=WHITE)
draw.text((75, 1006), "ทั้ง 2 รุ่นผลิตจากโรงงานมาตรฐาน MAKITA รับประกันศูนย์ 6 เดือนเต็ม พร้อมบริการหลังการขายครบวงจร", font=f_body, fill=(203, 213, 225, 255))

# Footer Guarantee Ribbon (y: 1055 to 1162)
draw.rounded_rectangle([36, 1055, 1164, 1162], radius=16, fill=RED)

guarantees = [
    ("🛡️ มอเตอร์แท้ 100%", "รับประกันศูนย์ 6 เดือน"),
    ("🚚 สต็อกแน่น", "จัดส่งด่วนทุกวันทั่วไทย"),
    ("🔍 QC ก่อนส่ง", "ตรวจเช็คเครื่อง 100%"),
    ("🧾 ออกใบกำกับภาษี", "ราคารวม VAT ถูกต้อง")
]

col_w = (1164 - 36) // 4
for idx, (title, sub) in enumerate(guarantees):
    gx = 36 + (idx * col_w)
    if idx > 0:
        draw.line([(gx, 1070), (gx, 1145)], fill=(255, 255, 255, 100), width=2)
    
    t_w = draw.textbbox((0, 0), title, font=load_font("leelawdb.ttf", 23))[2]
    s_w = draw.textbbox((0, 0), sub, font=load_font("leelawdb.ttf", 17))[2]
    
    tx = gx + (col_w - t_w) // 2
    sx = gx + (col_w - s_w) // 2
    
    draw.text((tx, 1072), title, font=load_font("leelawdb.ttf", 23), fill=WHITE)
    draw.text((sx, 1108), sub, font=load_font("leelawdb.ttf", 17), fill=(254, 240, 138, 255))

# 4. Outer Red Border (Frames the entire 1200x1200 canvas)
border_w = 20
draw.rectangle([(0, 0), (CANVAS_SIZE - 1, CANVAS_SIZE - 1)], outline=RED, width=border_w)

output_path = "app/static/covers/makita_marketing_hero_comparison.jpg"
os.makedirs(os.path.dirname(output_path), exist_ok=True)
canvas.convert("RGB").save(output_path, "JPEG", quality=96)
print("Marketing Hero Comparison Card generated successfully:", output_path)

# Upload to CDN
cdn_url = upload_to_cdn(output_path, force=True)
print("CDN URL:", cdn_url)
