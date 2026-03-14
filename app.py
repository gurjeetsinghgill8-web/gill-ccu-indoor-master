# ============================================================
#  DR. GILL'S CARDIAC & CRITICAL CARE COMMAND SYSTEM  v2.0
#  Kerala Cardiac ICU - World-Class AI Clinical Platform
#  Built by: Chief AI Architect (Generative AI Agent)
#  Date: 2025
# ============================================================

import streamlit as st
import google.generativeai as genai
import os
import requests
import pandas as pd
from fpdf import FPDF
import tempfile
import datetime
import random
import string
import json
from PIL import Image
import io

# ============================================================
# SECTION 1: PAGE SETUP
# ============================================================
st.set_page_config(
    page_title="Dr. Gill's Cardiac ICU Command System v2.0",
    layout="wide",
    page_icon="🏥",
    initial_sidebar_state="collapsed"
)

# ============================================================
# SECTION 2: MASTER CREDENTIALS (YOUR PRIVATE VAULT)
# ============================================================
# ╔═══════════════════════════════════════════════════════════╗
# ║  🔐 YOUR MASTER PASSWORD IS:  GILL@ICU#2025              ║
# ║  Keep this ONLY with yourself. Never share this.          ║
# ║  This gives you GOD-MODE access to everything.            ║
# ╚═══════════════════════════════════════════════════════════╝
MASTER_PASSWORD = "GILL@ICU#2025"
MASTER_NAME     = "Dr. G.S. Gill (MASTER ADMIN | HOD Cardiology)"

# Google Sheets Webhook — same as your original
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbwIBxF5vh7uvdDnRblpyhfpQCtpcxWN3MlGjbt3SUeEO5KH3c9AIcU91BzeKVQKCn_L/exec"

# ============================================================
# SECTION 3: DEFAULT DOCTOR DATABASE (Admin can expand this)
# ============================================================
DEFAULT_DOCTORS = {
    "9999": {"name": "Dr. Alok Sehgal",  "role": "Senior Interventional Cardiologist", "access": "HOD"},
    "1234": {"name": "Dr. G.S. Gill",     "role": "Cardiac Physician",                  "access": "Senior"},
    "0000": {"name": "Dr. Shivam Tomar",  "role": "Cardiac Physician",                  "access": "Resident"},
}

# ============================================================
# SECTION 4: SESSION STATE INITIALIZATION
# ============================================================
if "logged_in"      not in st.session_state: st.session_state.logged_in      = False
if "current_user"   not in st.session_state: st.session_state.current_user   = None
if "is_master"      not in st.session_state: st.session_state.is_master      = False
if "patients_db"    not in st.session_state: st.session_state.patients_db    = {}
if "doctors_db"     not in st.session_state: st.session_state.doctors_db     = DEFAULT_DOCTORS.copy()
if "icu_beds"       not in st.session_state: st.session_state.icu_beds       = {f"Bed {i}": "Empty" for i in range(1, 13)}
if "handover_notes" not in st.session_state: st.session_state.handover_notes = []
if "audit_log"      not in st.session_state: st.session_state.audit_log      = []

# ============================================================
# SECTION 5: API ENGINE SETUP
# ============================================================
active_key = ""
if "GEMINI_API_KEY" in st.secrets:
    active_key = st.secrets["GEMINI_API_KEY"]
else:
    active_key = os.getenv("GEMINI_API_KEY", "")

is_engine_ready = False
if active_key and active_key.startswith("AIza"):
    try:
        genai.configure(api_key=active_key)
        is_engine_ready = True
    except Exception as e:
        st.error(f"Engine Config Error: {e}")

# ============================================================
# SECTION 6: HELPER — LOG EVERY ACTION (AUDIT TRAIL)
# ============================================================
def log_action(action_text):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = st.session_state.current_user or "Unknown"
    st.session_state.audit_log.insert(0, f"[{ts}] {user} → {action_text}")
    if len(st.session_state.audit_log) > 200:
        st.session_state.audit_log = st.session_state.audit_log[:200]

# ============================================================
# SECTION 7: AI DYNAMIC ENGINE (Smart Model Picker)
# ============================================================
def smart_generate(contents):
    available_models = []
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
    except Exception as e:
        raise Exception(f"Cannot fetch models from Google: {e}")

    if not available_models:
        raise Exception("Google returned NO available models for this API key.")

    def sort_key(n):
        if '1.5-flash' in n and '8b' not in n: return 1
        if '1.5-flash-8b' in n:                return 2
        if '2.0-flash' in n:                   return 3
        if '1.5-pro' in n:                     return 4
        if 'gemini-pro' in n:                  return 5
        return 99

    available_models.sort(key=sort_key)
    errors = []
    for m_name in available_models:
        try:
            model  = genai.GenerativeModel(m_name)
            result = model.generate_content(contents)
            if result and result.text:
                return result.text.replace('**', '').replace('##', '').replace('###', '')
        except Exception as e:
            errors.append(f"[{m_name}]: {str(e)}")
            continue
    raise Exception("All AI engines failed:\n" + "\n".join(errors))

def optimize_image(uploaded_file):
    img = Image.open(uploaded_file)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img.thumbnail((1200, 1200))
    return img

# ============================================================
# SECTION 8: CLOUD SYNC (Google Sheets)
# ============================================================
def sync_from_cloud():
    if not WEBHOOK_URL.startswith("http"):
        return
    try:
        res = requests.get(WEBHOOK_URL, timeout=10)
        if res.status_code == 200:
            cloud_data = res.json()
            new_db = {}
            for row in cloud_data:
                p_name = row.get("patient_name", "").strip()
                if not p_name:
                    continue
                status = row.get("status", "Active")
                if p_name not in new_db:
                    new_db[p_name] = {"status": status, "history": [], "bed": row.get("bed", "Unassigned")}
                if status == "Discharged":
                    new_db[p_name]["status"] = "Discharged"
                new_db[p_name]["history"].append({
                    "date":      row.get("date", str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))),
                    "doctor":    row.get("doctor", "Unknown"),
                    "raw_notes": row.get("raw_notes", ""),
                    "summary":   row.get("summary", ""),
                })
            st.session_state.patients_db = new_db
    except Exception:
        pass

def push_to_cloud(payload):
    if not WEBHOOK_URL.startswith("http"):
        return False
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=10)
        return True
    except Exception:
        return False

# ============================================================
# SECTION 9: PDF GENERATOR (True Clinical PDF)
# ============================================================
def generate_pdf(title, patient_name, text_content, doctor_name=""):
    pdf = FPDF()
    pdf.add_page()
    # Header
    pdf.set_fill_color(10, 50, 100)
    pdf.rect(0, 0, 210, 25, 'F')
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 8, txt="DR. GILL'S CARDIAC & CRITICAL CARE ICU", ln=True, align='C')
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 7, txt="Kerala | AI Clinical Decision Support System v2.0", ln=True, align='C')
    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)
    # Document title
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, txt=title.upper(), ln=True, align='C')
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)
    # Patient info block
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(230, 240, 255)
    pdf.cell(0, 8, f"  Patient: {patient_name}", ln=True, fill=True)
    pdf.cell(0, 8, f"  HOD: Dr. Alok Sehgal (Sr. Interventional Cardiologist)  |  Duty Dr: {doctor_name}", ln=True, fill=True)
    pdf.cell(0, 8, f"  Generated: {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}", ln=True, fill=True)
    pdf.ln(5)
    # Content
    pdf.set_font("Arial", size=10)
    clean = text_content.replace('**', '').replace('*', '-').replace('#', '')
    clean = clean.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 6, txt=clean)
    # Footer
    pdf.set_y(-20)
    pdf.set_font("Arial", 'I', 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, "CONFIDENTIAL — FOR CLINICAL USE ONLY | Dr. Gill's ICU App v2.0 | Kerala", align='C')

    temp_dir  = tempfile.mkdtemp()
    filepath  = os.path.join(temp_dir, f"{patient_name}_{title.replace(' ', '_')}.pdf")
    pdf.output(filepath)
    return filepath

# ============================================================
# SECTION 10: NEWS2 SCORE CALCULATOR
# ============================================================
def calc_news2(rr, spo2, supp_o2, sbp, hr, temp, avpu, hypercapnic=False):
    score = 0
    # Respiratory Rate
    if rr <= 8 or rr >= 25:   score += 3
    elif rr in range(9, 12):  score += 1
    elif rr in range(21, 25): score += 2
    # SpO2 Scale 1 (normal patients)
    if not hypercapnic:
        if spo2 <= 91:          score += 3
        elif spo2 in range(92, 94): score += 2
        elif spo2 in range(94, 96): score += 1
    # Supplemental O2
    if supp_o2:
        score += 2
    # Systolic BP
    if sbp <= 90 or sbp >= 220:   score += 3
    elif sbp in range(91, 101):   score += 2
    elif sbp in range(101, 111):  score += 1
    # Heart Rate
    if hr <= 40 or hr >= 131:  score += 3
    elif hr in range(41, 51) or hr in range(111, 131): score += 2
    elif hr in range(91, 111): score += 1
    # Temperature
    if temp <= 35.0:        score += 3
    elif temp <= 36.0:      score += 1
    elif temp >= 39.1:      score += 2
    elif temp >= 38.1:      score += 1
    # AVPU
    avpu_scores = {"Alert": 0, "Confusion/New": 3, "Voice": 3, "Pain": 3, "Unresponsive": 3}
    score += avpu_scores.get(avpu, 0)

    if score >= 7:   risk, color, action = "HIGH", "🔴", "IMMEDIATE senior review / transfer to Level 3 care"
    elif score >= 5: risk, color, action = "MEDIUM-HIGH", "🟠", "Urgent senior review within 30 minutes"
    elif score >= 3: risk, color, action = "MEDIUM", "🟡", "Increased monitoring, review within 1 hour"
    else:            risk, color, action = "LOW", "🟢", "Continue routine monitoring"
    return score, risk, color, action

# ============================================================
# SECTION 11: PIN GENERATOR FOR ADMIN
# ============================================================
def generate_pin(length=4):
    return ''.join(random.choices(string.digits, k=length))

# ============================================================
# SECTION 12: LOGIN SCREEN
# ============================================================
if not st.session_state.logged_in:
    # Sync on first load
    sync_from_cloud()

    # Beautiful login screen
    st.markdown("""
    <style>
    .login-box { background: linear-gradient(135deg, #0a1628 0%, #1a3a6e 100%);
                 padding: 40px; border-radius: 16px; text-align: center; color: white; }
    .login-title { font-size: 28px; font-weight: bold; margin-bottom: 5px; }
    .login-sub   { font-size: 14px; color: #a0b8d8; margin-bottom: 25px; }
    </style>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
        <div class="login-box">
          <div class="login-title">🏥 Dr. Gill's Cardiac ICU Command System</div>
          <div class="login-sub">Kerala Cardiac ICU · AI-Powered Clinical Decision Support · v2.0</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("---")
        pin_input = st.text_input("Enter PIN or Master Password:", type="password", placeholder="4-digit PIN or Master Password")

        if st.button("🔐 Access System", type="primary", use_container_width=True):
            doctors = st.session_state.doctors_db
            if pin_input == MASTER_PASSWORD:
                st.session_state.logged_in    = True
                st.session_state.current_user = MASTER_NAME
                st.session_state.is_master    = True
                log_action("MASTER LOGIN")
                st.rerun()
            elif pin_input in doctors:
                doc = doctors[pin_input]
                st.session_state.logged_in    = True
                st.session_state.current_user = f"{doc['name']} ({doc['role']})"
                st.session_state.is_master    = False
                log_action("Doctor LOGIN")
                st.rerun()
            else:
                st.error("🚨 Invalid PIN or Password. Access Denied.")
        st.markdown("---")
        st.caption("🔒 Secure | All data encrypted in transit | For authorized personnel only")
    st.stop()

# ============================================================
# SECTION 13: MAIN APP HEADER
# ============================================================
col_h1, col_h2, col_h3 = st.columns([5, 4, 1])
with col_h1:
    master_badge = " 👑 MASTER ADMIN" if st.session_state.is_master else ""
    st.markdown(f"### 🏥 Dr. Gill's Cardiac ICU Command System v2.0{master_badge}")
with col_h2:
    st.markdown(f"**HOD:** Dr. Alok Sehgal *(Sr. Interventional Cardiologist)*")
    st.markdown(f"**Active User:** `{st.session_state.current_user}`  |  **Time:** {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}")
with col_h3:
    if st.button("🚪 Logout"):
        log_action("Logout")
        for key in ["logged_in", "current_user", "is_master"]:
            st.session_state[key] = False if key == "logged_in" else (False if key == "is_master" else None)
        st.rerun()
st.markdown("---")

# ============================================================
# SECTION 14: BUILD TABS (Master gets extra Admin tab)
# ============================================================
if st.session_state.is_master:
    tab_list = [
        "👑 MASTER CONTROL",
        "🏥 ICU Bed Board",
        "🩺 ICU Frontline",
        "📊 HOD Dashboard",
        "📉 Flowsheet & Trends",
        "🚨 Early Warning",
        "💊 Medication Safety",
        "🔄 Shift Handover",
        "🔬 Academic Vault"
    ]
else:
    tab_list = [
        "🏥 ICU Bed Board",
        "🩺 ICU Frontline",
        "📊 HOD Dashboard",
        "📉 Flowsheet & Trends",
        "🚨 Early Warning",
        "💊 Medication Safety",
        "🔄 Shift Handover",
        "🔬 Academic Vault"
    ]

tabs = st.tabs(tab_list)

# Helper to get tab by name
def get_tab(name):
    idx = tab_list.index(name)
    return tabs[idx]

# ============================================================
# ============================================================
#   TAB: 👑 MASTER CONTROL PANEL (YOU ONLY)
# ============================================================
# ============================================================
if st.session_state.is_master:
    with get_tab("👑 MASTER CONTROL"):
        st.markdown("""
        <div style="background:linear-gradient(135deg,#1a1a2e,#16213e,#0f3460);padding:20px;border-radius:12px;color:white;margin-bottom:20px">
          <h2 style="margin:0">👑 MASTER CONTROL PANEL — Dr. G.S. Gill</h2>
          <p style="margin:5px 0 0 0;color:#aaa">God-mode access · Only YOU can see this panel</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("#### 🔐 YOUR MASTER PASSWORD (Keep Secret!)")
        st.code(f"MASTER PASSWORD: {MASTER_PASSWORD}", language=None)
        st.caption("Write this down in a safe place. Use this to login and access this Master Control Panel.")

        st.markdown("---")

        # ---- DOCTOR MANAGEMENT ----
        st.markdown("### 👨‍⚕️ Doctor & Resident Management")
        st.caption("Add doctors/residents, generate their PINs, remove them anytime.")

        # Display current doctors
        docs = st.session_state.doctors_db
        doc_data = []
        for pin, info in docs.items():
            doc_data.append({"PIN": pin, "Name": info['name'], "Role": info['role'], "Access Level": info['access']})
        if doc_data:
            df_docs = pd.DataFrame(doc_data)
            st.dataframe(df_docs, use_container_width=True, hide_index=True)

        st.markdown("#### ➕ Add New Doctor / Resident")
        col_d1, col_d2, col_d3, col_d4 = st.columns(4)
        with col_d1:
            new_doc_name = st.text_input("Full Name:", placeholder="Dr. Firstname Lastname")
        with col_d2:
            new_doc_role = st.selectbox("Role:", ["Resident", "Senior Resident", "Registrar", "Consultant", "Visiting Consultant", "HOD"])
        with col_d3:
            new_doc_access = st.selectbox("Access Level:", ["Resident", "Senior", "HOD"])
        with col_d4:
            custom_pin = st.text_input("Custom PIN (leave blank for auto):", max_chars=6, placeholder="e.g. 5678")

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("✅ Add Doctor to System", type="primary", use_container_width=True):
                if not new_doc_name.strip():
                    st.warning("Please enter the doctor's name.")
                else:
                    assigned_pin = custom_pin.strip() if custom_pin.strip() else generate_pin(4)
                    while assigned_pin in st.session_state.doctors_db:
                        assigned_pin = generate_pin(4)
                    st.session_state.doctors_db[assigned_pin] = {
                        "name": new_doc_name.strip(),
                        "role": new_doc_role,
                        "access": new_doc_access
                    }
                    log_action(f"Added doctor: {new_doc_name} with PIN {assigned_pin}")
                    st.success(f"✅ {new_doc_name} added successfully!")
                    st.info(f"🔑 Their PIN is: **{assigned_pin}**  — Share this privately with them.")
                    st.rerun()

        st.markdown("#### ❌ Remove a Doctor")
        pins_to_show = {f"{v['name']} ({k})": k for k, v in docs.items()}
        to_remove = st.selectbox("Select Doctor to Remove:", ["---"] + list(pins_to_show.keys()))
        with col_btn2:
            if st.button("🗑️ Remove Selected Doctor", use_container_width=True):
                if to_remove != "---":
                    pin_r = pins_to_show[to_remove]
                    name_r = docs[pin_r]['name']
                    del st.session_state.doctors_db[pin_r]
                    log_action(f"Removed doctor: {name_r}")
                    st.success(f"Removed {name_r} from the system.")
                    st.rerun()

        st.markdown("---")

        # ---- SYSTEM OVERVIEW ----
        st.markdown("### 📊 System Overview & Statistics")
        total_pts   = len(st.session_state.patients_db)
        active_pts  = sum(1 for d in st.session_state.patients_db.values() if d.get("status") == "Active")
        discharged  = total_pts - active_pts
        total_docs  = len(st.session_state.doctors_db)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Patients Ever", total_pts)
        m2.metric("Currently Active",    active_pts, delta="In ICU")
        m3.metric("Discharged",          discharged)
        m4.metric("Registered Doctors",  total_docs)

        st.markdown("---")

        # ---- AUDIT LOG ----
        st.markdown("### 📋 Full Audit Trail (Every Action Logged)")
        if st.session_state.audit_log:
            for entry in st.session_state.audit_log[:50]:
                st.text(entry)
        else:
            st.info("No audit entries yet.")

        st.markdown("---")

        # ---- DATA MANAGEMENT ----
        st.markdown("### 🗄️ Data Management")
        col_dm1, col_dm2 = st.columns(2)
        with col_dm1:
            if st.button("🔄 Force Sync from Google Sheets", use_container_width=True):
                sync_from_cloud()
                log_action("Force synced from cloud")
                st.success("Synced!")
        with col_dm2:
            if st.button("🧹 Clear All Session Data (Careful!)", use_container_width=True):
                st.session_state.patients_db = {}
                log_action("Cleared all session patient data")
                st.warning("Session data cleared. Will re-sync from cloud on next load.")

# ============================================================
#   TAB: 🏥 ICU BED BOARD (Live Overview)
# ============================================================
with get_tab("🏥 ICU Bed Board"):
    st.header("🏥 Live ICU Bed Board — Kerala Cardiac ICU")
    st.caption("Real-time overview of all 12 ICU beds. Update bed assignments below.")

    active_patients = [name for name, d in st.session_state.patients_db.items() if d.get("status") == "Active"]

    # Bed grid display
    st.markdown("#### 🛏️ Bed Status Overview")
    bed_cols = st.columns(4)
    beds = st.session_state.icu_beds

    for i, (bed, patient) in enumerate(beds.items()):
        with bed_cols[i % 4]:
            if patient == "Empty":
                color = "#2d5a27"
                emoji = "🟢"
            else:
                color = "#8b1a1a"
                emoji = "🔴"
            st.markdown(f"""
            <div style="background:{color};padding:10px;border-radius:8px;text-align:center;margin:4px;color:white">
              <b>{emoji} {bed}</b><br>
              <small>{patient}</small>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### 🔄 Update Bed Assignments")
    col_b1, col_b2, col_b3 = st.columns(3)
    with col_b1:
        selected_bed = st.selectbox("Select Bed:", list(beds.keys()))
    with col_b2:
        bed_action = st.radio("Action:", ["Assign Patient", "Mark Empty"], horizontal=True)
    with col_b3:
        if bed_action == "Assign Patient":
            bed_patient = st.selectbox("Assign Patient:", ["---"] + active_patients)
            if st.button("✅ Assign Bed"):
                if bed_patient != "---":
                    st.session_state.icu_beds[selected_bed] = bed_patient
                    log_action(f"Assigned {bed_patient} to {selected_bed}")
                    st.rerun()
        else:
            if st.button("✅ Mark as Empty"):
                st.session_state.icu_beds[selected_bed] = "Empty"
                log_action(f"Marked {selected_bed} as Empty")
                st.rerun()

    st.markdown("---")
    # Quick stats
    occupied = sum(1 for v in beds.values() if v != "Empty")
    st.markdown(f"**ICU Occupancy:** {occupied}/12 beds occupied &nbsp;&nbsp; | &nbsp;&nbsp; **Available:** {12 - occupied} beds free")

# ============================================================
#   TAB: 🩺 ICU FRONTLINE (Admissions & Progress)
# ============================================================
with get_tab("🩺 ICU Frontline"):
    st.header("🩺 ICU Frontline — Admissions & Progress Notes")

    col_pt1, col_pt2 = st.columns(2)
    with col_pt1:
        patient_type = st.radio("Patient Status:", ["New Admission", "Existing Patient"], horizontal=True)
    with col_pt2:
        diagnosis_category = st.selectbox("Primary Diagnosis Category:", [
            "Acute MI / ACS",
            "Heart Failure",
            "Arrhythmia / Dysrhythmia",
            "Cardiogenic Shock",
            "Post-PCI / Post-CABG",
            "Cardiac Tamponade / Pericarditis",
            "Hypertensive Emergency",
            "Pulmonary Embolism",
            "Sepsis / Septic Shock",
            "Respiratory Failure",
            "Renal Failure (AKI/CKD)",
            "Multi-Organ Failure",
            "Post-Cardiac Arrest",
            "Other Critical"
        ])

    if patient_type == "New Admission":
        p_name = st.text_input("New Patient Full Name:", placeholder="e.g., Rajan Kumar").strip().title()
        col_na1, col_na2, col_na3 = st.columns(3)
        with col_na1:
            age   = st.number_input("Age:", min_value=1, max_value=120, value=55)
        with col_na2:
            gender = st.selectbox("Gender:", ["Male", "Female", "Other"])
        with col_na3:
            bed_assign = st.selectbox("Assign Bed:", ["Unassigned"] + [b for b, v in st.session_state.icu_beds.items() if v == "Empty"])
    else:
        active_pts = [nm for nm, d in st.session_state.patients_db.items() if d.get("status") == "Active"]
        if not active_pts:
            st.info("No active patients. Please admit a new patient first.")
            p_name = ""
        else:
            p_name = st.selectbox("Select Existing Patient:", ["---"] + active_pts)
            if p_name == "---":
                p_name = ""

    st.markdown("---")
    st.subheader("📝 Clinical Notes & Investigations")

    # Structured vitals entry
    with st.expander("📊 Enter Vitals (Structured)", expanded=False):
        vc1, vc2, vc3, vc4, vc5, vc6 = st.columns(6)
        with vc1: v_bp  = st.text_input("BP (mmHg)", "120/80")
        with vc2: v_hr  = st.number_input("HR (bpm)", 0, 300, 80)
        with vc3: v_rr  = st.number_input("RR (/min)", 0, 60, 16)
        with vc4: v_spo2 = st.number_input("SpO2 (%)", 0, 100, 98)
        with vc5: v_temp = st.number_input("Temp (°C)", 30.0, 43.0, 37.0, 0.1)
        with vc6: v_gcs  = st.number_input("GCS", 3, 15, 15)
        vitals_str = f"BP:{v_bp} HR:{v_hr} RR:{v_rr} SpO2:{v_spo2}% Temp:{v_temp}C GCS:{v_gcs}"

    notes = st.text_area(
        "Dictate Full Clinical Picture (History, Examination, Labs, ABG, ECG findings):",
        height=180,
        placeholder="Example: 65yr male, DM2/HTN, presented with chest pain 2hrs ago, STEMI inferior lead ECG, BP 90/60, HR 110, SpO2 94%..."
    )

    full_notes = f"Category: {diagnosis_category}\nVitals: {vitals_str}\nClinical Notes: {notes}" if notes else f"Category: {diagnosis_category}\nVitals: {vitals_str}"

    st.subheader("📸 Upload ECG, X-Ray, Echo, ABG, Lab Reports")
    st.caption("📱 Mobile users: Tap 'Browse files' → select camera for direct photo capture")
    uploaded_files = st.file_uploader(
        "Upload Images/PDFs (multiple allowed):",
        type=['jpg', 'jpeg', 'png', 'pdf'],
        accept_multiple_files=True,
        key="frontline_upload"
    )

    has_input = bool(notes.strip() or uploaded_files)

    st.markdown("---")
    col_btn1, col_btn2, col_btn3 = st.columns(3)
    with col_btn1:
        analyze_quick  = st.button("🚨 Quick Frontline Analysis", type="primary", use_container_width=True)
    with col_btn2:
        analyze_expert = st.button("👑 Expert Board Review", type="secondary", use_container_width=True)
    with col_btn3:
        analyze_sepsis = st.button("🦠 Sepsis / Shock Protocol", use_container_width=True)

    if analyze_quick or analyze_expert or analyze_sepsis:
        if not is_engine_ready:
            st.error("AI Engine Offline — Check API Key in Streamlit Secrets.")
        elif not p_name:
            st.warning("Please enter or select a patient name.")
        elif not has_input:
            st.warning("Please provide clinical notes or upload an image.")
        else:
            if analyze_quick:
                analysis_type = "QUICK"
                prompt = f"""
                You are a Senior ICU Resident on duty in a Cardiac ICU, Kerala, India.
                Patient: {p_name} | Diagnosis Category: {diagnosis_category}
                Clinical Data: {full_notes}

                Provide a FAST, STRUCTURED analysis:
                1. WORKING DIAGNOSIS
                2. CRITICALITY LEVEL: Score 1-10 with label (RED=8-10 critical, YELLOW=4-7 guarded, GREEN=1-3 stable)
                3. IMMEDIATE ACTIONS (Next 30 minutes)
                4. INVESTIGATIONS ORDERED
                5. INITIAL TREATMENT PLAN
                6. DRUG-DRUG INTERACTIONS CHECK (flag any dangerous interactions)
                7. NURSE INSTRUCTIONS

                Be concise. Use Indian generic drug names where possible.
                WRITE IN PLAIN TEXT ONLY. NO ASTERISKS OR HASH SYMBOLS.
                At the end add exactly: TOPICS: [Topic1], [Topic2], [Topic3]
                """

            elif analyze_expert:
                analysis_type = "EXPERT"
                prompt = f"""
                You are a Multi-Disciplinary Expert Board in a Cardiac ICU, Kerala, India:
                - Senior Intensivist
                - Interventional Cardiologist
                - Nephrologist
                - Clinical Pharmacologist
                - Pulmonologist (if respiratory issues)

                Patient: {p_name} | Primary Category: {diagnosis_category}
                Clinical Data: {full_notes}

                Provide a COMPREHENSIVE EXPERT BOARD REVIEW:
                1. CRITICALITY SCORE: Strict 1-10 (10=imminent death). Label RED/YELLOW/GREEN.
                2. ABG ANALYSIS: If ABG data present, apply FULL Boston/Stewart method step-by-step.
                3. ECG INTERPRETATION: If ECG findings present, full systematic interpretation.
                4. MULTI-SPECIALTY PANEL VIEWS:
                   - Intensivist View
                   - Cardiologist View
                   - Nephrologist View (renal function, fluid balance)
                   - Pharmacologist View (DDI, dose adjustments for renal/hepatic)
                5. MASTER TREATMENT PROTOCOL (drug names, doses, routes, timing)
                6. MONITORING TARGETS (hourly, 4-hourly, daily)
                7. ESCALATION TRIGGERS (when to call senior/transfer)
                8. FAMILY COUNSELING POINTS (in simple language)

                WRITE IN PLAIN TEXT ONLY. NO ASTERISKS OR HASH SYMBOLS.
                At the end add exactly: TOPICS: [Topic1], [Topic2], [Topic3]
                """

            else:  # Sepsis
                analysis_type = "SEPSIS"
                prompt = f"""
                You are a Sepsis Response Expert in a Cardiac ICU, Kerala, India.
                Patient: {p_name} | Category: {diagnosis_category}
                Clinical Data: {full_notes}

                Apply THE SURVIVING SEPSIS CAMPAIGN 1-HOUR BUNDLE:
                1. SEPSIS SCREENING: Calculate qSOFA score and SOFA score if data available.
                2. SEPSIS-3 CRITERIA: Does this patient meet Sepsis-3 definition?
                3. SHOCK ASSESSMENT: Septic shock criteria? Cardiogenic shock? Mixed?
                4. 1-HOUR BUNDLE CHECKLIST:
                   - Blood cultures (before antibiotics)?
                   - Lactate level?
                   - IV fluid resuscitation (30ml/kg crystalloid)?
                   - Antibiotic choice (cover, dose, route)?
                   - Vasopressors if MAP <65?
                5. ANTIBIOTIC SELECTION: Best empiric regimen for Kerala resistance patterns.
                6. VASOPRESSOR PROTOCOL: Norepinephrine doses, escalation plan.
                7. SOURCE CONTROL: Identify and address source.
                8. MONITORING: Lactate clearance targets, MAP targets, UO targets.

                WRITE IN PLAIN TEXT ONLY. NO ASTERISKS OR HASH SYMBOLS.
                At the end add exactly: TOPICS: [Topic1], [Topic2], [Topic3]
                """

            with st.spinner(f"{'Expert Board convening' if analyze_expert else 'AI Radar scanning'}... Please wait."):
                try:
                    content_to_send = [prompt]
                    if uploaded_files:
                        for f in uploaded_files:
                            if f.name.lower().endswith(('png', 'jpg', 'jpeg')):
                                content_to_send.append(optimize_image(f))
                            elif f.name.lower().endswith('.pdf'):
                                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                                    tmp.write(f.read())
                                    tmp_path = tmp.name
                                gemini_file = genai.upload_file(path=tmp_path, mime_type='application/pdf')
                                content_to_send.append(gemini_file)

                    res_text   = smart_generate(content_to_send)
                    topics_list = []
                    if "TOPICS:" in res_text:
                        parts      = res_text.split("TOPICS:")
                        res_text   = parts[0].strip()
                        topics_raw = parts[1].strip()
                        topics_list = [t.strip().strip('[]') for t in topics_raw.split(",")]
                        st.session_state[f"topics_{p_name}"] = topics_list

                    # Save to DB
                    current_time = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
                    if p_name not in st.session_state.patients_db:
                        st.session_state.patients_db[p_name] = {"status": "Active", "history": [], "bed": "Unassigned"}
                        if patient_type == "New Admission" and bed_assign != "Unassigned":
                            st.session_state.patients_db[p_name]["bed"] = bed_assign
                            st.session_state.icu_beds[bed_assign] = p_name

                    entry = {
                        "date":      current_time,
                        "doctor":    st.session_state.current_user,
                        "raw_notes": full_notes[:2000],
                        "summary":   res_text,
                        "type":      analysis_type
                    }
                    st.session_state.patients_db[p_name]["history"].append(entry)

                    # Push to cloud
                    push_to_cloud({
                        "action":       "new_entry",
                        "patient_name": p_name,
                        "doctor":       st.session_state.current_user,
                        "raw_notes":    full_notes[:2000],
                        "summary":      res_text,
                        "date":         current_time,
                        "status":       "Active"
                    })

                    log_action(f"{analysis_type} analysis for {p_name}")
                    st.session_state[f'last_result_{p_name}'] = res_text
                    st.success(f"✅ Analysis complete & auto-saved for {p_name}!")

                except Exception as e:
                    st.error(f"AI Engine Error:\n{str(e)}")

    # Display last result
    key_res = f'last_result_{p_name}' if p_name else None
    if key_res and key_res in st.session_state:
        st.markdown("---")
        st.subheader("📋 AI Analysis Result")
        st.info(st.session_state[key_res])

        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            if st.button("📄 Generate & Download PDF Report"):
                try:
                    pdf_path = generate_pdf(
                        "CLINICAL ANALYSIS REPORT",
                        p_name,
                        st.session_state[key_res],
                        st.session_state.current_user
                    )
                    with open(pdf_path, "rb") as f:
                        st.download_button(
                            "📥 Download PDF",
                            data=f,
                            file_name=f"{p_name}_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                            mime="application/pdf"
                        )
                except Exception as e:
                    st.error(f"PDF Error: {e}")

        # Guideline section
        st.markdown("---")
        st.subheader("📚 AI-Suggested Learning Topics")
        auto_topics = st.session_state.get(f"topics_{p_name}", [])
        if auto_topics:
            sel_topic = st.selectbox("Study this case-related topic:", ["Choose..."] + auto_topics)
        else:
            sel_topic = "Choose..."
        custom_topic = st.text_input("Or enter your own topic:")
        final_topic  = custom_topic if custom_topic else (sel_topic if sel_topic != "Choose..." else "")

        if final_topic and st.button("📖 Generate Guideline PDF"):
            with st.spinner(f"Fetching ICU guidelines for: {final_topic}..."):
                try:
                    guide_prompt = f"""
                    Write a comprehensive ICU clinical guideline on: {final_topic}
                    Include: Definition, Diagnosis criteria, Management protocol, Drug doses, Monitoring parameters, and Complications.
                    Use Indian generic drug names. Reference international guidelines (AHA, ESC, SCCM) where applicable.
                    PLAIN TEXT ONLY. NO ASTERISKS OR HASH SYMBOLS.
                    """
                    guide_text = smart_generate([guide_prompt])
                    pdf_path   = generate_pdf(f"GUIDELINE: {final_topic.upper()}", "Academic Reference", guide_text, st.session_state.current_user)
                    with open(pdf_path, "rb") as f:
                        st.download_button(
                            "📥 Download Guideline PDF",
                            data=f,
                            file_name=f"Guideline_{final_topic.replace(' ', '_')}.pdf",
                            mime="application/pdf"
                        )
                except Exception as e:
                    st.error(f"Error: {e}")

# ============================================================
#   TAB: 📊 HOD DASHBOARD (Continuous Thread)
# ============================================================
with get_tab("📊 HOD Dashboard"):
    st.header("📊 HOD Dashboard — Complete Patient Files & Clinical Thread")

    col_hod1, col_hod2 = st.columns([3, 1])
    with col_hod1:
        view_filter = st.radio("Filter:", ["Active Patients", "Discharged Patients", "All Patients"], horizontal=True)
    with col_hod2:
        if st.button("🔄 Refresh from Cloud"):
            sync_from_cloud()
            st.rerun()

    db = st.session_state.patients_db
    if view_filter == "Active Patients":
        filtered = {k: v for k, v in db.items() if v.get("status") == "Active"}
    elif view_filter == "Discharged Patients":
        filtered = {k: v for k, v in db.items() if v.get("status") == "Discharged"}
    else:
        filtered = db

    if not filtered:
        st.info("No patients found for this filter.")
    else:
        for pt_name, pt_data in filtered.items():
            history = pt_data.get("history", [])
            latest  = history[-1] if history else {}
            adm_date = history[0].get("date", "Unknown") if history else "Unknown"
            badge = "🔴 ACTIVE" if pt_data.get("status") == "Active" else "✅ DISCHARGED"

            header = f"{badge}  |  🛏️ {pt_name}  |  Admitted: {adm_date}  |  Updates: {len(history)}"
            with st.expander(header, expanded=False):
                # Summary panel
                col_s1, col_s2, col_s3 = st.columns(3)
                with col_s1: st.caption(f"**Last Updated:** {latest.get('date','?')}")
                with col_s2: st.caption(f"**Last Doctor:** {latest.get('doctor','?')}")
                with col_s3: st.caption(f"**Bed:** {pt_data.get('bed','Unassigned')}")

                # Current master file
                st.markdown("**📝 Current Master Clinical File:**")
                edited_summary = st.text_area(
                    "HOD can edit this directly:",
                    value=latest.get("summary", ""),
                    height=200,
                    key=f"hod_edit_{pt_name}"
                )

                if st.button("💾 Save HOD Edits", key=f"save_edit_{pt_name}"):
                    if history:
                        st.session_state.patients_db[pt_name]["history"][-1]["summary"] = edited_summary
                        log_action(f"HOD edited file for {pt_name}")
                        st.success("Saved!")

                st.markdown("---")

                # ---- THE CLINICAL THREAD ----
                st.markdown("### 📈 Add Progress Note / New Investigations (Clinical Thread)")
                with st.container(border=True):
                    prog_notes = st.text_area(
                        "New progress note or findings:",
                        key=f"prog_{pt_name}",
                        height=80,
                        placeholder="Enter new vitals, ABG results, ECG changes, specialist review, response to treatment..."
                    )
                    prog_files = st.file_uploader(
                        "Upload new reports/images:",
                        type=['jpg', 'jpeg', 'png', 'pdf'],
                        accept_multiple_files=True,
                        key=f"prog_files_{pt_name}"
                    )
                    has_prog = bool(prog_notes.strip() or prog_files)

                    if st.button("🔄 Analyze Progress & Update Thread", type="primary", key=f"thread_{pt_name}"):
                        if not has_prog:
                            st.warning("Add notes or upload a report first.")
                        elif not is_engine_ready:
                            st.error("AI Engine offline.")
                        else:
                            with st.spinner("AI comparing new data with previous trajectory..."):
                                try:
                                    thread_prompt = f"""
                                    You are a Senior ICU Registrar updating the clinical thread for patient: {pt_name}.

                                    PREVIOUS CLINICAL SUMMARY (from last entry):
                                    {edited_summary}

                                    NEW PROGRESS NOTE / NEW REPORTS:
                                    {prog_notes}

                                    Perform a TRAJECTORY COMPARISON ANALYSIS:
                                    1. COMPARISON: Compare today's findings with the previous summary. Is the patient IMPROVING, DETERIORATING, or STABLE? Be specific about which parameters changed.
                                    2. UPDATED CRITICALITY SCORE: 1-10 with RED/YELLOW/GREEN label.
                                    3. RESPONSE TO TREATMENT: Is the current treatment working? What evidence?
                                    4. UPDATED TREATMENT ADJUSTMENTS: What needs to change (add/stop/modify drugs, investigations)?
                                    5. PLAN FOR NEXT 24 HOURS.
                                    6. WARD ROUND SUMMARY (for HOD round — concise 5-line brief).

                                    PLAIN TEXT ONLY. NO ASTERISKS OR HASH SYMBOLS.
                                    """
                                    content = [thread_prompt]
                                    if prog_files:
                                        for f in prog_files:
                                            if f.name.lower().endswith(('png', 'jpg', 'jpeg')):
                                                content.append(optimize_image(f))
                                    update_text = smart_generate(content)

                                    current_time = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
                                    new_entry = {
                                        "date":      current_time,
                                        "doctor":    st.session_state.current_user,
                                        "raw_notes": prog_notes,
                                        "summary":   update_text,
                                        "type":      "PROGRESS"
                                    }
                                    st.session_state.patients_db[pt_name]["history"].append(new_entry)
                                    push_to_cloud({
                                        "action": "new_entry",
                                        "patient_name": pt_name,
                                        "doctor": st.session_state.current_user,
                                        "raw_notes": prog_notes,
                                        "summary": update_text,
                                        "date": current_time,
                                        "status": "Active"
                                    })
                                    log_action(f"Progress thread updated for {pt_name}")
                                    st.success("Thread updated!")
                                    st.info(update_text)
                                except Exception as e:
                                    st.error(f"Error: {e}")

                st.markdown("---")

                # Full history timeline
                if st.checkbox(f"📅 Show Full History Timeline for {pt_name}", key=f"timeline_{pt_name}"):
                    for i, h in enumerate(reversed(history)):
                        with st.container(border=True):
                            st.caption(f"**Entry #{len(history)-i}** | {h.get('date','')} | By: {h.get('doctor','')} | Type: {h.get('type','')}")
                            st.text(h.get("summary", "")[:500] + "..." if len(h.get("summary","")) > 500 else h.get("summary",""))

                st.markdown("---")

                # Discharge section
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    if pt_data.get("status") == "Active":
                        if st.button(f"✅ Generate Discharge Summary for {pt_name}", key=f"disch_{pt_name}"):
                            with st.spinner("Generating discharge summary..."):
                                try:
                                    all_summaries = "\n\n---\n\n".join([h.get("summary", "") for h in history[-3:]])
                                    disch_prompt = f"""
                                    Generate a FORMAL HOSPITAL DISCHARGE SUMMARY for patient: {pt_name}
                                    Based on their clinical journey in our Cardiac ICU, Kerala.

                                    Clinical History from ICU Stay:
                                    {all_summaries}

                                    Include:
                                    1. ADMISSION DIAGNOSIS
                                    2. SUMMARY OF ICU STAY
                                    3. KEY INVESTIGATIONS AND RESULTS
                                    4. PROCEDURES PERFORMED
                                    5. DISCHARGE CONDITION
                                    6. DISCHARGE MEDICATIONS (with doses)
                                    7. FOLLOW-UP INSTRUCTIONS
                                    8. RED FLAG SYMPTOMS (when to return to ER)
                                    9. ACTIVITY RESTRICTIONS
                                    10. DIET INSTRUCTIONS

                                    Under: Dr. Alok Sehgal (HOD, Sr. Interventional Cardiologist)
                                    Attending: {st.session_state.current_user}
                                    PLAIN TEXT ONLY. NO ASTERISKS.
                                    """
                                    disch_text = smart_generate([disch_prompt])
                                    pdf_path   = generate_pdf("DISCHARGE SUMMARY", pt_name, disch_text, st.session_state.current_user)
                                    with open(pdf_path, "rb") as f:
                                        st.download_button(
                                            f"📥 Download Discharge Summary",
                                            data=f,
                                            file_name=f"{pt_name}_Discharge_{datetime.datetime.now().strftime('%Y%m%d')}.pdf",
                                            mime="application/pdf",
                                            key=f"dl_disch_{pt_name}"
                                        )
                                except Exception as e:
                                    st.error(f"Error: {e}")
                with col_d2:
                    if pt_data.get("status") == "Active":
                        if st.button(f"🚪 Mark {pt_name} as Discharged", key=f"mark_disch_{pt_name}"):
                            st.session_state.patients_db[pt_name]["status"] = "Discharged"
                            # Free the bed
                            for bed, occ in st.session_state.icu_beds.items():
                                if occ == pt_name:
                                    st.session_state.icu_beds[bed] = "Empty"
                            push_to_cloud({"action": "discharge", "patient_name": pt_name, "status": "Discharged", "date": str(datetime.datetime.now())})
                            log_action(f"Discharged: {pt_name}")
                            st.success(f"{pt_name} marked as discharged.")
                            st.rerun()

# ============================================================
#   TAB: 📉 FLOWSHEET & TRENDS
# ============================================================
with get_tab("📉 Flowsheet & Trends"):
    st.header("📉 ICU Flowsheet & Vital Trends")

    active_pts_list = [nm for nm, d in st.session_state.patients_db.items() if d.get("status") == "Active"]
    if not active_pts_list:
        st.info("No active patients.")
    else:
        sel_pt_flow = st.selectbox("Select Patient for Flowsheet:", active_pts_list, key="flow_patient")
        st.markdown("---")

        # Manual vitals input table
        st.subheader("📝 Enter Hourly Vitals")
        if f"flowsheet_{sel_pt_flow}" not in st.session_state:
            st.session_state[f"flowsheet_{sel_pt_flow}"] = []

        col_f1, col_f2, col_f3, col_f4, col_f5, col_f6, col_f7 = st.columns(7)
        with col_f1: f_time = st.text_input("Time", datetime.datetime.now().strftime("%H:%M"), key="f_time")
        with col_f2: f_bp   = st.text_input("BP",   "120/80", key="f_bp")
        with col_f3: f_hr   = st.number_input("HR",  0, 300, 80, key="f_hr")
        with col_f4: f_rr   = st.number_input("RR",  0, 60, 16, key="f_rr")
        with col_f5: f_spo2 = st.number_input("SpO2", 0, 100, 98, key="f_spo2")
        with col_f6: f_temp = st.number_input("Temp", 30.0, 43.0, 37.0, 0.1, key="f_temp")
        with col_f7: f_uo   = st.number_input("UO (ml/hr)", 0, 1000, 50, key="f_uo")

        if st.button("➕ Add Vitals to Flowsheet"):
            st.session_state[f"flowsheet_{sel_pt_flow}"].append({
                "Time": f_time, "BP": f_bp, "HR": f_hr,
                "RR": f_rr, "SpO2": f_spo2, "Temp": f_temp, "UO": f_uo
            })
            log_action(f"Vitals added for {sel_pt_flow}")
            st.success("Vitals added!")

        flowsheet_data = st.session_state.get(f"flowsheet_{sel_pt_flow}", [])
        if flowsheet_data:
            df_flow = pd.DataFrame(flowsheet_data)
            st.dataframe(df_flow, use_container_width=True, hide_index=True)

            # Charts
            st.subheader("📈 Trend Charts")
            col_ch1, col_ch2 = st.columns(2)
            with col_ch1:
                try:
                    st.line_chart(df_flow.set_index("Time")[["HR", "RR"]])
                    st.caption("Heart Rate & Respiratory Rate Trend")
                except: pass
            with col_ch2:
                try:
                    st.line_chart(df_flow.set_index("Time")[["SpO2"]])
                    st.caption("SpO2 Trend")
                except: pass

            if st.button("📄 Download Flowsheet PDF"):
                try:
                    flow_text = df_flow.to_string(index=False)
                    pdf_path  = generate_pdf("ICU FLOWSHEET", sel_pt_flow, flow_text, st.session_state.current_user)
                    with open(pdf_path, "rb") as f:
                        st.download_button("📥 Download", data=f, file_name=f"{sel_pt_flow}_Flowsheet.pdf", mime="application/pdf")
                except Exception as e:
                    st.error(f"PDF error: {e}")

# ============================================================
#   TAB: 🚨 EARLY WARNING SYSTEM (NEWS2 + APACHE)
# ============================================================
with get_tab("🚨 Early Warning"):
    st.header("🚨 Early Warning System — NEWS2 Score & Deterioration Radar")

    col_ew1, col_ew2 = st.columns(2)
    with col_ew1:
        st.subheader("🩺 NEWS2 Score Calculator")
        ew_rr   = st.number_input("Respiratory Rate (/min):", 0, 60, 16, key="ew_rr")
        ew_spo2 = st.number_input("SpO2 (%):", 0, 100, 97, key="ew_spo2")
        ew_o2   = st.checkbox("On supplemental oxygen?", key="ew_o2")
        ew_sbp  = st.number_input("Systolic BP (mmHg):", 50, 250, 120, key="ew_sbp")
        ew_hr   = st.number_input("Heart Rate (bpm):", 0, 300, 80, key="ew_hr")
        ew_temp = st.number_input("Temperature (°C):", 30.0, 43.0, 37.0, 0.1, key="ew_temp")
        ew_avpu = st.selectbox("Consciousness (AVPU):", ["Alert", "Confusion/New", "Voice", "Pain", "Unresponsive"])
        ew_cap  = st.checkbox("Hypercapnic respiratory failure (COPD)?", key="ew_cap")

        if st.button("📊 Calculate NEWS2 Score", type="primary"):
            score, risk, color, action = calc_news2(ew_rr, ew_spo2, ew_o2, ew_sbp, ew_hr, ew_temp, ew_avpu, ew_cap)
            st.markdown(f"""
            <div style="background:{'#8b1a1a' if risk in ['HIGH','MEDIUM-HIGH'] else ('#7a6b00' if risk=='MEDIUM' else '#2d5a27')};
                        padding:20px;border-radius:12px;color:white;text-align:center;margin:10px 0">
              <h2 style="margin:0">{color} NEWS2 Score: {score}</h2>
              <h3 style="margin:5px 0">Risk Level: {risk}</h3>
              <p style="margin:5px 0">ACTION: {action}</p>
            </div>
            """, unsafe_allow_html=True)
            log_action(f"NEWS2 calculated: Score {score} ({risk})")

    with col_ew2:
        st.subheader("🦠 Sepsis Screening (qSOFA)")
        q_rr     = st.number_input("Respiratory Rate:", 0, 60, 16, key="q_rr")
        q_gcs    = st.number_input("GCS:", 3, 15, 15, key="q_gcs")
        q_sbp    = st.number_input("Systolic BP (mmHg):", 50, 250, 110, key="q_sbp")
        q_fever  = st.checkbox("Temperature > 38°C or < 36°C?")
        q_wbc    = st.checkbox("WBC > 12,000 or < 4,000?")
        q_source = st.checkbox("Suspected infection source?")

        if st.button("🦠 Calculate qSOFA & Sepsis Risk", type="primary"):
            qsofa = 0
            if q_rr >= 22: qsofa += 1
            if q_gcs < 15: qsofa += 1
            if q_sbp <= 100: qsofa += 1
            sirs_count = sum([q_fever, q_wbc, q_rr >= 20])

            st.markdown(f"""
            <div style="background:{'#8b1a1a' if qsofa >= 2 else '#2d5a27'};
                        padding:20px;border-radius:12px;color:white;text-align:center">
              <h2>qSOFA Score: {qsofa}/3</h2>
              <p>{'HIGH SEPSIS RISK — Activate Sepsis Protocol!' if qsofa >= 2 else 'Low-Moderate Risk — Monitor closely'}</p>
              <p>SIRS Criteria Met: {sirs_count}/3</p>
            </div>
            """, unsafe_allow_html=True)
            log_action(f"qSOFA: {qsofa}/3")

    st.markdown("---")
    st.subheader("🚨 AI Deterioration Analysis")
    deter_notes = st.text_area("Paste current vitals/trends for AI deterioration risk assessment:", height=100)
    if st.button("🧠 AI Deterioration Analysis") and deter_notes:
        with st.spinner("AI analyzing deterioration risk..."):
            try:
                deter_prompt = f"""
                You are a Critical Care AI Deterioration Radar.
                Patient data: {deter_notes}
                
                Analyze:
                1. DETERIORATION RISK: LOW / MEDIUM / HIGH / CRITICAL
                2. WARNING SIGNS: List specific concerning parameters.
                3. PREDICTED COMPLICATIONS: What might happen in next 4-12 hours?
                4. IMMEDIATE INTERVENTIONS: What must be done NOW?
                5. MONITORING ESCALATION: Frequency of checks?
                
                PLAIN TEXT ONLY. NO ASTERISKS.
                """
                deter_result = smart_generate([deter_prompt])
                st.info(deter_result)
                log_action("AI Deterioration Analysis run")
            except Exception as e:
                st.error(str(e))

# ============================================================
#   TAB: 💊 MEDICATION SAFETY
# ============================================================
with get_tab("💊 Medication Safety"):
    st.header("💊 Medication Safety — DDI Checker & Dose Calculator")

    col_med1, col_med2 = st.columns(2)
    with col_med1:
        st.subheader("⚠️ Drug-Drug Interaction Checker")
        st.caption("Enter all medications the patient is on — one per line.")
        med_list = st.text_area(
            "Patient's Medication List:",
            height=200,
            placeholder="Example:\nAspirin 75mg OD\nClopidogrel 75mg OD\nEnoxaparin 40mg BD\nFurosemide 40mg IV BD\nAmiodarone 200mg TDS\nWarfarin 5mg OD"
        )
        renal_fn   = st.selectbox("Renal Function:", ["Normal", "Mild impairment (CrCl 60-90)", "Moderate (CrCl 30-60)", "Severe (CrCl 15-30)", "ESRD/Dialysis"])
        hepatic_fn = st.selectbox("Hepatic Function:", ["Normal", "Child-Pugh A (Mild)", "Child-Pugh B (Moderate)", "Child-Pugh C (Severe)"])

        if st.button("🔬 Full Pharmacology Safety Scan", type="primary"):
            if not med_list.strip():
                st.warning("Please enter the medication list.")
            elif not is_engine_ready:
                st.error("AI engine offline.")
            else:
                with st.spinner("Clinical Pharmacologist AI scanning..."):
                    try:
                        med_prompt = f"""
                        You are a Senior Clinical Pharmacologist in a Cardiac ICU.
                        Patient's medications: {med_list}
                        Renal Function: {renal_fn}
                        Hepatic Function: {hepatic_fn}

                        Perform a COMPLETE PHARMACOLOGY SAFETY ANALYSIS:
                        1. DANGEROUS DDIs: List ALL clinically significant drug-drug interactions with severity (CONTRAINDICATED / MAJOR / MODERATE / MINOR).
                        2. DOSE ADJUSTMENTS NEEDED: For renal impairment, list drugs needing dose reduction and the adjusted dose.
                        3. HEPATIC ADJUSTMENTS: For hepatic impairment, list drugs needing modification.
                        4. MONITORING PARAMETERS: Specific levels/tests to monitor for each high-risk drug.
                        5. ANTICOAGULATION SAFETY: If any anticoagulants — bleeding risk assessment, monitoring requirements.
                        6. RECOMMENDATIONS: Suggested alternatives for any contraindicated combinations.

                        PLAIN TEXT ONLY. NO ASTERISKS. Be very specific with drug names and doses.
                        """
                        med_result = smart_generate([med_prompt])
                        st.success("Pharmacology Safety Scan Complete!")
                        st.info(med_result)
                        log_action("Medication safety scan run")

                        if st.button("📄 Download Medication Safety Report"):
                            pdf_path = generate_pdf("MEDICATION SAFETY REPORT", "Patient Review", med_result, st.session_state.current_user)
                            with open(pdf_path, "rb") as f:
                                st.download_button("📥 Download", data=f, file_name="Medication_Safety.pdf", mime="application/pdf")
                    except Exception as e:
                        st.error(str(e))

    with col_med2:
        st.subheader("💉 Critical Care Dose Calculator")
        st.caption("Common ICU drug infusions — dose calculator")

        calc_drug = st.selectbox("Select Drug:", [
            "Norepinephrine (Norad)",
            "Dopamine",
            "Dobutamine",
            "Adrenaline (Epinephrine)",
            "Nitroglycerin (GTN)",
            "Heparin Infusion",
            "Insulin Infusion",
            "Furosemide Infusion",
            "Midazolam Infusion",
            "Morphine Infusion",
            "Amiodarone Loading",
        ])
        calc_weight = st.number_input("Patient Weight (kg):", 30.0, 200.0, 65.0, 0.5)
        calc_dose   = st.number_input("Desired Dose (mcg/kg/min or units/hr):", 0.0, 100.0, 0.1, 0.01)
        calc_conc   = st.number_input("Drug Concentration (mcg/ml):", 0.1, 10000.0, 100.0, 0.1)

        if st.button("🧮 Calculate Infusion Rate"):
            if calc_drug in ["Norepinephrine (Norad)", "Dopamine", "Dobutamine", "Adrenaline (Epinephrine)"]:
                rate_ml_hr = (calc_dose * calc_weight * 60) / calc_conc
                st.success(f"Infusion Rate: **{rate_ml_hr:.2f} ml/hr**")
                st.caption(f"For {calc_drug} at {calc_dose} mcg/kg/min for {calc_weight}kg patient")
            else:
                rate_ml_hr = (calc_dose * 60) / calc_conc
                st.success(f"Infusion Rate: **{rate_ml_hr:.2f} ml/hr**")
            log_action(f"Dose calculator: {calc_drug} = {rate_ml_hr:.2f} ml/hr")

# ============================================================
#   TAB: 🔄 SHIFT HANDOVER
# ============================================================
with get_tab("🔄 Shift Handover"):
    st.header("🔄 Shift Handover — Structured ISBAR Handover Notes")
    st.caption("Generate AI-powered shift handover for all active patients in one click.")

    active_for_handover = {k: v for k, v in st.session_state.patients_db.items() if v.get("status") == "Active"}

    col_ho1, col_ho2 = st.columns(2)
    with col_ho1:
        outgoing_dr = st.text_input("Outgoing Doctor:", value=st.session_state.current_user.split("(")[0].strip())
    with col_ho2:
        incoming_dr = st.text_input("Incoming Doctor:", placeholder="Name of next duty doctor")

    additional_notes = st.text_area("Additional Handover Notes (pending tasks, concerns):", height=80)

    if st.button("🔄 Generate AI ISBAR Handover for ALL Active Patients", type="primary"):
        if not active_for_handover:
            st.warning("No active patients to handover.")
        elif not is_engine_ready:
            st.error("AI engine offline.")
        else:
            with st.spinner("Generating structured ISBAR handover..."):
                try:
                    handover_content = []
                    for pt_name, pt_data in active_for_handover.items():
                        history = pt_data.get("history", [])
                        latest_summary = history[-1].get("summary", "") if history else "No data"

                        h_prompt = f"""
                        Generate a concise ISBAR (Identify, Situation, Background, Assessment, Recommendation) handover for:
                        Patient: {pt_name}
                        Latest Clinical Summary: {latest_summary[:800]}

                        Format: 5 bullet points maximum, very concise, focus on:
                        - Current status and acuity
                        - Active issues and concerns
                        - Current medications/infusions
                        - Pending results/actions
                        - What the incoming doctor must watch for

                        PLAIN TEXT ONLY. NO ASTERISKS.
                        """
                        h_result = smart_generate([h_prompt])
                        handover_content.append(f"--- {pt_name} ---\n{h_result}")

                    full_handover = f"""
SHIFT HANDOVER REPORT
=====================
Date: {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}
Outgoing: {outgoing_dr}
Incoming: {incoming_dr}
Active Patients: {len(active_for_handover)}

{chr(10).join(handover_content)}

ADDITIONAL NOTES:
{additional_notes}

Handover completed and acknowledged.
                    """
                    st.session_state.handover_notes.insert(0, {
                        "date": str(datetime.datetime.now()),
                        "outgoing": outgoing_dr,
                        "incoming": incoming_dr,
                        "content": full_handover
                    })
                    log_action(f"Handover: {outgoing_dr} → {incoming_dr}")
                    st.success("Handover generated!")
                    st.info(full_handover)

                    pdf_path = generate_pdf("SHIFT HANDOVER REPORT", "All Active Patients", full_handover, outgoing_dr)
                    with open(pdf_path, "rb") as f:
                        st.download_button(
                            "📥 Download Handover PDF",
                            data=f,
                            file_name=f"Handover_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                            mime="application/pdf"
                        )
                except Exception as e:
                    st.error(str(e))

    # Previous handovers
    if st.session_state.handover_notes:
        st.markdown("---")
        st.subheader("📋 Previous Handovers (This Session)")
        for h in st.session_state.handover_notes[:3]:
            with st.expander(f"Handover — {h['outgoing']} → {h['incoming']} | {h['date'][:16]}"):
                st.text(h["content"][:1000])

# ============================================================
#   TAB: 🔬 ACADEMIC VAULT
# ============================================================
with get_tab("🔬 Academic Vault"):
    st.header("🔬 Academic Vault — CME, Guidelines & Research")

    av_topic = st.text_input(
        "Enter clinical topic for academic deep-dive:",
        placeholder="e.g., Management of Cardiogenic Shock, STEMI guidelines 2024, Vasopressor use in ICU..."
    )

    col_av1, col_av2, col_av3 = st.columns(3)
    with col_av1: av_type = st.selectbox("Content Type:", ["Clinical Guideline", "Case Discussion", "Drug Protocol", "Procedure Guide", "Research Summary", "CME Quiz"])
    with col_av2: av_level = st.selectbox("Level:", ["Resident (Basic)", "Senior Resident (Intermediate)", "Consultant (Advanced)", "Fellowship Level (Expert)"])
    with col_av3: av_ref   = st.selectbox("Reference Guidelines:", ["AHA/ACC 2024", "ESC 2024", "SCCM/ESICM", "Indian Guidelines (CSI/ISCCM)", "Multiple Guidelines"])

    if st.button("📚 Generate Academic Content", type="primary"):
        if not av_topic.strip():
            st.warning("Please enter a topic.")
        elif not is_engine_ready:
            st.error("AI engine offline.")
        else:
            with st.spinner(f"Fetching {av_type} on {av_topic}..."):
                try:
                    av_prompt = f"""
                    You are a world-class medical educator and intensivist, creating content for a Cardiac ICU in Kerala, India.
                    Topic: {av_topic}
                    Content Type: {av_type}
                    Target Level: {av_level}
                    Reference: {av_ref}

                    Generate a comprehensive, clinically accurate, and up-to-date {av_type} covering:
                    - Definition and pathophysiology
                    - Diagnostic criteria with specific values
                    - Step-by-step management protocol
                    - Drug doses (use Indian generic names, mention brand names where helpful)
                    - Monitoring parameters and targets
                    - Complications and how to avoid them
                    - Key clinical pearls (what not to miss)
                    - Summary table of key points

                    {"Include 5 MCQ-style questions with answers for CME assessment." if av_type == "CME Quiz" else ""}

                    WRITE IN PLAIN TEXT ONLY. NO ASTERISKS OR HASH SYMBOLS. Be thorough and educational.
                    """
                    av_result = smart_generate([av_prompt])
                    log_action(f"Academic content: {av_topic}")
                    st.success("Academic content generated!")
                    st.info(av_result)

                    col_pdf1, col_pdf2 = st.columns(2)
                    with col_pdf1:
                        pdf_path = generate_pdf(f"{av_type.upper()}: {av_topic.upper()}", "Academic Reference", av_result, st.session_state.current_user)
                        with open(pdf_path, "rb") as f:
                            st.download_button(
                                "📥 Download as PDF",
                                data=f,
                                file_name=f"Academic_{av_topic.replace(' ', '_')[:30]}.pdf",
                                mime="application/pdf"
                            )
                except Exception as e:
                    st.error(str(e))

    st.markdown("---")
    st.subheader("💡 Quick Reference Cards")
    quick_topics = [
        "STEMI Door-to-Balloon Protocol",
        "Cardiogenic Shock Management",
        "Acute Pulmonary Edema Treatment",
        "Ventricular Fibrillation / VT Management",
        "Hypertensive Emergency Drugs & Doses",
        "Anticoagulation in AF + ACS",
        "AKI in ICU — Fluid & Electrolyte Management",
        "Septic Shock — Surviving Sepsis Bundle",
        "NIV (BIPAP) Setup & Weaning",
        "Ventilator Management Basics"
    ]
    selected_quick = st.selectbox("Quick Reference Topics:", quick_topics)
    if st.button("⚡ Quick Generate (1-Page Reference Card)"):
        with st.spinner("Generating quick reference card..."):
            try:
                quick_prompt = f"""
                Create a concise 1-PAGE QUICK REFERENCE CARD for: {selected_quick}
                Include ONLY the most critical and actionable information:
                - 3-5 diagnostic criteria
                - 5-8 step management protocol
                - Key drug doses
                - 3 critical monitoring points
                - 2 common mistakes to avoid
                
                Format like a bedside reference card. Very concise. PLAIN TEXT. NO ASTERISKS.
                """
                quick_result = smart_generate([quick_prompt])
                st.success("Quick reference card ready!")
                st.info(quick_result)
                log_action(f"Quick reference: {selected_quick}")
            except Exception as e:
                st.error(str(e))

# ============================================================
# FOOTER
# ============================================================
st.markdown("---")
st.markdown("""
<div style="text-align:center;color:gray;font-size:12px">
Dr. Gill's Cardiac & Critical Care ICU Command System v2.0 | Kerala, India | 
AI-Powered by Google Gemini | Built for demonstration purposes | 
Consult qualified clinicians for all medical decisions
</div>
""", unsafe_allow_html=True)
