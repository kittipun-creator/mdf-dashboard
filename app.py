import os
import json
import base64
import re
import google.generativeai as genai
import gspread
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="MDF Quality Dashboard", layout="wide")

# ==========================================
# 1. ตั้งค่าการเชื่อมต่อ (Local & Cloud)
# ==========================================
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

def load_gcp_credentials():
    if "GOOGLE_KEY_BASE64" in st.secrets:
        try:
            raw_val = str(st.secrets["GOOGLE_KEY_BASE64"])
            ascii_str = re.sub(r'[^\x00-\x7F]+', '', raw_val).strip('"' + "'" + " \t\n\r")
            
            # ซ่อมแซม Padding (=) อัตโนมัติหากจำนวนตัวอักษรไม่ครบสูตร Base64
            missing_padding = len(ascii_str) % 4
            if missing_padding:
                ascii_str += '=' * (4 - missing_padding)

            json_bytes = base64.b64decode(ascii_str)
            creds_dict = json.loads(json_bytes.decode("utf-8"))
            return Credentials.from_service_account_info(creds_dict, scopes=scopes)
        except Exception as e:
            st.error(f"❌ อ่าน GOOGLE_KEY_BASE64 ไม่สำเร็จ: {e}")
            st.stop()

    elif "GOOGLE_JSON" in st.secrets:
        try:
            raw_json = st.secrets["GOOGLE_JSON"]
            creds_dict = json.loads(raw_json, strict=False) if isinstance(raw_json, str) else dict(raw_json)
            if "private_key" in creds_dict:
                creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            return Credentials.from_service_account_info(creds_dict, scopes=scopes)
        except Exception as e:
            st.error(f"❌ อ่าน GOOGLE_JSON ไม่สำเร็จ: {e}")
            st.stop()

    elif os.path.exists("google_key.json"):
        return Credentials.from_service_account_file("google_key.json", scopes=scopes)

    st.error("❌ ไม่พบข้อมูลการเชื่อมต่อ Google Sheets ใน Secrets")
    st.stop()

try:
    creds = load_gcp_credentials()
except Exception as e:
    st.error(f"❌ โครงสร้างกุญแจ Google Sheets มีปัญหา: {e}")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)
client = gspread.authorize(creds)

# ==========================================
# 1. ตั้งค่าการเชื่อมต่อ (Local & Cloud)
# ==========================================
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

def sanitize_pem_key(key_str):
    """ทำความสะอาดและจัดโครงสร้าง PEM Key ใหม่หมดเพื่อป้องกัน MalformedFraming"""
    if not key_str:
        return key_str
    key_str = key_str.replace("\\n", "\n").replace("\r", "").strip('"' + "'" + " \t\n")
    
    if "-----BEGIN PRIVATE KEY-----" in key_str and "-----END PRIVATE KEY-----" in key_str:
        body = key_str.replace("-----BEGIN PRIVATE KEY-----", "").replace("-----END PRIVATE KEY-----", "")
        body_clean = "".join(body.split())
        formatted_body = "\n".join([body_clean[i:i+64] for i in range(0, len(body_clean), 64)])
        return f"-----BEGIN PRIVATE KEY-----\n{formatted_body}\n-----END PRIVATE KEY-----\n"
    return key_str

def load_gcp_credentials():
    creds_dict = None
    
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
    elif "GOOGLE_JSON" in st.secrets:
        raw_json = st.secrets["GOOGLE_JSON"]
        creds_dict = json.loads(raw_json, strict=False) if isinstance(raw_json, str) else dict(raw_json)
    elif os.path.exists("google_key.json"):
        return Credentials.from_service_account_file("google_key.json", scopes=scopes)
    
    if creds_dict:
        if "private_key" in creds_dict:
            creds_dict["private_key"] = sanitize_pem_key(str(creds_dict["private_key"]))
        return Credentials.from_service_account_info(creds_dict, scopes=scopes)
    
    st.error("❌ ไม่พบข้อมูลการเชื่อมต่อ Google Sheets กรุณาตั้งค่า Secrets")
    st.stop()

try:
    creds = load_gcp_credentials()
except Exception as e:
    st.error(f"❌ โครงสร้างกุญแจ Google Sheets มีปัญหา: {e}")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)
client = gspread.authorize(creds)

# ==========================================
# 2. ดึงและเตรียมข้อมูลจาก Google Sheets
# ==========================================
THAI_MONTHS = {
    "ม.ค.": "Jan", "มกราคม": "Jan", "ก.พ.": "Feb", "กุมภาพันธ์": "Feb",
    "มี.ค.": "Mar", "มีนาคม": "Mar", "เม.ย.": "Apr", "เมษายน": "Apr",
    "พ.ค.": "May", "พฤษภาคม": "May", "มิ.ย.": "Jun", "มิถุนายน": "Jun",
    "ก.ค.": "Jul", "กรกฎาคม": "Jul", "ส.ค.": "Aug", "สิงหาคม": "Aug",
    "ก.ย.": "Sep", "กันยายน": "Sep", "ต.ค.": "Oct", "ตุลาคม": "Oct",
    "พ.ย.": "Nov", "พฤศจิกายน": "Nov", "ธ.ค.": "Dec", "ธันวาคม": "Dec"
}

@st.cache_data(ttl=600)
def load_data():
    sheet = client.open("Test ค่าความเรียบมันLine MDF3").sheet1
    data = sheet.get_all_records()
    df_data = pd.DataFrame(data)
    df_data.columns = df_data.columns.str.strip()

    def smart_parse_date(series):
        def clean_val(val):
            if pd.isna(val) or str(val).strip() in ["", "nan", "None", "NaT", "null", "-", "0"]:
                return None
            val_str = str(val).strip()
            val_str = val_str.translate(str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789"))
            for th, en in THAI_MONTHS.items():
                if th in val_str:
                    val_str = val_str.replace(th, en)
                    break
            val_str = re.sub(r'\b2569\b', '2026', val_str)
            val_str = re.sub(r'([/.-])69(?!\d)', r'\1 2026', val_str)
            val_str = re.sub(r'\b(2[45]\d{2})\b', lambda m: str(int(m.group(0)) - 543), val_str)
            return val_str

        cleaned = series.apply(clean_val)
        parsed = pd.to_datetime(cleaned, dayfirst=True, errors="coerce")
        
        def adjust_year(dt):
            if pd.notna(dt):
                if dt.year > 2400:
                    return dt.replace(year=dt.year - 543)
                if 1960 <= dt.year <= 1970:
                    return dt.replace(year=dt.year + 57)
                if 2060 <= dt.year <= 2070:
                    return dt.replace(year=dt.year - 43)
                return dt
            return pd.NaT

        return parsed.apply(adjust_year)

    for col in ["วันที่ผลิต", "วันที่ขัด"]:
        if col in df_data.columns:
            df_data[f"{col}_parsed"] = smart_parse_date(df_data[col])

    if "วันที่ผลิต_parsed" in df_data.columns and "วันที่ขัด_parsed" in df_data.columns:
        df_data["วันที่ขัด_parsed"] = df_data["วันที่ขัด_parsed"].fillna(df_data["วันที่ผลิต_parsed"])
    elif "วันที่ผลิต_parsed" in df_data.columns and "วันที่ขัด_parsed" not in df_data.columns:
        df_data["วันที่ขัด_parsed"] = df_data["วันที่ผลิต_parsed"]

    numeric_columns = ["R", "MR", "M", "ML", "L", "STD"]
    for col in numeric_columns:
        if col in df_data.columns:
            df_data[col] = pd.to_numeric(df_data[col], errors="coerce")

    if all(col in df_data.columns for col in ["R", "MR", "M", "ML", "L"]):
        df_data["AVG_Smoothness"] = df_data[["R", "MR", "M", "ML", "L"]].mean(axis=1)

    return df_data


df = load_data()

# ==========================================
# 3. ส่วนตัวกรองข้อมูล (Sidebar Filter)
# ==========================================
st.sidebar.header("⚙️ ตัวกรองข้อมูล (Filter)")

line_col = "Line" if "Line" in df.columns else ("สายการผลิต" if "สายการผลิต" in df.columns else None)
if line_col:
    line_options = ["ทั้งหมด"] + list(df[line_col].dropna().astype(str).unique())
    selected_line = st.sidebar.selectbox("1. เลือก Line ผลิต", line_options)
    line_filtered_df = df if selected_line == "ทั้งหมด" else df[df[line_col].astype(str) == selected_line].copy()
else:
    selected_line = "MDF3"
    line_filtered_df = df.copy()

available_date_cols = [col for col in ["วันที่ผลิต", "วันที่ขัด"] if f"{col}_parsed" in df.columns]

filtered_df = line_filtered_df.copy()
active_parsed_col = None

if available_date_cols:
    selected_date_type = st.sidebar.radio(
        "2. เลือกประเภทวันที่เพื่อกรอง",
        available_date_cols,
        key="radio_date_type_select",
    )
    active_parsed_col = f"{selected_date_type}_parsed"
    valid_dates = line_filtered_df[active_parsed_col].dropna().dt.date

    if not valid_dates.empty:
        min_date = valid_dates.min()
        max_date = valid_dates.max()
        init_val = (min_date, max_date) if min_date != max_date else (min_date, min_date)

        st.sidebar.caption("💡 *คลิกเลือกวันบนปฏิทิน 2 ครั้งเพื่อกำหนดช่วงเริ่ม-สิ้นสุด*")
        date_range = st.sidebar.date_input(
            f"เลือกช่วง ({selected_date_type})",
            value=init_val,
            min_value=min_date,
            max_value=max_date,
            key=f"calendar_picker_{selected_line}_{selected_date_type}",
        )

        if isinstance(date_range, (tuple, list)):
            if len(date_range) == 2:
                filtered_df = line_filtered_df[(line_filtered_df[active_parsed_col].dt.date >= date_range[0]) & (line_filtered_df[active_parsed_col].dt.date <= date_range[1])]
            elif len(date_range) == 1:
                filtered_df = line_filtered_df[line_filtered_df[active_parsed_col].dt.date == date_range[0]]
        else:
            filtered_df = line_filtered_df[line_filtered_df[active_parsed_col].dt.date == date_range]
    else:
        st.sidebar.warning(f"ไม่พบข้อมูลวันที่ใน '{selected_date_type}'")

lot_col = "Lot." if "Lot." in df.columns else ("Lot" if "Lot" in df.columns else None)
if lot_col:
    lot_options = ["ทั้งหมด"] + list(filtered_df[lot_col].dropna().astype(str).unique())
    selected_lot = st.sidebar.selectbox("3. เลือก Lot", lot_options)
    if selected_lot != "ทั้งหมด":
        filtered_df = filtered_df[filtered_df[lot_col].astype(str) == selected_lot]

# ==========================================
# 4. แสดงผล Dashboard
# ==========================================
st.title(f"🏭 ระบบวิเคราะห์ค่าความเรียบมัน Line {selected_line}")

col1, col2, col3, col4 = st.columns(4)
col1.metric("จำนวน Lot ที่ผลิต", filtered_df[lot_col].nunique() if lot_col and lot_col in filtered_df.columns else 0)
col2.metric("จำนวนรายการตรวจเช็ค", len(filtered_df))

if "AVG_Smoothness" in filtered_df.columns and not filtered_df.empty:
    col3.metric("ค่าเฉลี่ยความเรียบ (รวม)", f"{filtered_df['AVG_Smoothness'].mean():.2f}")
if "STD" in filtered_df.columns and not filtered_df.empty:
    col4.metric("ค่า STD เป้าหมาย", f"{filtered_df['STD'].mean():.2f}")

st.markdown("---")
st.subheader("📈 แนวโน้มค่าความเรียบมันแยกรายจุด (L, ML, M, MR, R)")

if not filtered_df.empty and active_parsed_col:
    plot_df = filtered_df.sort_values(by=[active_parsed_col]).reset_index(drop=True)
    x_indices = list(range(len(plot_df)))

    if "เวลา" in plot_df.columns:
        x_labels = plot_df[active_parsed_col].dt.strftime("%d/%m/%Y") + " " + plot_df["เวลา"].astype(str)
    elif lot_col and lot_col in plot_df.columns:
        x_labels = plot_df[active_parsed_col].dt.strftime("%d/%m/%Y") + " (Lot:" + plot_df[lot_col].astype(str) + ")"
    else:
        x_labels = plot_df[active_parsed_col].dt.strftime("%d/%m/%Y")

    fig = go.Figure()
    point_colors = {"L": "#70133a", "M": "#ff8f00", "ML": "#2b579a", "MR": "#1e824c", "R": "#333333"}
    for point in ["L", "M", "ML", "MR", "R"]:
        if point in plot_df.columns:
            fig.add_trace(go.Scatter(x=x_indices, y=plot_df[point], mode="lines+markers", name=point,
                                     line=dict(color=point_colors.get(point, "#555"), width=2),
                                     marker=dict(size=5), text=x_labels,
                                     hovertemplate=f"<b>จุด {point}</b><br>ข้อมูล: %{{text}}<br>ค่า: %{{y:.2f}}<extra></extra>"))

    if "STD" in plot_df.columns:
        fig.add_trace(go.Scatter(x=x_indices, y=plot_df["STD"], mode="lines", name="STD", line=dict(color="#cc0000", width=2.5)))

    total_points = len(plot_df)
    step = max(1, total_points // 10)
    fig.update_layout(
        title=f"เปรียบเทียบค่าความเรียบมันทั้ง 5 จุด (Line {selected_line}) - ทั้งหมด {total_points} รายการ",
        xaxis_title="ลำดับรายการตรวจเช็ค (เลื่อนสไลเดอร์ด้านล่างเพื่อซูมขยาย)", yaxis_title="ค่าความเรียบมัน", hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        yaxis=dict(range=[2.0, 5.0]),
        xaxis=dict(tickmode="array", tickvals=x_indices[::step], ticktext=[x_labels[i] for i in x_indices[::step]], tickangle=-30, rangeslider=dict(visible=True))
    )
    st.plotly_chart(fig, use_container_width=True)

st.subheader("📋 รายละเอียดข้อมูลดิบ (Filtered Data)")
st.dataframe(filtered_df)

st.markdown("---")
st.subheader("🧠 ผู้ช่วย AI วิเคราะห์คุณภาพ (Quality Insight)")

if st.button("✨ ให้ AI วิเคราะห์คุณภาพของช่วงเวลานี้"):
    with st.spinner("AI กำลังวิเคราะห์ข้อมูล..."):
        columns_to_show = [col for col in [lot_col, active_parsed_col, "ความหนา", "AVG_Smoothness", "STD"] if col and col in filtered_df.columns]
        sample_data = filtered_df[columns_to_show].head(50).to_string()
        prompt = f"คุณคือวิศวกร QA โรงงาน MDF วิเคราะห์ค่าความเรียบมัน Line {selected_line} (STD=4.00):\n{sample_data}"
        try:
            model = genai.GenerativeModel("gemini-3.6-flash")
            st.info(model.generate_content(prompt).text)
        except Exception as e:
            st.error(f"เกิดข้อผิดพลาดในการเชื่อมต่อ AI: {e}")
# ==========================================
# 1. ตั้งค่าการเชื่อมต่อ (Local & Cloud)
# ==========================================
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ดึง Gemini Key
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

# ดึง Google Credentials ป้องกันไฟล์หายแครช
if "GOOGLE_JSON" in st.secrets:
    try:
        if isinstance(st.secrets["GOOGLE_JSON"], str):
            google_creds_dict = json.loads(st.secrets["GOOGLE_JSON"], strict=False)
        else:
            google_creds_dict = dict(st.secrets["GOOGLE_JSON"])
        creds = Credentials.from_service_account_info(google_creds_dict, scopes=scopes)
    except Exception as e:
        st.error(f"❌ รูปแบบ Secrets ของ GOOGLE_JSON ไม่ถูกต้อง: {e}")
        st.stop()
elif os.path.exists("google_key.json"):
    creds = Credentials.from_service_account_file("google_key.json", scopes=scopes)
else:
    st.error("❌ ไม่พบข้อมูลการเชื่อมต่อ Google Sheets กรุณาใส่คีย์ใน Secrets บน Streamlit Cloud")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)
client = gspread.authorize(creds)
# ==========================================
# 2. ดึงและเตรียมข้อมูลจาก Google Sheets
# ==========================================
THAI_MONTHS = {
    "ม.ค.": "Jan", "มกราคม": "Jan", "ก.พ.": "Feb", "กุมภาพันธ์": "Feb",
    "มี.ค.": "Mar", "มีนาคม": "Mar", "เม.ย.": "Apr", "เมษายน": "Apr",
    "พ.ค.": "May", "พฤษภาคม": "May", "มิ.ย.": "Jun", "มิถุนายน": "Jun",
    "ก.ค.": "Jul", "กรกฎาคม": "Jul", "ส.ค.": "Aug", "สิงหาคม": "Aug",
    "ก.ย.": "Sep", "กันยายน": "Sep", "ต.ค.": "Oct", "ตุลาคม": "Oct",
    "พ.ย.": "Nov", "พฤศจิกายน": "Nov", "ธ.ค.": "Dec", "ธันวาคม": "Dec"
}

@st.cache_data(ttl=600)
def load_data():
    sheet = client.open("Test ค่าความเรียบมันLine MDF3").sheet1
    data = sheet.get_all_records()
    df_data = pd.DataFrame(data)
    df_data.columns = df_data.columns.str.strip()

    def smart_parse_date(series):
        def clean_val(val):
            if pd.isna(val) or str(val).strip() in ["", "nan", "None", "NaT", "null", "-", "0"]:
                return None
            val_str = str(val).strip()
            val_str = val_str.translate(str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789"))
            for th, en in THAI_MONTHS.items():
                if th in val_str:
                    val_str = val_str.replace(th, en)
                    break
            val_str = re.sub(r'\b2569\b', '2026', val_str)
            val_str = re.sub(r'([/.-])69(?!\d)', r'\1 2026', val_str)
            val_str = re.sub(r'\b(2[45]\d{2})\b', lambda m: str(int(m.group(0)) - 543), val_str)
            return val_str

        cleaned = series.apply(clean_val)
        parsed = pd.to_datetime(cleaned, dayfirst=True, errors="coerce")
        
        def adjust_year(dt):
            if pd.notna(dt):
                if dt.year > 2400:
                    return dt.replace(year=dt.year - 543)
                if 1960 <= dt.year <= 1970:
                    return dt.replace(year=dt.year + 57)
                if 2060 <= dt.year <= 2070:
                    return dt.replace(year=dt.year - 43)
                return dt
            return pd.NaT

        return parsed.apply(adjust_year)

    for col in ["วันที่ผลิต", "วันที่ขัด"]:
        if col in df_data.columns:
            df_data[f"{col}_parsed"] = smart_parse_date(df_data[col])

    if "วันที่ผลิต_parsed" in df_data.columns and "วันที่ขัด_parsed" in df_data.columns:
        df_data["วันที่ขัด_parsed"] = df_data["วันที่ขัด_parsed"].fillna(df_data["วันที่ผลิต_parsed"])
    elif "วันที่ผลิต_parsed" in df_data.columns and "วันที่ขัด_parsed" not in df_data.columns:
        df_data["วันที่ขัด_parsed"] = df_data["วันที่ผลิต_parsed"]

    numeric_columns = ["R", "MR", "M", "ML", "L", "STD"]
    for col in numeric_columns:
        if col in df_data.columns:
            df_data[col] = pd.to_numeric(df_data[col], errors="coerce")

    if all(col in df_data.columns for col in ["R", "MR", "M", "ML", "L"]):
        df_data["AVG_Smoothness"] = df_data[["R", "MR", "M", "ML", "L"]].mean(axis=1)

    return df_data


df = load_data()

# ==========================================
# 3. ส่วนตัวกรองข้อมูล (Sidebar Filter)
# ==========================================
st.sidebar.header("⚙️ ตัวกรองข้อมูล (Filter)")

line_col = "Line" if "Line" in df.columns else ("สายการผลิต" if "สายการผลิต" in df.columns else None)
if line_col:
    line_options = ["ทั้งหมด"] + list(df[line_col].dropna().astype(str).unique())
    selected_line = st.sidebar.selectbox("1. เลือก Line ผลิต", line_options)
    line_filtered_df = df if selected_line == "ทั้งหมด" else df[df[line_col].astype(str) == selected_line].copy()
else:
    selected_line = "MDF3"
    line_filtered_df = df.copy()

available_date_cols = [col for col in ["วันที่ผลิต", "วันที่ขัด"] if f"{col}_parsed" in df.columns]

filtered_df = line_filtered_df.copy()
active_parsed_col = None

if available_date_cols:
    selected_date_type = st.sidebar.radio(
        "2. เลือกประเภทวันที่เพื่อกรอง",
        available_date_cols,
        key="radio_date_type_select",
    )
    active_parsed_col = f"{selected_date_type}_parsed"
    valid_dates = line_filtered_df[active_parsed_col].dropna().dt.date

    if not valid_dates.empty:
        min_date = valid_dates.min()
        max_date = valid_dates.max()
        init_val = (min_date, max_date) if min_date != max_date else (min_date, min_date)

        st.sidebar.caption("💡 *คลิกเลือกวันบนปฏิทิน 2 ครั้งเพื่อกำหนดช่วงเริ่ม-สิ้นสุด*")
        date_range = st.sidebar.date_input(
            f"เลือกช่วง ({selected_date_type})",
            value=init_val,
            min_value=min_date,
            max_value=max_date,
            key=f"calendar_picker_{selected_line}_{selected_date_type}",
        )

        if isinstance(date_range, (tuple, list)):
            if len(date_range) == 2:
                filtered_df = line_filtered_df[(line_filtered_df[active_parsed_col].dt.date >= date_range[0]) & (line_filtered_df[active_parsed_col].dt.date <= date_range[1])]
            elif len(date_range) == 1:
                filtered_df = line_filtered_df[line_filtered_df[active_parsed_col].dt.date == date_range[0]]
        else:
            filtered_df = line_filtered_df[line_filtered_df[active_parsed_col].dt.date == date_range]
    else:
        st.sidebar.warning(f"ไม่พบข้อมูลวันที่ใน '{selected_date_type}'")

lot_col = "Lot." if "Lot." in df.columns else ("Lot" if "Lot" in df.columns else None)
if lot_col:
    lot_options = ["ทั้งหมด"] + list(filtered_df[lot_col].dropna().astype(str).unique())
    selected_lot = st.sidebar.selectbox("3. เลือก Lot", lot_options)
    if selected_lot != "ทั้งหมด":
        filtered_df = filtered_df[filtered_df[lot_col].astype(str) == selected_lot]

# ==========================================
# 4. แสดงผล Dashboard
# ==========================================
st.title(f"🏭 ระบบวิเคราะห์ค่าความเรียบมัน Line {selected_line}")

col1, col2, col3, col4 = st.columns(4)
col1.metric("จำนวน Lot ที่ผลิต", filtered_df[lot_col].nunique() if lot_col and lot_col in filtered_df.columns else 0)
col2.metric("จำนวนรายการตรวจเช็ค", len(filtered_df))

if "AVG_Smoothness" in filtered_df.columns and not filtered_df.empty:
    col3.metric("ค่าเฉลี่ยความเรียบ (รวม)", f"{filtered_df['AVG_Smoothness'].mean():.2f}")
if "STD" in filtered_df.columns and not filtered_df.empty:
    col4.metric("ค่า STD เป้าหมาย", f"{filtered_df['STD'].mean():.2f}")

st.markdown("---")
st.subheader("📈 แนวโน้มค่าความเรียบมันแยกรายจุด (L, ML, M, MR, R)")

if not filtered_df.empty and active_parsed_col:
    plot_df = filtered_df.sort_values(by=[active_parsed_col]).reset_index(drop=True)
    x_indices = list(range(len(plot_df)))

    if "เวลา" in plot_df.columns:
        x_labels = plot_df[active_parsed_col].dt.strftime("%d/%m/%Y") + " " + plot_df["เวลา"].astype(str)
    elif lot_col and lot_col in plot_df.columns:
        x_labels = plot_df[active_parsed_col].dt.strftime("%d/%m/%Y") + " (Lot:" + plot_df[lot_col].astype(str) + ")"
    else:
        x_labels = plot_df[active_parsed_col].dt.strftime("%d/%m/%Y")

    fig = go.Figure()
    point_colors = {"L": "#70133a", "M": "#ff8f00", "ML": "#2b579a", "MR": "#1e824c", "R": "#333333"}
    for point in ["L", "M", "ML", "MR", "R"]:
        if point in plot_df.columns:
            fig.add_trace(go.Scatter(x=x_indices, y=plot_df[point], mode="lines+markers", name=point,
                                     line=dict(color=point_colors.get(point, "#555"), width=2),
                                     marker=dict(size=5), text=x_labels,
                                     hovertemplate=f"<b>จุด {point}</b><br>ข้อมูล: %{{text}}<br>ค่า: %{{y:.2f}}<extra></extra>"))

    if "STD" in plot_df.columns:
        fig.add_trace(go.Scatter(x=x_indices, y=plot_df["STD"], mode="lines", name="STD", line=dict(color="#cc0000", width=2.5)))

    total_points = len(plot_df)
    step = max(1, total_points // 10)
    fig.update_layout(
        title=f"เปรียบเทียบค่าความเรียบมันทั้ง 5 จุด (Line {selected_line}) - ทั้งหมด {total_points} รายการ",
        xaxis_title="ลำดับรายการตรวจเช็ค (เลื่อนสไลเดอร์ด้านล่างเพื่อซูมขยาย)", yaxis_title="ค่าความเรียบมัน", hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        yaxis=dict(range=[2.0, 5.0]),
        xaxis=dict(tickmode="array", tickvals=x_indices[::step], ticktext=[x_labels[i] for i in x_indices[::step]], tickangle=-30, rangeslider=dict(visible=True))
    )
    st.plotly_chart(fig, use_container_width=True)

st.subheader("📋 รายละเอียดข้อมูลดิบ (Filtered Data)")
st.dataframe(filtered_df)

st.markdown("---")
st.subheader("🧠 ผู้ช่วย AI วิเคราะห์คุณภาพ (Quality Insight)")

if st.button("✨ ให้ AI วิเคราะห์คุณภาพของช่วงเวลานี้"):
    with st.spinner("AI กำลังวิเคราะห์ข้อมูล..."):
        columns_to_show = [col for col in [lot_col, active_parsed_col, "ความหนา", "AVG_Smoothness", "STD"] if col and col in filtered_df.columns]
        sample_data = filtered_df[columns_to_show].head(50).to_string()
        prompt = f"คุณคือวิศวกร QA โรงงาน MDF วิเคราะห์ค่าความเรียบมัน Line {selected_line} (STD=4.00):\n{sample_data}"
        try:
            model = genai.GenerativeModel("gemini-3.6-flash")
            st.info(model.generate_content(prompt).text)
        except Exception as e:
            st.error(f"เกิดข้อผิดพลาดในการเชื่อมต่อ AI: {e}")