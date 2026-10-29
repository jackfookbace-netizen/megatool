import os
import zipfile
import io
import re
import json
import xml.etree.ElementTree as ET
from app.image_service import generate_cover, upload_to_cdn
from app.ktw_service import get_product_detail, clean_brand_name, detect_brand_from_sku, extract_product_images

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.dirname(os.path.abspath(__file__))

CANDIDATE_PATHS = [
    os.path.join(APP_DIR, 'Shopee_template_original.xlsx'),
    os.path.join(ROOT_DIR, 'Shopee_template_original.xlsx'),
    'Shopee_template_original.xlsx'
]

TEMPLATE_PATH = CANDIDATE_PATHS[0]
for p in CANDIDATE_PATHS:
    if os.path.exists(p):
        TEMPLATE_PATH = p
        break

import concurrent.futures

def clean_html(text):
    if not text:
        return ""
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()

def _process_single_image(raw_img_url, img_idx, sku, brand, badge_text, shop_name, use_template=True):
    import hashlib
    import requests

    is_already_framed = (
        not use_template or 
        'collage_' in str(raw_img_url) or 
        'comparison_' in str(raw_img_url)
    )

    if is_already_framed:
        # If the file is already a local static file (like /static/covers/collage_...)
        if '/static/covers/' in str(raw_img_url):
            fname = str(raw_img_url).split('/static/covers/')[-1].split('?')[0]
            local_raw_path = f"app/static/covers/{fname}"
            if os.path.exists(local_raw_path):
                uploaded_cdn = upload_to_cdn(local_raw_path)
                if uploaded_cdn and uploaded_cdn.startswith('http'):
                    return (img_idx, uploaded_cdn)
                return (img_idx, f"https://megatool-yrho.onrender.com/static/covers/{fname}")

        url_hash = hashlib.md5(raw_img_url.encode('utf-8')).hexdigest()[:10]
        raw_filename = f"raw_{sku}_{url_hash}.jpg"
        local_raw_path = f"app/static/covers/{raw_filename}"
        try:
            if not os.path.exists(local_raw_path):
                from app.image_service import fetch_image_safe
                im = fetch_image_safe(raw_img_url)
                im.convert('RGB').save(local_raw_path, 'JPEG', quality=95)

            # Tier 1: Cloudflare CDN
            if os.path.exists(local_raw_path):
                uploaded_cdn = upload_to_cdn(local_raw_path)
                if uploaded_cdn and uploaded_cdn.startswith('http'):
                    return (img_idx, uploaded_cdn)

                # Tier 2: Public Render server URL
                render_url = f"https://megatool-yrho.onrender.com/static/covers/{raw_filename}"
                return (img_idx, render_url)
        except Exception as e:
            print(f"Error processing raw/framed image for {sku} {img_idx}:", e)

        # Tier 3: Direct original KTW image URL
        if raw_img_url and raw_img_url.startswith('http'):
            return (img_idx, raw_img_url)
        return (img_idx, None)

    url_hash = hashlib.md5(f"{raw_img_url}_{brand}_{badge_text}_{shop_name}".encode('utf-8')).hexdigest()[:10]
    local_img_path = f"app/static/covers/{sku}_{url_hash}.jpg"
    filename = f"{sku}_{url_hash}.jpg"
    try:
        generate_cover(
            raw_img_url,
            local_img_path,
            brand=brand,
            sku=sku,
            badge_text=badge_text,
            shop_name=shop_name
        )
        # Tier 1: Cloudflare CDN (Freeimage / iili.io)
        uploaded_cdn = upload_to_cdn(local_img_path)
        if uploaded_cdn and uploaded_cdn.startswith('http'):
            return (img_idx, uploaded_cdn)

        # Tier 2: Public Render server URL (branded template cover)
        if os.path.exists(local_img_path):
            render_url = f"https://megatool-yrho.onrender.com/static/covers/{filename}"
            return (img_idx, render_url)
    except Exception as e:
        print(f"Error applying template to {sku} image {img_idx}:", e)

    # Tier 3: Direct original high-res KTW image URL
    if raw_img_url and raw_img_url.startswith('http'):
        return (img_idx, raw_img_url)

    return (img_idx, None)


def col_to_idx(col_str):
    num = 0
    for ch in col_str:
        num = num * 26 + (ord(ch.upper()) - ord('A') + 1)
    return num

def export_shopee_batch(product_items, output_filename='Shopee_Batch_Export.xlsx', shop_name='MEGATOOL', is_variation_group=False, parent_title=None, variation_group_name='รุ่นสินค้า', comparison_card_url=None, include_comparison=True):
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
    if is_variation_group and len(product_items) > 0:
        parent_sku = f"PARENT_{product_items[0]['sku']}"
        group_brand = "GENUINE"
        group_cat_id = 101800
        
        processed_items = []
        all_gallery_images = []
        combined_descs = []

        for item_info in product_items:
            sku = item_info['sku']
            override_price = item_info.get('price')
            badge_text = item_info.get('badge')
            custom_var_name = item_info.get('variation_name')
            
            detail = get_product_detail(sku)
            if not detail:
                continue
                
            brand = clean_brand_name(detail.get('manufacturer'), sku)
            group_brand = brand
            if brand == '3M':
                group_cat_id = 101186
                
            raw_name = detail.get('name', sku)
            raw_desc = clean_html(detail.get('description', ''))
            cost_price = detail.get('price', {}).get('value', 0)
            
            if override_price and float(override_price) > 0:
                sale_price = float(override_price)
            else:
                target_net = max(cost_price * 1.07, cost_price + 30)
                sale_price = round(target_net / (1 - 0.28), 0)
                
            stock_qty = detail.get('stock', {}).get('stockLevel', 100)
            if stock_qty <= 0:
                stock_qty = 50
                
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

            custom_images = item_info.get('selected_images')
            if custom_images and isinstance(custom_images, list) and len(custom_images) > 0:
                raw_images = [u for u in custom_images if u]
            else:
                raw_images = extract_product_images(detail)

            selected_cover = item_info.get('selected_image')
            if selected_cover:
                if selected_cover in raw_images:
                    raw_images.remove(selected_cover)
                raw_images.insert(0, selected_cover)
            raw_images = raw_images[:9]

            use_template = item_info.get('use_template', True)
            unframed_images = set(item_info.get('unframed_images') or [])
            cdn_results = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                future_to_idx = {
                    executor.submit(
                        _process_single_image, 
                        u, 
                        idx, 
                        sku, 
                        brand, 
                        badge_text, 
                        shop_name, 
                        use_template=(use_template and (u not in unframed_images))
                    ): idx
                    for idx, u in enumerate(raw_images)
                }
                for fut in concurrent.futures.as_completed(future_to_idx):
                    idx = future_to_idx[fut]
                    try:
                        img_idx, cdn_url = fut.result()
                        if cdn_url and cdn_url.startswith('http'):
                            cdn_results[img_idx] = cdn_url
                    except Exception as e:
                        print(f"Failed processing image {idx} for {sku}:", e)

            cdn_urls = [cdn_results[i] for i in range(len(raw_images)) if i in cdn_results]
            if not cdn_urls and raw_images:
                cdn_urls = [u for u in raw_images if u and u.startswith('http')]

            var_cover = cdn_urls[0] if cdn_urls else ""
            if var_cover and var_cover not in all_gallery_images:
                all_gallery_images.append(var_cover)

            opt_name = (custom_var_name or "").strip()
            if not opt_name:
                opt_name = raw_name.replace(f"[{brand}]", "").strip()
                if len(opt_name) > 20:
                    opt_name = opt_name[:20]

            combined_descs.append(f"• ตัวเลือก: {opt_name} (รหัส {sku})\n{raw_desc[:200]}...")

            processed_items.append({
                "sku": sku,
                "raw_name": raw_name,
                "brand": brand,
                "sale_price": sale_price,
                "stock_qty": stock_qty,
                "weight_kg": weight_kg,
                "length_cm": length_cm,
                "width_cm": width_cm,
                "height_cm": height_cm,
                "opt_name": opt_name,
                "var_cover": var_cover,
                "cdn_urls": cdn_urls
            })

        if processed_items:
            if parent_title and parent_title.strip():
                final_parent_title = parent_title.strip()
            else:
                first_name = processed_items[0]['raw_name']
                final_parent_title = f"[{group_brand} แท้ 100%] {first_name} รวมรุ่นตัวเลือกสเปก ของแท้มาตรฐานโรงงาน"
            if len(final_parent_title) > 120:
                final_parent_title = final_parent_title[:117] + "..."

            desc_bullet_text = "\n\n".join(combined_descs)
            final_parent_desc = f"""[{group_brand} แท้ 100%] รวมตัวเลือกสินค้าคุณภาพมาตรฐานสากล
สินค้าส่งตรงจากโรงงานผู้ผลิต มั่นใจได้ในคุณภาพของแท้ 100%

【 รายละเอียดตัวเลือกสินค้าในรายการนี้ 】
{desc_bullet_text}

【 ข้อแนะนำการสั่งซื้อ 】
• สามารถกดเลือกตัวเลือกรุ่น/สเปกที่ต้องการได้ที่ปุ่มตัวเลือกสินค้าด้านบน
• สินค้าทุกชิ้นตรวจสอบและแพ็คห่ออย่างดีก่อนจัดส่งทุกวันครับ"""

            final_gallery = all_gallery_images[:9]
            # Inject Comparison Card as Image 2 if enabled and provided/auto-generated
            if include_comparison:
                if comparison_card_url and str(comparison_card_url).startswith('http'):
                    if comparison_card_url in final_gallery:
                        final_gallery.remove(comparison_card_url)
                    if len(final_gallery) > 0:
                        final_gallery.insert(1, comparison_card_url)
                    else:
                        final_gallery.append(comparison_card_url)
                elif is_variation_group and len(processed_items) > 1:
                    try:
                        import hashlib
                        var_skus = "_".join([p['sku'] for p in processed_items])
                        comp_hash = hashlib.md5(f"comp_{var_skus}_v2".encode('utf-8')).hexdigest()[:8]
                        comp_file = f"comparison_{comp_hash}.jpg"
                        comp_local = f"app/static/covers/{comp_file}"
                        from app.image_service import generate_comparison_card
                        generate_comparison_card(processed_items, comp_local, parent_title=final_parent_title, shop_name=shop_name)
                        uploaded_comp = upload_to_cdn(comp_local, force=True)
                        comp_url = uploaded_comp if (uploaded_comp and uploaded_comp.startswith('http')) else f"https://megatool-yrho.onrender.com/static/covers/{comp_file}"
                        if comp_url:
                            if len(final_gallery) > 0:
                                final_gallery.insert(1, comp_url)
                            else:
                                final_gallery.append(comp_url)
                    except Exception as comp_err:
                        print("Auto comparison card generation in batch:", comp_err)

            if len(final_gallery) < 9:
                for p in processed_items:
                    for u in p.get('cdn_urls', []):
                        if u and u not in final_gallery and len(final_gallery) < 9:
                            final_gallery.append(u)
            final_gallery = final_gallery[:9]

            def append_sorted_cells(row_el, cells_d, r_num):
                for col_l in sorted(cells_d.keys(), key=col_to_idx):
                    c_type, val = cells_d[col_l]
                    if val is None or val == "":
                        continue
                    c_node = ET.SubElement(row_el, '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c', {'r': f"{col_l}{r_num}"})
                    if c_type == 's':
                        c_node.attrib['t'] = 's'
                        s_idx = get_or_add_str(val)
                        v_node = ET.SubElement(c_node, '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                        v_node.text = str(s_idx)
                    else:
                        v_node = ET.SubElement(c_node, '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                        v_node.text = str(val)

            clean_var_tier = (variation_group_name or "รุ่นสินค้า").strip()
            if len(clean_var_tier) > 14:
                clean_var_tier = clean_var_tier[:14]

            for idx, p_item in enumerate(processed_items):
                row_elem = ET.Element('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row', {'r': str(current_row_num), 'spans': '1:38'})
                cells = {}

                # Category & Title (Columns A & B): Filled on ALL rows so Shopee never reports empty title
                cells['A'] = ('n', group_cat_id)
                cells['B'] = ('s', final_parent_title)
                cells['C'] = ('s', final_parent_desc)

                # Parent SKU in Column I
                cells['I'] = ('s', parent_sku)
                # Variation Integration No in Column J (Mandatory for Shopee variations!)
                cells['J'] = ('s', "101")
                # Variation Tier 1 Name in Column K (Strictly 1-14 chars limit in Shopee)
                cells['K'] = ('s', clean_var_tier)
                # Option 1 in Column L (Strictly 1-20 chars limit in Shopee)
                clean_opt = (p_item['opt_name'] or "มาตรฐาน").strip()
                if len(clean_opt) > 20:
                    clean_opt = clean_opt[:20]
                cells['L'] = ('s', clean_opt)
                # Option Image in Column M
                if p_item['var_cover']:
                    cells['M'] = ('s', p_item['var_cover'])

                cells['P'] = ('n', p_item['sale_price'])
                cells['Q'] = ('n', p_item['stock_qty'])
                cells['R'] = ('s', p_item['sku'])

                # Main Gallery Images (Columns V to AD): on first row
                if idx == 0:
                    cols_img = ['V', 'W', 'X', 'Y', 'Z', 'AA', 'AB', 'AC', 'AD']
                    for c_idx, col_l in enumerate(cols_img):
                        if c_idx < len(final_gallery):
                            cells[col_l] = ('s', final_gallery[c_idx])

                cells['AE'] = ('n', p_item['weight_kg'])
                cells['AF'] = ('n', int(p_item['length_cm']))
                cells['AG'] = ('n', int(p_item['width_cm']))
                cells['AH'] = ('n', int(p_item['height_cm']))
                cells['AI'] = ('s', "เปิด")
                cells['AJ'] = ('s', "ปิด")

                append_sorted_cells(row_elem, cells, current_row_num)
                sheet_data.append(row_elem)
                current_row_num += 1
    else:
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
        
            # Determine sale price using Shopee Net-Profit formula (Fee: 28%, Margin: 7%, min profit: 30 baht)
            if override_price and float(override_price) > 0:
                sale_price = float(override_price)
            else:
                target_net = max(cost_price * 1.07, cost_price + 30)
                sale_price = round(target_net / (1 - 0.28), 0)

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

            # Collect raw distinct angle images from detail or custom user selection (up to 9 images)
            custom_images = item_info.get('selected_images')
            if custom_images and isinstance(custom_images, list) and len(custom_images) > 0:
                raw_images = [u for u in custom_images if u]
            else:
                raw_images = extract_product_images(detail)

            selected_cover = item_info.get('selected_image')
            if selected_cover:
                if selected_cover in raw_images:
                    raw_images.remove(selected_cover)
                raw_images.insert(0, selected_cover)
            
            raw_images = raw_images[:9]

            use_template = item_info.get('use_template', True)
            unframed_images = set(item_info.get('unframed_images') or [])
            cdn_results = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                future_to_idx = {
                    executor.submit(
                        _process_single_image, 
                        u, 
                        idx, 
                        sku, 
                        brand, 
                        badge_text, 
                        shop_name, 
                        use_template=(use_template and (u not in unframed_images))
                    ): idx
                    for idx, u in enumerate(raw_images)
                }
                for fut in concurrent.futures.as_completed(future_to_idx):
                    idx = future_to_idx[fut]
                    try:
                        img_idx, cdn_url = fut.result()
                        if cdn_url and cdn_url.startswith('http'):
                            cdn_results[img_idx] = cdn_url
                    except Exception as e:
                        print(f"Failed processing image {idx} for {sku}:", e)

            # Build ordered list of CDN URLs
            cdn_urls = [cdn_results[i] for i in range(len(raw_images)) if i in cdn_results]
            if not cdn_urls and raw_images:
                cdn_urls = [u for u in raw_images if u and u.startswith('http')]



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

            cells = {}
            cells['A'] = ('n', cat_id)
            cells['B'] = ('s', shopee_title)
            cells['C'] = ('s', shopee_desc)
            cells['I'] = ('s', sku)
            cells['P'] = ('n', sale_price)
            cells['Q'] = ('n', stock_qty)
            cells['R'] = ('s', sku)

            cols_img = ['V', 'W', 'X', 'Y', 'Z', 'AA', 'AB', 'AC', 'AD']
            for c_idx, col_l in enumerate(cols_img):
                if c_idx < len(cdn_urls):
                    cells[col_l] = ('s', cdn_urls[c_idx])

            cells['AE'] = ('n', weight_kg)
            cells['AF'] = ('n', int(length_cm))
            cells['AG'] = ('n', int(width_cm))
            cells['AH'] = ('n', int(height_cm))
            cells['AI'] = ('s', "เปิด")
            cells['AJ'] = ('s', "ปิด")

            for col_l in sorted(cells.keys(), key=col_to_idx):
                c_type, val = cells[col_l]
                if val is None or val == "":
                    continue
                c_node = ET.SubElement(row_elem, '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c', {'r': f"{col_l}{current_row_num}"})
                if c_type == 's':
                    c_node.attrib['t'] = 's'
                    s_idx = get_or_add_str(val)
                    v_node = ET.SubElement(c_node, '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                    v_node.text = str(s_idx)
                else:
                    v_node = ET.SubElement(c_node, '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                    v_node.text = str(val)

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
