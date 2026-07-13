import streamlit as st
import requests
import pandas as pd
import re
import time
import io

# =============================================================================
# CONFIGURATION & HEADER
# =============================================================================
st.set_page_config(page_title="Tokopedia Scraper Engine", layout="wide")
st.title("Tokopedia Market Intelligence Scraper")
st.markdown("Kumpulkan data produk secara *real-time* berbasis API GraphQL Tokopedia untuk analisis kompetitor.")

# =============================================================================
# HELPER FUNCTIONS & ENGINE
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

def run_tokopedia_scraper(product_list, max_per_item, pmin, category_id, progress_bar, status_text):
    url = "https://gql.tokopedia.com/graphql/SearchProductV5Query"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "x-source": "search"
    }
    
    all_extracted_data = []
    total_items = len(product_list)

    for index, (merk, tipe) in enumerate(product_list):
        # Update UI Progress
        progress_percentage = (index + 1) / total_items
        progress_bar.progress(progress_percentage)
        status_text.text(f" Memproses ({index+1}/{total_items}): {merk} {tipe}...")

        tipe_clean = tipe.lower().replace(merk.lower(), '').strip()
        search_query = f"{merk} {tipe}"

        # API Query Parameters
        params = f"device=desktop&source=search&st=product&q={search_query}&rows={max_per_item}&condition=1&pmin={pmin}&sc={category_id}"

        payload = [{
            "operationName": "SearchProductV5Query", 
            "variables": {"params": params}, 
            "query": """query SearchProductV5Query($params: String!) {
                  searchProductV5(params: $params) {
                    data {
                      products {
                        name
                        url
                        rating
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

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            products = response.json()[0]['data']['searchProductV5']['data']['products']
            
            for p in products:
                name_lower = p['name'].lower()
                
                # Validasi Nama Ketat
                if merk.lower() not in name_lower or (tipe_clean and tipe_clean.split()[0] not in name_lower):
                    continue

                # Identifikasi Label
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
                    'Merk Input': merk, 
                    'Tipe Input': tipe, 
                    'Nama Produk Tokopedia': p['name'], 
                    'Harga Bersih': p['price']['number'], 
                    'Harga Asli': p['price']['original'], 
                    'Diskon %': p['price']['discountPercentage'], 
                    'Terjual Raw': terjual_raw, 
                    'Terjual Parsed': parsed_terjual, 
                    'Rating': p['rating'] or "-", 
                    'Nama Toko': p['shop']['name'], 
                    'Lokasi': p['shop']['city'], 
                    'Shop Tier': p['shop']['tier'], 
                    'Bebas Ongkir': "Ya" if p['freeShipping']['url'] else "Tidak", 
                    'Promo Label': promo_label, 
                    'URL Gambar': p['mediaURL']['image'], 
                    'URL Produk': p['url']
                })
            
            # Delay aman anti-blocking
            time.sleep(3)

        except Exception as e:
            st.warning(f"Gagal memproses query '{search_query}': {e}")
            continue

    return pd.DataFrame(all_extracted_data)

# =============================================================================
# FRONTEND CONTROL PANEL
# =============================================================================
with st.sidebar:
    st.header("⚙️ Pengaturan Parameter")
    max_per_item = st.slider("Max Produk per Item", min_value=1, max_value=50, value=15)
    pmin = st.number_input("Harga Minimal (Rp)", min_value=0, value=300000, step=50000)
    category_id = st.number_input("ID Kategori (sc)", min_value=0, value=24, help="Default 24 biasanya untuk Handphone")

# Pilih Metode Input Data
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
    uploaded_file = st.file_file_uploader("Upload File Database HP (.csv / .xlsx)", type=["csv", "xlsx"])
    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith('.csv'):
                df_input = pd.read_csv(uploaded_file)
            else:
                df_input = pd.read_excel(uploaded_file)
            
            # Validasi kolom wajib ada
            if 'merk' in df_input.columns and 'tipe' in df_input.columns:
                product_list = df_input[['merk', 'tipe']].dropna().values.tolist()
                st.success(f"File berhasil dimuat! Ditemukan **{len(product_list)}** baris data siap diproses.")
            else:
                st.error("Format file salah! Pastikan file memiliki kolom bernama kecil: **'merk'** dan **'tipe'**.")
        except Exception as e:
            st.error(f"Gagal membaca file: {e}")

# Tombol Eksekusi
st.write("---")
start_button = st.button(" Mulai Ambil Data & Analisis", type="primary", use_container_width=True)

# =============================================================================
# EXECUTION & RESULTS DISPLAY
# =============================================================================
if start_button:
    if not product_list:
        st.error("Gagal! Belum ada data pencarian yang dimasukkan atau file belum diunggah.")
    else:
        # Menyiapkan placeholder visual Streamlit
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        
        with st.spinner("Menghubungkan ke API Worker Tokopedia..."):
            df_result = run_tokopedia_scraper(product_list, max_per_item, pmin, category_id, progress_bar, status_text)
        
        # Bersihkan status bar setelah selesai
        progress_bar.empty()
        status_text.empty()

        if not df_result.empty:
            st.success(f"Analisis Selesai! Berhasil merangkum **{len(df_result)}** entitas produk pasar.")
            
            # Tampilkan data pratinjau
            st.subheader("📊 Preview Data Hasil Scraping")
            st.dataframe(df_result, use_container_width=True)

            # --- UTILITY EXPORT BUTTONS ---
            st.write("### ⬇️ Download Database")
            col_dl1, col_dl2 = st.columns(2)
            
            # Export CSV (In-Memory)
            csv_buffer = df_result.to_csv(index=False).encode('utf-8')
            col_dl1.download_button(
                label="Unduh File CSV",
                data=csv_buffer,
                file_name="hasil_scraping_tokopedia.csv",
                mime="text/csv",
                use_container_width=True
            )
            
            # Export Excel (In-Memory Buffer)
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df_result.to_excel(writer, index=False, sheet_name='Data Tokopedia')
            
            col_dl2.download_button(
                label="Unduh File Excel (XLSX)",
                data=excel_buffer.getvalue(),
                file_name="hasil_scraping_tokopedia.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        else:
            st.warning("Pencarian selesai tetapi tidak ada produk yang lolos filter validasi nama.")
