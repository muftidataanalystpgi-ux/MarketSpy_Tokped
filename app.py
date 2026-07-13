import streamlit as st
import requests
import pandas as pd
import re
import time
import io
import random

# =============================================================================
# CONFIGURATION & HEADER
# =============================================================================
st.set_page_config(page_title="Multi-Marketplace Scraper Engine", layout="wide")
st.title("Multi-Marketplace Market Intelligence Scraper")
st.markdown("Kumpulkan data produk secara *real-time* dari Tokopedia dan Shopee untuk analisis kompetitor.")

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
def parse_terjual(text):
    """Mengonversi teks terjual Tokopedia menjadi angka integer."""
    if not text or text == "-":
        return 0
    text = text.lower().replace('terjual', '').replace('+', '').replace(' ', '').replace('.', '')
    if 'rb' in text:
        res = re.findall(r"(\d+)", text)
        return int(res[0]) * 1000 if res else 0
    res = re.findall(r"(\d+)", text)
    return int(res[0]) if res else 0

def get_rotated_proxy(proxy_settings):
    """Mengambil dan memformat proxy berdasarkan opsi yang dipilih di UI."""
    if not proxy_settings or not proxy_settings.get("use_proxy"):
        return None
        
    if proxy_settings.get("mode") == "Tautan Webshare (Otomatis)":
        try:
            proxy_url_list = "https://proxy.webshare.io/api/v2/proxy/list/download/bpfflnzhzjhbevwpoblyubaevtfhmfqtptyjjaux/-/any/username/direct/-/?plan_id=13791542"
            response_proxy = requests.get(proxy_url_list, timeout=10)
            if response_proxy.status_code == 200:
                proxy_lines = response_proxy.text.strip().split('\n')
                if proxy_lines and proxy_lines[0]:
                    chosen_proxy = random.choice(proxy_lines).strip()
                    # Format Webshare: IP:PORT:USER:PASS
                    ip, port, user, password = chosen_proxy.split(':')
                    proxy_formatted = f"http://{user}:{password}@{ip}:{port}"
                    return {"http": proxy_formatted, "https": proxy_formatted}
        except Exception as e:
            st.warning(f"⚠️ Gagal mengambil proxy dari Webshare Link: {e}. Berjalan tanpa proxy.")
            
    elif proxy_settings.get("mode") == "Input Manual" and proxy_settings.get("address"):
        proxy_url = f"http://{proxy_settings['user']}:{proxy_settings['pass']}@{proxy_settings['address']}" if proxy_settings['user'] else f"http://{proxy_settings['address']}"
        return {"http": proxy_url, "https": proxy_url}
        
    return None

# =============================================================================
# ENGINE 1: TOKOPEDIA SCRAPER
# =============================================================================
def run_tokopedia_scraper(product_list, max_per_item, pmin, category_id, progress_bar, status_text, proxy_settings=None):
    url = "https://gql.tokopedia.com/graphql/SearchProductV5Query"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "x-source": "search"
    }
    
    all_extracted_data = []
    total_items = len(product_list)

    for index, (merk, tipe) in enumerate(product_list):
        progress_percentage = (index + 1) / total_items
        progress_bar.progress(progress_percentage)
        status_text.text(f"💚 Tokopedia - Memproses ({index+1}/{total_items}): {merk} {tipe}...")

        tipe_clean = tipe.lower().replace(merk.lower(), '').strip()
        search_query = f"{merk} {tipe}"

        params = f"device=desktop&source=search&st=product&q={search_query}&rows={max_per_item}&condition=1&pmin={pmin}&sc={category_id}"
        payload = [{
            "operationName": "SearchProductV5Query", 
            "variables": {"params": params}, 
            "query": """query SearchProductV5Query($params: String!) {
                  searchProductV5(params: $params) {
                    data {
                      products {
                        name url rating
                        price { number original discountPercentage }
                        shop { name city tier }
                        freeShipping { url }
                        mediaURL { image }
                        labelGroups { position title }
                      }
                    }
                  }
                }"""
        }]

        max_retries = 3
        response_data = None
        
        for attempt in range(max_retries):
            try:
                # Rotasi proxy aktif setiap kali melakukan percobaan ulang (retry)
                current_proxy = get_rotated_proxy(proxy_settings)
                response = requests.post(url, json=payload, headers=headers, timeout=25, proxies=current_proxy)
                response_data = response.json()[0]['data']['searchProductV5']['data']['products']
                break 
            except Exception as e:
                if attempt < max_retries - 1:
                    status_text.text(f"⚠️ Tokopedia Timeout/Blocked pada '{search_query}'. Mencoba proxy lain ({attempt + 2}/{max_retries})...")
                    time.sleep(4)
                else:
                    st.warning(f"❌ Gagal memproses Tokopedia '{search_query}' setelah {max_retries} kali percobaan.")

        if response_data is None:
            continue

        for p in response_data:
            name_lower = p['name'].lower()
            if merk.lower() not in name_lower or (tipe_clean and tipe_clean.split()[0] not in name_lower):
                continue

            terjual_raw = "-"
            promo_label = "-"
            if p.get('labelGroups'):
                for label in p['labelGroups']:
                    if label['position'] == "ri_product_credibility":
                        terjual_raw = label['title']
                    elif label['position'] in ["promotion_label", "ri_ribbon"]:
                        promo_label = label['title']
            
            parsed_terjual = parse_terjual(terjual_raw)
            
            all_extracted_data.append({
                'Marketplace': 'Tokopedia',
                'Merk Input': merk, 'Tipe Input': tipe, 'Nama Produk': p['name'], 
                'Harga Bersih': p['price']['number'], 'Harga Asli': p['price']['original'], 
                'Diskon %': f"{p['price']['discountPercentage']}%" if p['price']['discountPercentage'] else "0%", 
                'Terjual Parsed': parsed_terjual, 'Rating': p['rating'] or "-", 
                'Nama Toko': p['shop']['name'], 'Lokasi': p['shop']['city'], 
                'Bebas Ongkir': "Ya" if p['freeShipping']['url'] else "Tidak", 
                'URL Produk': p['url']
            })
        
        time.sleep(2)

    return pd.DataFrame(all_extracted_data)

# =============================================================================
# ENGINE 2: SHOPEE SCRAPER
# =============================================================================
def run_shopee_scraper(product_list, max_per_item, pmin, progress_bar, status_text, proxy_settings=None):
    url = "https://shopee.co.id/api/v4/search/search_items"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://shopee.co.id/",
        "X-Requested-With": "XMLHttpRequest"
    }

    all_extracted_data = []
    total_items = len(product_list)

    for index, (merk, tipe) in enumerate(product_list):
        progress_percentage = (index + 1) / total_items
        progress_bar.progress(progress_percentage)
        status_text.text(f"🧡 Shopee - Memproses ({index+1}/{total_items}): {merk} {tipe}...")

        tipe_clean = tipe.lower().replace(merk.lower(), '').strip()
        search_query = f"{merk} {tipe}"
        
        params = {
            "by": "relevancy", "keyword": search_query, "limit": max_per_item,
            "newest": 0, "order": "desc", "page_type": "search",
            "scenario": "PAGE_GLOBAL_SEARCH", "version": "1"
        }

        max_retries = 3
        items = None

        for attempt in range(max_retries):
            try:
                current_proxy = get_rotated_proxy(proxy_settings)
                response = requests.get(url, params=params, headers=headers, timeout=25, proxies=current_proxy)
                items = response.json().get('items', [])
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    status_text.text(f"⚠️ Shopee Timeout/Blocked pada '{search_query}'. Mencoba proxy lain ({attempt + 2}/{max_retries})...")
                    time.sleep(4)
                else:
                    st.warning(f"❌ Gagal memproses Shopee '{search_query}' setelah {max_retries} kali percobaan.")

        if not items:
            continue
            
        for item in items:
            item_basic = item.get('item_basic', {})
            name_lower = item_basic.get('name', '').lower()
            
            if merk.lower() not in name_lower or (tipe_clean and tipe_clean.split()[0] not in name_lower):
                continue
            
            harga_bersih = int(item_basic.get('price') / 100000) if item_basic.get('price') else 0
            harga_asli = int(item_basic.get('price_before_discount') / 100000) if item_basic.get('price_before_discount') else harga_bersih
            
            if harga_bersih < pmin:
                continue

            terjual_parsed = item_basic.get('historical_sold', 0)
            
            all_extracted_data.append({
                'Marketplace': 'Shopee',
                'Merk Input': merk, 'Tipe Input': tipe, 'Nama Produk': item_basic.get('name'),
                'Harga Bersih': harga_bersih, 'Harga Asli': harga_asli,
                'Diskon %': f"{item_basic.get('discount')}%" if item_basic.get('discount') else "0%",
                'Terjual Parsed': terjual_parsed,
                'Rating': round(item_basic.get('item_rating', {}).get('rating_star', 0), 2),
                'Nama Toko': f"Shop ID: {item_basic.get('shopid')}",
                'Lokasi': item_basic.get('shop_location', '-'),
                'Bebas Ongkir': "Ya" if item_basic.get('show_free_shipping') else "Tidak",
                'URL Produk': f"https://shopee.co.id/product/{item_basic.get('shopid')}/{item_basic.get('itemid')}"
            })
        
        time.sleep(3)

    return pd.DataFrame(all_extracted_data)

# =============================================================================
# FRONTEND CONTROL PANEL
# =============================================================================
with st.sidebar:
    st.header("🎯 Target & Parameter")
    target_marketplace = st.selectbox("Pilih Marketplace Target", ["Tokopedia", "Shopee"])
    max_per_item = st.slider("Max Produk per Item", min_value=1, max_value=50, value=15)
    pmin = st.number_input("Harga Minimal (Rp)", min_value=0, value=300000, step=50000)
    
    # Kondisional Parameter Tokopedia
    category_id = 24
    if target_marketplace == "Tokopedia":
        category_id = st.number_input("ID Kategori Tokopedia (sc)", min_value=0, value=24)
        
    # --- PANEL PROXY CONFIG ---
    st.write("---")
    st.header("🌐 Konfigurasi Proxy Cloud")
    use_proxy = st.checkbox("Aktifkan Jalur Proxy (Rekomendasi Cloud)")
    
    proxy_settings = {"use_proxy": use_proxy, "mode": "", "address": "", "user": "", "pass": ""}
    if use_proxy:
        proxy_mode = st.selectbox("Metode Proxy", ["Tautan Webshare (Otomatis)", "Input Manual"])
        proxy_settings["mode"] = proxy_mode
        
        if proxy_mode == "Input Manual":
            proxy_settings["address"] = st.text_input("Host:Port Proxy", placeholder="p.webshare.io:80")
            proxy_settings["user"] = st.text_input("Username Proxy", type="password")
            proxy_settings["pass"] = st.text_input("Password Proxy", type="password")

# Pilihan Mode Input Data
input_mode = st.radio("Pilih Metode Pencarian:", ["Input Manual (Satu per Satu)", "Input Massal (Upload File CSV/Excel)"])
product_list = []

if input_mode == "Input Manual (Satu per Satu)":
    col1, col2 = st.columns(2)
    with col1:
        input_merk = st.text_input("Masukkan Merk", placeholder="Contoh: Samsung")
    with col2:
        input_tipe = st.text_input("Masukkan Tipe", placeholder="Contoh: Galaxy S24")
    if input_merk and input_tipe:
        product_list.append([input_merk.strip(), input_tipe.strip()])
else:
    uploaded_file = st.file_uploader("Upload File Database (.csv / .xlsx)", type=["csv", "xlsx"])
    if uploaded_file is not None:
        try:
            df_input = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
            if 'merk' in df_input.columns and 'tipe' in df_input.columns:
                product_list = df_input[['merk', 'tipe']].dropna().values.tolist()
                st.success(f"File dimuat! Ditemukan **{len(product_list)}** data pencarian.")
            else:
                st.error("Format kolom salah! Harus ada kolom kecil bernama **'merk'** dan **'tipe'**.")
        except Exception as e:
            st.error(f"Gagal membaca file: {e}")

st.write("---")
start_button = st.button("🚀 Mulai Ambil Data & Analisis", type="primary", use_container_width=True)

# =============================================================================
# EXECUTION & RESULTS DISPLAY
# =============================================================================
if start_button:
    if not product_list:
        st.error("Gagal! Belum ada entri pencarian yang sah.")
    else:
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        
        with st.spinner(f"Menghubungkan ke API Worker {target_marketplace}..."):
            if target_marketplace == "Tokopedia":
                df_result = run_tokopedia_scraper(
                    product_list, max_per_item, pmin, category_id, 
                    progress_bar, status_text, proxy_settings=proxy_settings
                )
            elif target_marketplace == "Shopee":
                df_result = run_shopee_scraper(
                    product_list, max_per_item, pmin, 
                    progress_bar, status_text, proxy_settings=proxy_settings
                )
        
        progress_bar.empty()
        status_text.empty()

        if not df_result.empty:
            st.success(f"Analisis Selesai! Berhasil merangkum **{len(df_result)}** entitas produk pasar.")
            st.subheader("📊 Preview Data Hasil Scraping")
            st.dataframe(df_result, use_container_width=True)

            st.write("### ⬇️ Download Database")
            col_dl1, col_dl2 = st.columns(2)
            
            # Export CSV
            csv_buffer = df_result.to_csv(index=False).encode('utf-8')
            col_dl1.download_button(
                label="📁 Unduh File CSV", data=csv_buffer,
                file_name=f"hasil_scraping_{target_marketplace.lower()}.csv",
                mime="text/csv", use_container_width=True
            )
            
            # Export Excel
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df_result.to_excel(writer, index=False, sheet_name='Data Pasar')
            
            col_dl2.download_button(
                label="📄 Unduh File Excel (XLSX)", data=excel_buffer.getvalue(),
                file_name=f"hasil_scraping_{target_marketplace.lower()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        else:
            st.warning("Pencarian selesai tetapi tidak ada produk yang lolos filter validasi/harga.")
