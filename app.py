import streamlit as st
import requests
import pandas as pd
import time
import re
import io

# --- HELPER FUNCTIONS ---
def parse_terjual(text):
    if not text or text == "-": return 0
    text = text.lower().replace('terjual', '').replace('+', '').replace(' ', '').replace('.', '')
    if 'rb' in text:
        res = re.findall(r"(\d+)", text)
        return int(res[0]) * 1000 if res else 0
    res = re.findall(r"(\d+)", text)
    return int(res[0]) if res else 0

def scrape_tokopedia(keywords, limit, min_p, cat_id, min_sold, shop_tier):
    url = "https://gql.tokopedia.com/graphql/SearchProductV5Query"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "x-source": "search"
    }
    
    all_results = []
    progress_bar = st.progress(0)
    
    for idx, keyword in enumerate(keywords):
        st.write(f"🔍 Mencari: **{keyword}**...")
        
        # Params Construction
        shop_filter = f"&shop_tier={shop_tier}" if shop_tier != "All" else ""
        cat_filter = f"&sc={cat_id}" if cat_id else ""
        params = f"device=desktop&source=search&st=product&q={keyword}&rows={limit}&pmin={min_p}{cat_filter}{shop_filter}"

        payload = [{"operationName": "SearchProductV5Query", "variables": {"params": params}, "query": """query SearchProductV5Query($params: String!) {
              searchProductV5(params: $params) {
                data {
                  products {
                    name url rating condition
                    price { number original discountPercentage }
                    shop { name city tier }
                    labelGroups { position title }
                  }
                }
              }
            }"""}]

        try:
            res = requests.post(url, json=payload, headers=headers, timeout=15).json()
            data_obj = res[0].get('data', {}).get('searchProductV5', {}).get('data', {})
            products = data_obj.get('products', []) if data_obj else []

            for p in products:
                terjual_raw = "-"
                if p.get('labelGroups'):
                    for l in p['labelGroups']:
                        if l['position'] == "ri_product_credibility": terjual_raw = l['title']
                
                parsed_sold = parse_terjual(terjual_raw)
                
                # Filter Sisi Client: Min Sold
                if parsed_sold >= min_sold:
                    raw_cond = p.get('condition', 0)
                    all_results.append({
                        "Keyword": keyword,
                        "Nama Produk": p['name'],
                        "Harga": p['price']['number'],
                        "Terjual": terjual_raw,
                        "Rating": p['rating'] or "0",
                        "Kondisi": "Baru" if raw_cond == 1 else "Bekas",
                        "Toko": p['shop']['name'],
                        "Lokasi": p['shop']['city'],
                        "Link": p['url']
                    })
            
            # Progress Update
            progress_bar.progress((idx + 1) / len(keywords))
            time.sleep(2) # Delay anti-bot
            
        except Exception as e:
            st.error(f"Error pada {keyword}: {e}")
            
    return pd.DataFrame(all_results)

# --- STREAMLIT UI ---
st.set_page_config(page_title="MarketSpy Tokopedia", layout="wide")

st.title("MarketSpy: Tokopedia Dashboard Analyzer")
st.markdown("Dashboard analisis pasar untuk riset produk secara massal atau manual.")

# Sidebar Filters
st.sidebar.header("⚙️ Konfigurasi Filter")
cat_id = st.sidebar.text_input("ID Kategori (HP=25, Makanan=58)", value="25")
min_price = st.sidebar.number_input("Harga Minimal (Rp)", value=500000, step=50000)
min_sold = st.sidebar.number_input("Minimal Terjual", value=30, step=5)
limit_per_key = st.sidebar.slider("Hasil per Kata Kunci", 5, 50, 15)
shop_tier = st.sidebar.selectbox("Tipe Toko", ["All", "2"]) # 2 = Official Store

# Tabs for Input
tab1, tab2 = st.tabs(["Massal (CSV)", "⌨️ Manual Input"])

keywords_to_search = []

with tab1:
    uploaded_file = st.file_uploader("Upload CSV (Kolom pertama harus Kata Kunci)", type=["csv"])
    if uploaded_file:
        df_input = pd.read_csv(uploaded_file)
        keywords_to_search = df_input.iloc[:, 0].dropna().tolist()
        st.success(f"Berhasil memuat {len(keywords_to_search)} kata kunci.")

with tab2:
    manual_input = st.text_area("Masukkan Kata Kunci (Satu per baris)", placeholder="Oppo A78\nSamsung A55")
    if manual_input:
        keywords_to_search = manual_input.split('\n')

# Execute Button
if st.button("Mulai Scraping & Analisis"):
    if not keywords_to_search:
        st.warning("Masukkan kata kunci atau unggah file terlebih dahulu!")
    else:
        with st.spinner("Sedang mengambil data dari Tokopedia..."):
            df_final = scrape_tokopedia(keywords_to_search, limit_per_key, min_price, cat_id, min_sold, shop_tier)
            
            if not df_final.empty:
                st.subheader("📊 Hasil Analisis")
                st.dataframe(df_final, use_container_width=True)
                
                # Download Button
                csv_buffer = io.StringIO()
                df_final.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
                st.download_button(
                    label="Unduh Hasil (CSV)",
                    data=csv_buffer.getvalue(),
                    file_name="marketspy_report.csv",
                    mime="text/csv"
                )
            else:
                st.error("Tidak ada produk yang memenuhi kriteria filter.")
