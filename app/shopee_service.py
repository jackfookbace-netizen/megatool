import os
import zipfile
import io
import re
import json
import xml.etree.ElementTree as ET
from app.image_service import generate_cover, upload_to_cdn
from app.ktw_service import get_product_detail, clean_brand_name, detect_brand_from_sku, extract_product_images

TEMPLATE_PATH = 'Shopee_template_original.xlsx'

import concurrent.futures

def clean_html(text):
    if not text:
        return ""
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()

def _process_single_image(raw_img_url, img_idx, sku, brand, badge_text, shop_name):
    local_img_path = f"app/static/covers/{sku}_img_{img_idx}.jpg"
    try:
        generate_cover(
            raw_img_url,
            local_img_path,
            brand=brand,
            sku=sku,
            badge_text=badge_text,
            shop_name=shop_name
        )
        uploaded_cdn = upload_to_cdn(local_img_path)
        if uploaded_cdn and 'ktw.co.th' not in uploaded_cdn and uploaded_cdn.startswith('http'):
            return (img_idx, uploaded_cdn)
    except Exception as e:
        print(f"Error applying template to {sku} image {img_idx}:", e)
    return (img_idx, None)


def export_shopee_batch(product_items, output_filename='Shopee_Batch_Export.xlsx', shop_name='MEGATOOL'):
    """
    Takes product_items: [{'sku': '...', 'price': 145, 'badge': '...'}]
    Generates branded template images for ALL angles, uploads to CDN, and injects into official Shopee template.
    """
    if not os.path.exists(TEMPLATE_PATH):
        raise FileNotFoundError(f"Template {TEMPLATE_PATH} not found")

    with open(TEMPLATE_PATH, 'rb') as f:
        zip_bytes = f.read()

    in_zip = zipfile.ZipFile(io.BytesIO(zip_bytes), 'r')
    ss_bytes = in_zip.read('xl/sharedStrings.xml')
    ss_root = ET.fromstring(ss_bytes)
    ns = {'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

    current_si_count = len(list(ss_root.findall('main:si', ns)))
    existing_map = {}
    for i, si in enumerate(ss_root.findall('main:si', ns)):
        t = si.find('main:t', ns)
        if t is not None and t.text:
            existing_map[t.text] = i

    new_strings = []

    def get_or_add_str(val):
        nonlocal current_si_count
        val_str = str(val) if val is not None else ""
        if val_str in existing_map:
            return existing_map[val_str]
        if val_str in new_strings:
            return current_si_count + new_strings.index(val_str)
            
        new_strings.append(val_str)
        idx = current_si_count + len(new_strings) - 1
        si_elem = ET.Element('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si')
        t_elem = ET.SubElement(si_elem, '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t')
        t_elem.text = val_str
        ss_root.append(si_elem)
        return idx

    # Read sheet2.xml
    s2_bytes = in_zip.read('xl/worksheets/sheet2.xml')
    s2_root = ET.fromstring(s2_bytes)
    sheet_data = s2_root.find('main:sheetData', ns)

    start_row = 7
    current_row_num = start_row
    for item_info in product_items:
        sku = item_info['sku']
        override_price = item_info.get('price')
        badge_text = item_info.get('badge')
        
        detail = get_product_detail(sku)
        if not detail:
            continue
            
        row_elem = ET.Element('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row', {'r': str(current_row_num), 'spans': '1:38'})


        brand = clean_brand_name(detail.get('manufacturer'), sku)
        raw_name = detail.get('name', sku)
        raw_desc = clean_html(detail.get('description', ''))
        ean = detail.get('ean') or ''
        cost_price = detail.get('price', {}).get('value', 0)
        
        # Determine sale price
        if override_price and float(override_price) > 0:
            sale_price = float(override_price)
        else:
            sale_price = round(cost_price * 1.25, 0)
            if sale_price < cost_price + 30:
                sale_price = cost_price + 30

        # Stock
        stock_qty = detail.get('stock', {}).get('stockLevel', 100)
        if stock_qty <= 0:
            stock_qty = 50

        # Weight & Dims
        weight_kg = 1.0
        width_cm = 10.0
        length_cm = 15.0
        height_cm = 10.0
        units = detail.get('conversionUnits', [])
        if units:
            u0 = units[0]
            weight_kg = u0.get('conversionGross', 1.0)
            length_cm = round(u0.get('conversionLength', 150.0) / 10.0, 1)
            width_cm = round(u0.get('conversionWidth', 100.0) / 10.0, 1)
            height_cm = round(u0.get('conversionHeight', 100.0) / 10.0, 1)

        # Collect raw distinct angle images from detail (up to 9 images)
        raw_images = extract_product_images(detail)[:9]

        cdn_results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            future_to_idx = {
                executor.submit(_process_single_image, u, idx, sku, brand, badge_text, shop_name): idx
                for idx, u in enumerate(raw_images)
            }
            for fut in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[fut]
                try:
                    img_idx, cdn_url = fut.result()
                    if cdn_url and 'ktw.co.th' not in cdn_url:
                        cdn_results[img_idx] = cdn_url
                except Exception as e:
                    print(f"Failed processing image {idx} for {sku}:", e)

        # Build ordered list of CDN URLs
        cdn_urls = [cdn_results[i] for i in range(len(raw_images)) if i in cdn_results]

        # If for any reason cover (image 0) is missing, retry synchronously up to 2 times
        if not cdn_urls and raw_images:
            _, fallback_cover = _process_single_image(raw_images[0], 0, sku, brand, badge_text, shop_name)
            if fallback_cover:
                cdn_urls.append(fallback_cover)



        # SEO Title
        shopee_title = f"[{brand} แท้ 100%] {raw_name} รหัส {sku} ของแท้มาตรฐานโรงงาน"
        if len(shopee_title) > 120:
            shopee_title = shopee_title[:117] + "..."

        shopee_desc = f"""[{brand} แท้ 100%] {raw_name}
สินค้าคุณภาพมาตรฐานสากล ส่งตรงจากโรงงานผลิต มั่นใจได้ในของแท้ 100%

【 จุดเด่นและสเปกสินค้า 】
{raw_desc}

【 ข้อมูลจำเพาะ 】
• แบรนด์: {brand}
• รหัสสินค้า (SKU): {sku}
• บาร์โค้ดสากล (EAN): {ean if ean else '-'}

📦 สินค้ามีสต็อกจริงพร้อมส่ง แพ็คห่อแน่นหนาอย่างดี จัดส่งรวดเร็วทุกวันครับ"""

        # Map Category ID: Default tool category 101800 (สว่าน) or 101186 (เทป)
        cat_id = 101186 if brand == '3M' else 101800

        def add_cell_num(col_letter, val):
            c = ET.SubElement(row_elem, '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c', {'r': f"{col_letter}{current_row_num}"})
            v = ET.SubElement(c, '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
            v.text = str(val)

        def add_cell_str(col_letter, val):
            if val is None or val == "":
                return
            s_idx = get_or_add_str(val)
            c = ET.SubElement(row_elem, '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c', {'r': f"{col_letter}{current_row_num}", 't': 's'})
            v = ET.SubElement(c, '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
            v.text = str(s_idx)

        # Populate columns
        add_cell_num('A', cat_id)
        add_cell_str('B', shopee_title)
        add_cell_str('C', shopee_desc)
        add_cell_str('I', sku)
        add_cell_num('P', sale_price)
        add_cell_num('Q', stock_qty)
        add_cell_str('R', sku)
        # Column U (GTIN) is optional - leave empty so Shopee does not trigger strict barcode checksum error
        # add_cell_str('U', ean)

        # Image columns V to AD (Cover + 8 gallery images = 9 slots)
        cols_img = ['V', 'W', 'X', 'Y', 'Z', 'AA', 'AB', 'AC', 'AD']
        for c_idx, col_l in enumerate(cols_img):
            if c_idx < len(cdn_urls):
                add_cell_str(col_l, cdn_urls[c_idx])

        add_cell_num('AE', weight_kg)
        add_cell_num('AF', int(length_cm))
        add_cell_num('AG', int(width_cm))
        add_cell_num('AH', int(height_cm))
        add_cell_str('AI', "เปิด") # Standard delivery (channel_id.7000)
        add_cell_str('AJ', "ปิด")  # Express delivery (channel_id.7002)
        # Column AK is ps_product_pre_order_dts (Leave empty for in-stock products)
        # Column AL is et_title_reason (Leave empty)

        sheet_data.append(row_elem)
        current_row_num += 1

    # Update sharedStrings counts
    total_ss = current_si_count + len(new_strings)
    ss_root.attrib['count'] = str(total_ss)
    ss_root.attrib['uniqueCount'] = str(total_ss)
    new_ss_xml = ET.tostring(ss_root, encoding='utf-8', xml_declaration=True)

    # Update dimension
    last_row = max(start_row, current_row_num - 1)
    dim = s2_root.find('main:dimension', ns)
    if dim is not None:
        dim.attrib['ref'] = f'A1:AL{last_row}'
    new_s2_xml = ET.tostring(s2_root, encoding='utf-8', xml_declaration=True)


    # Repackage zip
    out_io = io.BytesIO()
    out_zip = zipfile.ZipFile(out_io, 'w', compression=zipfile.ZIP_DEFLATED)
    for item in in_zip.infolist():
        if item.filename == 'xl/sharedStrings.xml':
            out_zip.writestr(item, new_ss_xml)
        elif item.filename == 'xl/worksheets/sheet2.xml':
            out_zip.writestr(item, new_s2_xml)
        else:
            out_zip.writestr(item, in_zip.read(item.filename))
    out_zip.close()

    export_path = f"app/static/{output_filename}"
    with open(export_path, 'wb') as f_out:
        f_out.write(out_io.getvalue())

    return f"/static/{output_filename}"
