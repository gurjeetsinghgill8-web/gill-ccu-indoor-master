import streamlit as st
import os
import requests
import pandas as pd
import tempfile
import datetime
import random
import string

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

try:
    from fpdf import FPDF
    FPDF_AVAILABLE = True
except ImportError:
    FPDF_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="Dr. Gill's Cardiac ICU v2.0",
    layout="wide",
    page_icon="🏥",
    initial_sidebar_state="collapsed"
)

# ============================================================
# MASTER PASSWORD & CREDENTIALS
# ============================================================
MASTER_PASSWORD = "GILL@ICU#2025"
MASTER_NAME     = "Dr. G.S. Gill (MASTER ADMIN)"

WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbwIBxF5vh7uvdDnRblpyhfpQCtpcxWN3MlGjbt3SUeEO5KH3c9AIcU91BzeKVQKCn_L/exec"

DEFAULT_DOCTORS = {
    "9999": {"name": "Dr. Alok Sehgal",  "role": "Senior Interventional Cardiologist", "access": "HOD"},
    "1234": {"name": "Dr. G.S. Gill",    "role": "Cardiac Physician",                  "access": "Senior"},
    "0000": {"name": "Dr. Shivam Tomar", "role": "Cardiac Physician",                  "access": "Resident"},
}

# ============================================================
# SESSION STATE
# ============================================================
if "logged_in"      not in st.session_state: st.session_state.logged_in      = False
if "current_user"   not in st.session_state: st.session_state.current_user   = None
if "is_master"      not in st.session_state: st.session_state.is_master      = False
if "patients_db"    not in st.session_state: st.session_state.patients_db    = {}
if "doctors_db"     not in st.session_state: st.session_state.doctors_db     = DEFAULT_DOCTORS.copy()
if "icu_beds"       not in st.session_state: st.session_state.icu_beds       = {f"Bed {i}": "Empty" for i in range(1, 13)}
if "audit_log"      not in st.session_state: st.session_state.audit_log      = []
if "handover_notes" not in st.session_state: st.session_state.handover_notes = []

# ============================================================
# API SETUP
# ============================================================
active_key = ""
if "GEMINI_API_KEY" in st.secrets:
    active_key = st.secrets["GEMINI_API_KEY"]
else:
    active_key = os.getenv("GEMINI_API_KEY", "")

is_engine_ready = False
if GENAI_AVAILABLE and active_key and active_key.startswith("AIza"):
    try:
        genai.configure(api_key=active_key)
        is_engine_ready = True
    except Exception:
        pass

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def log_action(text):
    ts   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = st.session_state.current_user or "Unknown"
    st.session_state.audit_log.insert(0, f"[{ts}] {user} → {text}")
    if len(st.session_state.audit_log) > 300:
        st.session_state.audit_log = st.session_state.audit_log[:300]

def generate_pin():
    existing = set(st.session_state.doctors_db.keys())
    while True:
        p = ''.join(random.choices(string.digits, k=4))
        if p not in existing:
            return p

def optimize_image(f):
    if not PIL_AVAILABLE:
        return f
    img = Image.open(f)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img.thumbnail((1200, 1200))
    return img

def smart_generate(contents):
    if not GENAI_AVAILABLE:
        raise Exception("google-generativeai library not installed.")
    if not is_engine_ready:
        raise Exception("API Key not configured. Add GEMINI_API_KEY in Streamlit Secrets.")

    models_priority = [
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
        "gemini-1.5-pro",
        "gemini-2.0-flash",
        "gemini-pro",
    ]

    errors = []
    for m_name in models_priority:
        try:
            model  = genai.GenerativeModel(m_name)
            result = model.generate_content(contents)
            if result and result.text:
                return result.text.replace('**','').replace('##','').replace('###','').replace('#','')
        except Exception as e:
            errors.append(f"{m_name}: {str(e)}")
            continue

    # Try dynamic list as fallback
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                try:
                    model  = genai.GenerativeModel(m.name)
                    result = model.generate_content(contents)
                    if result and result.text:
                        return result.text.replace('**','').replace('##','').replace('###','')
                except Exception as e:
                    errors.append(f"{m.name}: {str(e)}")
    except Exception as e:
        errors.append(f"list_models: {str(e)}")

    raise Exception("All AI models failed:\n" + "\n".join(errors))

def sync_from_cloud():
    if not WEBHOOK_URL.startswith("http"):
        return
    try:
        res = requests.get(WEBHOOK_URL, timeout=10)
        if res.status_code == 200:
            cloud_data = res.json()
            new_db = {}
            for row in cloud_data:
                p = row.get("patient_name","").strip()
                if not p: continue
                status = row.get("status","Active")
                if p not in new_db:
                    new_db[p] = {"status": status, "history": [], "bed": "Unassigned"}
                if status == "Discharged":
                    new_db[p]["status"] = "Discharged"
                new_db[p]["history"].append({
                    "date":      row.get("date", str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))),
                    "doctor":    row.get("doctor","Unknown"),
                    "raw_notes": row.get("raw_notes",""),
                    "summary":   row.get("summary",""),
                })
            st.session_state.patients_db = new_db
    except Exception:
        pass

def push_to_cloud(payload):
    if not WEBHOOK_URL.startswith("http"): return
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=10)
    except Exception:
        pass

def generate_pdf(title, patient_name, text_content, doctor_name=""):
    if not FPDF_AVAILABLE:
        return None
    pdf = FPDF()
    pdf.add_page()
    pdf.set_fill_color(10, 50, 100)
    pdf.rect(0, 0, 210, 22, 'F')
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", 'B', 13)
    pdf.cell(0, 8,  txt="DR. GILL'S CARDIAC & CRITICAL CARE ICU — KERALA", ln=True, align='C')
    pdf.set_font("Arial", size=9)
    pdf.cell(0, 7,  txt="AI Clinical Decision Support System v2.0", ln=True, align='C')
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)
    pdf.set_font("Arial", 'B', 13)
    pdf.cell(0, 9,  txt=title.upper(), ln=True, align='C')
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)
    pdf.set_font("Arial", 'B', 9)
    pdf.set_fill_color(230, 240, 255)
    pdf.cell(0, 7, f"  Patient: {patient_name}", ln=True, fill=True)
    pdf.cell(0, 7, f"  HOD: Dr. Alok Sehgal (Sr. Interventional Cardiologist)  |  Doctor: {doctor_name}", ln=True, fill=True)
    pdf.cell(0, 7, f"  Generated: {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}", ln=True, fill=True)
    pdf.ln(4)
    pdf.set_font("Arial", size=10)
    clean = text_content.replace('**','').replace('*','-').replace('#','')
    clean = clean.encode('latin-1','replace').decode('latin-1')
    pdf.multi_cell(0, 6, txt=clean)
    pdf.set_y(-18)
    pdf.set_font("Arial",'I',7)
    pdf.set_text_color(120,120,120)
    pdf.cell(0, 5, "CONFIDENTIAL — FOR CLINICAL USE ONLY | Dr. Gill's ICU App v2.0 | Kerala", align='C')
    tmpdir  = tempfile.mkdtemp()
    fpath   = os.path.join(tmpdir, f"{patient_name}_{title.replace(' ','_')[:30]}.pdf")
    pdf.output(fpath)
    return fpath

def calc_news2(rr, spo2, supp_o2, sbp, hr, temp, avpu):
    s = 0
    if rr <= 8 or rr >= 25: s += 3
    elif 9  <= rr <= 11:    s += 1
    elif 21 <= rr <= 24:    s += 2
    if spo2 <= 91:          s += 3
    elif 92 <= spo2 <= 93:  s += 2
    elif 94 <= spo2 <= 95:  s += 1
    if supp_o2:             s += 2
    if sbp <= 90 or sbp >= 220: s += 3
    elif 91  <= sbp <= 100: s += 2
    elif 101 <= sbp <= 110: s += 1
    if hr <= 40 or hr >= 131:   s += 3
    elif 41 <= hr <= 50 or 111 <= hr <= 130: s += 2
    elif 91 <= hr <= 110:   s += 1
    if temp <= 35.0:        s += 3
    elif temp <= 36.0:      s += 1
    elif temp >= 39.1:      s += 2
    elif temp >= 38.1:      s += 1
    avpu_map = {"Alert":0,"Confusion/New":3,"Voice":3,"Pain":3,"Unresponsive":3}
    s += avpu_map.get(avpu, 0)
    if s >= 7:   return s, "HIGH",        "🔴", "IMMEDIATE senior review — consider ICU Level 3"
    elif s >= 5: return s, "MEDIUM-HIGH", "🟠", "Urgent review within 30 minutes"
    elif s >= 3: return s, "MEDIUM",      "🟡", "Increase monitoring, review within 1 hour"
    else:        return s, "LOW",         "🟢", "Continue routine monitoring"

# ============================================================
# LOGIN SCREEN
# ============================================================
if not st.session_state.logged_in:
    sync_from_cloud()
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("""
        <div style='background:linear-gradient(135deg,#0a1628,#1a3a6e);
                    padding:35px;border-radius:16px;text-align:center;color:white;margin-bottom:20px'>
          <h2 style='margin:0'>🏥 Dr. Gill's Cardiac ICU</h2>
          <h3 style='margin:5px 0;color:#a0c4e8'>Command System v2.0 — Kerala</h3>
          <p style='color:#7098c0;margin:0'>AI-Powered Clinical Decision Support</p>
        </div>
        """, unsafe_allow_html=True)

        pin_input = st.text_input("Enter PIN or Master Password:", type="password", placeholder="4-digit PIN or Master Password")

        if st.button("🔐 Login", type="primary", use_container_width=True):
            if pin_input == MASTER_PASSWORD:
                st.session_state.logged_in    = True
                st.session_state.current_user = MASTER_NAME
                st.session_state.is_master    = True
                log_action("MASTER LOGIN")
                st.rerun()
            elif pin_input in st.session_state.doctors_db:
                doc = st.session_state.doctors_db[pin_input]
                st.session_state.logged_in    = True
                st.session_state.current_user = f"{doc['name']} ({doc['role']})"
                st.session_state.is_master    = False
                log_action("Doctor LOGIN")
                st.rerun()
            else:
                st.error("Invalid PIN or Password. Access Denied.")
        st.caption("🔒 Authorized Personnel Only")
    st.stop()

# ============================================================
# HEADER
# ============================================================
h1, h2, h3 = st.columns([5,4,1])
with h1:
    badge = " 👑 MASTER ADMIN" if st.session_state.is_master else ""
    st.markdown(f"### 🏥 Dr. Gill's Cardiac ICU v2.0{badge}")
with h2:
    st.markdown(f"**HOD:** Dr. Alok Sehgal *(Sr. Interventional Cardiologist)*")
    st.markdown(f"**User:** `{st.session_state.current_user}` | {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}")
with h3:
    if st.button("🚪 Logout"):
        st.session_state.logged_in    = False
        st.session_state.current_user = None
        st.session_state.is_master    = False
        st.rerun()
st.markdown("---")

if not is_engine_ready:
    st.warning("⚠️ AI Engine not active. Add GEMINI_API_KEY in Streamlit → Settings → Secrets.")

# ============================================================
# TABS
# ============================================================
if st.session_state.is_master:
    tab_names = ["👑 Master Control","🏥 Bed Board","🩺 ICU Frontline","📊 HOD Dashboard","📉 Flowsheet","🚨 Early Warning","💊 Medications","🔄 Handover","🔬 Academic"]
else:
    tab_names = ["🏥 Bed Board","🩺 ICU Frontline","📊 HOD Dashboard","📉 Flowsheet","🚨 Early Warning","💊 Medications","🔄 Handover","🔬 Academic"]

tabs = st.tabs(tab_names)

def T(name):
    return tabs[tab_names.index(name)]

# ============================================================
# TAB: MASTER CONTROL
# ============================================================
if st.session_state.is_master:
    with T("👑 Master Control"):
        st.markdown("""
        <div style='background:linear-gradient(135deg,#1a1a2e,#0f3460);
                    padding:20px;border-radius:12px;color:white;margin-bottom:20px'>
          <h2 style='margin:0'>👑 Master Control Panel — Dr. G.S. Gill</h2>
          <p style='color:#aaa;margin:5px 0 0'>God-mode access — Only YOU can see this tab</p>
        </div>
        """, unsafe_allow_html=True)

        st.success(f"🔐 YOUR MASTER PASSWORD:  **GILL@ICU#2025**  — Keep this secret!")
        st.markdown("---")

        # Doctor management
        st.subheader("👨‍⚕️ Doctor & Resident Management")
        docs = st.session_state.doctors_db
        rows = [{"PIN": k, "Name": v['name'], "Role": v['role'], "Access": v['access']} for k,v in docs.items()]
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.markdown("#### ➕ Add New Doctor")
        d1,d2,d3,d4 = st.columns(4)
        with d1: new_name   = st.text_input("Full Name:", placeholder="Dr. First Last")
        with d2: new_role   = st.selectbox("Role:", ["Resident","Senior Resident","Registrar","Consultant","HOD"])
        with d3: new_access = st.selectbox("Access:", ["Resident","Senior","HOD"])
        with d4: cust_pin   = st.text_input("Custom PIN (or blank for auto):", max_chars=6)

        if st.button("✅ Add Doctor", type="primary"):
            if not new_name.strip():
                st.warning("Enter doctor name.")
            else:
                pin = cust_pin.strip() if cust_pin.strip() else generate_pin()
                while pin in st.session_state.doctors_db:
                    pin = generate_pin()
                st.session_state.doctors_db[pin] = {"name":new_name.strip(),"role":new_role,"access":new_access}
                log_action(f"Added doctor: {new_name} PIN:{pin}")
                st.success(f"✅ {new_name} added!")
                st.info(f"🔑 Their PIN is: **{pin}** — Share this privately via WhatsApp.")
                st.rerun()

        st.markdown("#### ❌ Remove Doctor")
        pin_map = {f"{v['name']} (PIN: {k})": k for k,v in docs.items()}
        to_del  = st.selectbox("Select to remove:", ["---"] + list(pin_map.keys()))
        if st.button("🗑️ Remove"):
            if to_del != "---":
                pk = pin_map[to_del]
                nm = docs[pk]['name']
                del st.session_state.doctors_db[pk]
                log_action(f"Removed: {nm}")
                st.success(f"Removed {nm}.")
                st.rerun()

        st.markdown("---")
        st.subheader("📊 System Stats")
        total   = len(st.session_state.patients_db)
        active  = sum(1 for d in st.session_state.patients_db.values() if d.get("status")=="Active")
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Total Patients", total)
        m2.metric("Active in ICU", active)
        m3.metric("Discharged", total-active)
        m4.metric("Registered Doctors", len(docs))

        st.markdown("---")
        st.subheader("📋 Audit Trail")
        for e in st.session_state.audit_log[:50]:
            st.text(e)

        if st.button("🔄 Sync from Cloud"):
            sync_from_cloud()
            st.success("Synced!")

# ============================================================
# TAB: BED BOARD
# ============================================================
with T("🏥 Bed Board"):
    st.header("🏥 ICU Bed Board — Kerala Cardiac ICU (12 Beds)")
    beds = st.session_state.icu_beds
    cols = st.columns(4)
    for i,(bed,pat) in enumerate(beds.items()):
        with cols[i%4]:
            color = "#1e4d1e" if pat=="Empty" else "#6b1a1a"
            emoji = "🟢 EMPTY" if pat=="Empty" else f"🔴 {pat}"
            st.markdown(f"""
            <div style='background:{color};padding:12px;border-radius:8px;
                        text-align:center;color:white;margin:4px'>
              <b>{bed}</b><br><small>{emoji}</small>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")
    active_pts = [n for n,d in st.session_state.patients_db.items() if d.get("status")=="Active"]
    b1,b2,b3 = st.columns(3)
    with b1: sel_bed    = st.selectbox("Bed:", list(beds.keys()))
    with b2: bed_action = st.radio("Action:", ["Assign Patient","Mark Empty"], horizontal=True)
    with b3:
        if bed_action=="Assign Patient":
            bed_pt = st.selectbox("Patient:", ["---"]+active_pts)
            if st.button("✅ Assign"):
                if bed_pt!="---":
                    st.session_state.icu_beds[sel_bed] = bed_pt
                    log_action(f"Bed assigned: {bed_pt} → {sel_bed}")
                    st.rerun()
        else:
            if st.button("✅ Mark Empty"):
                st.session_state.icu_beds[sel_bed] = "Empty"
                log_action(f"{sel_bed} marked empty")
                st.rerun()

    occ = sum(1 for v in beds.values() if v!="Empty")
    st.info(f"Occupied: {occ}/12 | Available: {12-occ} beds")

# ============================================================
# TAB: ICU FRONTLINE
# ============================================================
with T("🩺 ICU Frontline"):
    st.header("🩺 ICU Frontline — Admissions & Analysis")

    c1,c2 = st.columns(2)
    with c1: pt_type  = st.radio("Patient:", ["New Admission","Existing Patient"], horizontal=True)
    with c2: diag_cat = st.selectbox("Diagnosis Category:", [
        "Acute MI / ACS","Heart Failure","Arrhythmia","Cardiogenic Shock",
        "Post-PCI / Post-CABG","Hypertensive Emergency","Pulmonary Embolism",
        "Sepsis / Septic Shock","Respiratory Failure","Renal Failure (AKI)",
        "Post-Cardiac Arrest","Multi-Organ Failure","Other Critical"])

    if pt_type=="New Admission":
        p_name = st.text_input("Patient Full Name:").strip().title()
        nc1,nc2,nc3 = st.columns(3)
        with nc1: age    = st.number_input("Age:", 1, 120, 55)
        with nc2: gender = st.selectbox("Gender:", ["Male","Female","Other"])
        with nc3: bed_sel= st.selectbox("Assign Bed:", ["Unassigned"]+[b for b,v in st.session_state.icu_beds.items() if v=="Empty"])
    else:
        ap = [n for n,d in st.session_state.patients_db.items() if d.get("status")=="Active"]
        p_name = st.selectbox("Select Patient:", ["---"]+ap) if ap else ""
        if p_name=="---": p_name=""

    # Vitals
    with st.expander("📊 Enter Vitals", expanded=False):
        v1,v2,v3,v4,v5,v6 = st.columns(6)
        with v1: vbp  = st.text_input("BP","120/80")
        with v2: vhr  = st.number_input("HR",0,300,80)
        with v3: vrr  = st.number_input("RR",0,60,16)
        with v4: vspo2= st.number_input("SpO2",0,100,98)
        with v5: vtemp= st.number_input("Temp °C",30.0,43.0,37.0,0.1)
        with v6: vgcs = st.number_input("GCS",3,15,15)
        vitals_str = f"BP:{vbp} HR:{vhr} RR:{vrr} SpO2:{vspo2}% Temp:{vtemp}C GCS:{vgcs}"

    notes = st.text_area("Clinical Notes (history, examination, labs, ABG, ECG):", height=160,
        placeholder="65yr male, DM2/HTN, chest pain 2hrs, STEMI inferior, BP 90/60, HR 120...")

    full_notes = f"Category:{diag_cat} | Vitals:{vitals_str} | Notes:{notes}"

    st.subheader("📸 Upload ECG / X-Ray / Lab Reports")
    uploads = st.file_uploader("Upload images or PDF:", type=['jpg','jpeg','png','pdf'], accept_multiple_files=True)

    has_input = bool(notes.strip() or uploads)
    st.markdown("---")

    b1,b2,b3 = st.columns(3)
    with b1: do_quick  = st.button("🚨 Quick Analysis",    type="primary",    use_container_width=True)
    with b2: do_expert = st.button("👑 Expert Board",      type="secondary",  use_container_width=True)
    with b3: do_sepsis = st.button("🦠 Sepsis Protocol",                      use_container_width=True)

    if do_quick or do_expert or do_sepsis:
        if not is_engine_ready:
            st.error("AI Engine offline — add GEMINI_API_KEY in Streamlit Secrets.")
        elif not p_name:
            st.warning("Enter patient name.")
        elif not has_input:
            st.warning("Add clinical notes or upload a report.")
        else:
            if do_quick:
                atype = "QUICK"
                prompt = f"""You are a Senior ICU Resident in a Cardiac ICU, Kerala India.
Patient: {p_name} | {full_notes}
Give fast structured analysis:
1. WORKING DIAGNOSIS
2. CRITICALITY SCORE (1-10, label RED/YELLOW/GREEN)
3. IMMEDIATE ACTIONS (next 30 minutes)
4. INVESTIGATIONS TO ORDER
5. TREATMENT PLAN
6. DRUG INTERACTIONS CHECK
7. NURSE INSTRUCTIONS
Use Indian generic drug names. PLAIN TEXT ONLY. NO ASTERISKS.
End with: TOPICS: Topic1, Topic2, Topic3"""

            elif do_expert:
                atype = "EXPERT"
                prompt = f"""You are a Multi-Disciplinary Expert Board (Intensivist, Cardiologist, Nephrologist, Pharmacologist).
Patient: {p_name} | {full_notes}
1. CRITICALITY SCORE (1-10, RED/YELLOW/GREEN)
2. ABG ANALYSIS (step-by-step if ABG data present)
3. ECG INTERPRETATION (if ECG findings present)
4. MULTI-SPECIALTY VIEWS (Intensivist / Cardiologist / Nephrologist / Pharmacologist)
5. MASTER TREATMENT PROTOCOL (drug names, doses, routes, timing)
6. MONITORING TARGETS
7. ESCALATION TRIGGERS
8. FAMILY COUNSELING POINTS
PLAIN TEXT ONLY. NO ASTERISKS.
End with: TOPICS: Topic1, Topic2, Topic3"""

            else:
                atype = "SEPSIS"
                prompt = f"""You are a Sepsis Expert in a Cardiac ICU, Kerala India.
Patient: {p_name} | {full_notes}
Apply SURVIVING SEPSIS CAMPAIGN 1-HOUR BUNDLE:
1. qSOFA SCORE & SEPSIS-3 CRITERIA
2. SHOCK ASSESSMENT (septic/cardiogenic/mixed)
3. 1-HOUR BUNDLE CHECKLIST
4. ANTIBIOTIC SELECTION (Kerala resistance patterns)
5. VASOPRESSOR PROTOCOL (Norepinephrine doses)
6. SOURCE CONTROL
7. MONITORING TARGETS (lactate, MAP, urine output)
PLAIN TEXT ONLY. NO ASTERISKS.
End with: TOPICS: Topic1, Topic2, Topic3"""

            with st.spinner("AI analyzing case..."):
                try:
                    contents = [prompt]
                    if uploads:
                        for f in uploads:
                            if f.name.lower().endswith(('png','jpg','jpeg')) and PIL_AVAILABLE:
                                contents.append(optimize_image(f))
                            elif f.name.lower().endswith('.pdf'):
                                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                                    tmp.write(f.read())
                                gemini_f = genai.upload_file(path=tmp.name, mime_type='application/pdf')
                                contents.append(gemini_f)

                    result = smart_generate(contents)
                    topics = []
                    if "TOPICS:" in result:
                        parts  = result.split("TOPICS:")
                        result = parts[0].strip()
                        topics = [t.strip() for t in parts[1].split(",")]
                        st.session_state[f"topics_{p_name}"] = topics

                    now = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
                    if p_name not in st.session_state.patients_db:
                        st.session_state.patients_db[p_name] = {"status":"Active","history":[],"bed":"Unassigned"}
                        if pt_type=="New Admission" and bed_sel!="Unassigned":
                            st.session_state.patients_db[p_name]["bed"] = bed_sel
                            st.session_state.icu_beds[bed_sel] = p_name

                    st.session_state.patients_db[p_name]["history"].append({
                        "date":now,"doctor":st.session_state.current_user,
                        "raw_notes":full_notes[:2000],"summary":result,"type":atype
                    })
                    push_to_cloud({"action":"new_entry","patient_name":p_name,
                                   "doctor":st.session_state.current_user,"raw_notes":full_notes[:2000],
                                   "summary":result,"date":now,"status":"Active"})
                    log_action(f"{atype} analysis: {p_name}")
                    st.session_state[f"result_{p_name}"] = result
                    st.success(f"Analysis complete & auto-saved for {p_name}!")
                except Exception as e:
                    st.error(f"AI Error: {str(e)}")

    rkey = f"result_{p_name}" if p_name else None
    if rkey and rkey in st.session_state:
        st.markdown("---")
        st.subheader("📋 AI Analysis")
        st.info(st.session_state[rkey])

        if FPDF_AVAILABLE and st.button("📄 Download PDF Report"):
            path = generate_pdf("CLINICAL ANALYSIS", p_name, st.session_state[rkey], st.session_state.current_user)
            if path:
                with open(path,"rb") as f:
                    st.download_button("📥 Download", data=f,
                        file_name=f"{p_name}_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                        mime="application/pdf")

        st.markdown("---")
        st.subheader("📚 AI-Suggested Topics")
        auto_topics = st.session_state.get(f"topics_{p_name}", [])
        sel_topic   = st.selectbox("Study:", ["Choose..."]+auto_topics) if auto_topics else None
        cust_topic  = st.text_input("Or type your own topic:")
        final_topic = cust_topic if cust_topic else (sel_topic if sel_topic and sel_topic!="Choose..." else "")
        if final_topic and st.button("📖 Generate Guideline PDF"):
            with st.spinner("Generating guideline..."):
                try:
                    gp = f"""Write a comprehensive ICU clinical guideline on: {final_topic}
Include definition, diagnosis criteria, management protocol, drug doses (Indian generic names),
monitoring parameters, complications. Reference AHA/ESC/SCCM guidelines.
PLAIN TEXT ONLY. NO ASTERISKS."""
                    gt = smart_generate([gp])
                    gpath = generate_pdf(f"GUIDELINE: {final_topic[:40].upper()}", "Academic", gt, st.session_state.current_user)
                    if gpath:
                        with open(gpath,"rb") as f:
                            st.download_button("📥 Download Guideline", data=f,
                                file_name=f"Guideline_{final_topic.replace(' ','_')[:30]}.pdf",
                                mime="application/pdf")
                except Exception as e:
                    st.error(str(e))

# ============================================================
# TAB: HOD DASHBOARD
# ============================================================
with T("📊 HOD Dashboard"):
    st.header("📊 HOD Dashboard — Patient Files & Clinical Thread")

    c1,c2 = st.columns([3,1])
    with c1: vf = st.radio("Show:", ["Active","Discharged","All"], horizontal=True)
    with c2:
        if st.button("🔄 Refresh"):
            sync_from_cloud()
            st.rerun()

    db = st.session_state.patients_db
    filt = {k:v for k,v in db.items() if
            (vf=="Active" and v.get("status")=="Active") or
            (vf=="Discharged" and v.get("status")=="Discharged") or
            vf=="All"}

    if not filt:
        st.info("No patients found.")
    else:
        for pname, pdata in filt.items():
            hist   = pdata.get("history",[])
            latest = hist[-1] if hist else {}
            badge  = "🔴 ACTIVE" if pdata.get("status")=="Active" else "✅ DISCHARGED"
            adm    = hist[0].get("date","?") if hist else "?"

            with st.expander(f"{badge} | 🛏️ {pname} | Admitted: {adm} | Updates: {len(hist)}"):
                s1,s2,s3 = st.columns(3)
                s1.caption(f"Last update: {latest.get('date','?')}")
                s2.caption(f"Last doctor: {latest.get('doctor','?')}")
                s3.caption(f"Bed: {pdata.get('bed','?')}")

                edited = st.text_area("Master Clinical File (HOD can edit):",
                    value=latest.get("summary",""), height=200, key=f"edit_{pname}")

                if st.button("💾 Save Edits", key=f"save_{pname}"):
                    if hist:
                        st.session_state.patients_db[pname]["history"][-1]["summary"] = edited
                        log_action(f"HOD edited: {pname}")
                        st.success("Saved!")

                st.markdown("---")
                st.markdown("### 📈 Add Progress Note (Clinical Thread)")
                with st.container(border=True):
                    pnotes = st.text_area("New progress / findings:", key=f"pn_{pname}", height=70,
                        placeholder="New vitals, ABG result, ECG change, response to treatment...")
                    pfiles = st.file_uploader("Upload new reports:", type=['jpg','jpeg','png','pdf'],
                        accept_multiple_files=True, key=f"pf_{pname}")

                    if st.button("🔄 Analyze & Update Thread", type="primary", key=f"thread_{pname}"):
                        if not (pnotes.strip() or pfiles):
                            st.warning("Add notes or upload a report.")
                        elif not is_engine_ready:
                            st.error("AI offline.")
                        else:
                            with st.spinner("AI comparing with previous data..."):
                                try:
                                    tp = f"""You are a Senior ICU Registrar updating the clinical thread for {pname}.

PREVIOUS CLINICAL SUMMARY:
{edited}

NEW PROGRESS NOTE:
{pnotes}

TRAJECTORY COMPARISON:
1. COMPARISON: Is patient IMPROVING, DETERIORATING, or STABLE? Be specific.
2. UPDATED CRITICALITY SCORE (1-10, RED/YELLOW/GREEN)
3. RESPONSE TO TREATMENT: Is current plan working?
4. TREATMENT ADJUSTMENTS NEEDED
5. PLAN FOR NEXT 24 HOURS
6. WARD ROUND SUMMARY (5 lines for HOD round)

PLAIN TEXT ONLY. NO ASTERISKS."""
                                    tc = [tp]
                                    if pfiles:
                                        for f in pfiles:
                                            if f.name.lower().endswith(('png','jpg','jpeg')) and PIL_AVAILABLE:
                                                tc.append(optimize_image(f))
                                    tres = smart_generate(tc)
                                    now  = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
                                    st.session_state.patients_db[pname]["history"].append({
                                        "date":now,"doctor":st.session_state.current_user,
                                        "raw_notes":pnotes,"summary":tres,"type":"PROGRESS"
                                    })
                                    push_to_cloud({"action":"new_entry","patient_name":pname,
                                        "doctor":st.session_state.current_user,"raw_notes":pnotes,
                                        "summary":tres,"date":now,"status":"Active"})
                                    log_action(f"Thread updated: {pname}")
                                    st.success("Thread updated!")
                                    st.info(tres)
                                except Exception as e:
                                    st.error(str(e))

                if st.checkbox(f"📅 Full History", key=f"hist_{pname}"):
                    for i,h in enumerate(reversed(hist)):
                        with st.container(border=True):
                            st.caption(f"Entry #{len(hist)-i} | {h.get('date','')} | {h.get('doctor','')} | {h.get('type','')}")
                            txt = h.get("summary","")
                            st.text(txt[:600]+"..." if len(txt)>600 else txt)

                st.markdown("---")
                if pdata.get("status")=="Active":
                    dc1,dc2 = st.columns(2)
                    with dc1:
                        if st.button(f"📄 Generate Discharge Summary", key=f"ds_{pname}"):
                            with st.spinner("Generating..."):
                                try:
                                    all_s = "\n\n---\n\n".join([h.get("summary","") for h in hist[-3:]])
                                    dp = f"""Generate formal HOSPITAL DISCHARGE SUMMARY for {pname}, Cardiac ICU Kerala.
Clinical journey: {all_s}
Include: Admission diagnosis, ICU stay summary, investigations, procedures, discharge condition,
discharge medications with doses, follow-up instructions, red flag symptoms, activity/diet restrictions.
Under: Dr. Alok Sehgal (HOD). Attending: {st.session_state.current_user}.
PLAIN TEXT ONLY. NO ASTERISKS."""
                                    dt   = smart_generate([dp])
                                    dpth = generate_pdf("DISCHARGE SUMMARY", pname, dt, st.session_state.current_user)
                                    if dpth:
                                        with open(dpth,"rb") as f:
                                            st.download_button("📥 Download Discharge PDF", data=f,
                                                file_name=f"{pname}_Discharge.pdf", mime="application/pdf",
                                                key=f"dl_{pname}")
                                except Exception as e:
                                    st.error(str(e))
                    with dc2:
                        if st.button(f"🚪 Mark Discharged", key=f"md_{pname}"):
                            st.session_state.patients_db[pname]["status"] = "Discharged"
                            for bed,occ in st.session_state.icu_beds.items():
                                if occ==pname: st.session_state.icu_beds[bed]="Empty"
                            push_to_cloud({"action":"discharge","patient_name":pname,
                                           "status":"Discharged","date":str(datetime.datetime.now())})
                            log_action(f"Discharged: {pname}")
                            st.success(f"{pname} discharged.")
                            st.rerun()

# ============================================================
# TAB: FLOWSHEET
# ============================================================
with T("📉 Flowsheet"):
    st.header("📉 ICU Flowsheet & Vital Trends")
    ap = [n for n,d in st.session_state.patients_db.items() if d.get("status")=="Active"]
    if not ap:
        st.info("No active patients.")
    else:
        sel_pt = st.selectbox("Patient:", ap)
        fkey   = f"flow_{sel_pt}"
        if fkey not in st.session_state: st.session_state[fkey] = []

        f1,f2,f3,f4,f5,f6,f7 = st.columns(7)
        with f1: ft   = st.text_input("Time", datetime.datetime.now().strftime("%H:%M"), key="ft")
        with f2: fbp  = st.text_input("BP","120/80", key="fbp")
        with f3: fhr  = st.number_input("HR",0,300,80, key="fhr")
        with f4: frr  = st.number_input("RR",0,60,16, key="frr")
        with f5: fsp  = st.number_input("SpO2",0,100,98, key="fsp")
        with f6: ftmp = st.number_input("Temp",30.0,43.0,37.0,0.1, key="ftmp")
        with f7: fuo  = st.number_input("UO ml/hr",0,1000,50, key="fuo")

        if st.button("➕ Add Vitals"):
            st.session_state[fkey].append({"Time":ft,"BP":fbp,"HR":fhr,"RR":frr,"SpO2":fsp,"Temp":ftmp,"UO":fuo})
            log_action(f"Vitals added: {sel_pt}")
            st.success("Added!")

        fdata = st.session_state.get(fkey,[])
        if fdata:
            df = pd.DataFrame(fdata)
            st.dataframe(df, use_container_width=True, hide_index=True)
            ch1,ch2 = st.columns(2)
            with ch1:
                try: st.line_chart(df.set_index("Time")[["HR","RR"]]); st.caption("HR & RR")
                except: pass
            with ch2:
                try: st.line_chart(df.set_index("Time")[["SpO2"]]); st.caption("SpO2")
                except: pass

# ============================================================
# TAB: EARLY WARNING
# ============================================================
with T("🚨 Early Warning"):
    st.header("🚨 Early Warning — NEWS2 & Sepsis Screening")
    ew1,ew2 = st.columns(2)
    with ew1:
        st.subheader("🩺 NEWS2 Calculator")
        e_rr  = st.number_input("Respiratory Rate:",0,60,16,key="e_rr")
        e_sp  = st.number_input("SpO2 (%):",0,100,97,key="e_sp")
        e_o2  = st.checkbox("On supplemental O2?")
        e_sbp = st.number_input("Systolic BP (mmHg):",50,250,120,key="e_sbp")
        e_hr  = st.number_input("Heart Rate:",0,300,80,key="e_hr")
        e_tmp = st.number_input("Temperature (°C):",30.0,43.0,37.0,0.1,key="e_tmp")
        e_av  = st.selectbox("AVPU:",["Alert","Confusion/New","Voice","Pain","Unresponsive"])

        if st.button("📊 Calculate NEWS2", type="primary"):
            sc,risk,color,action = calc_news2(e_rr,e_sp,e_o2,e_sbp,e_hr,e_tmp,e_av)
            bg = "#6b1a1a" if "HIGH" in risk else ("#7a6b00" if "MEDIUM" in risk else "#1e4d1e")
            st.markdown(f"""
            <div style='background:{bg};padding:20px;border-radius:12px;color:white;text-align:center'>
              <h2>{color} NEWS2: {sc}</h2><h3>Risk: {risk}</h3><p>{action}</p>
            </div>""", unsafe_allow_html=True)
            log_action(f"NEWS2: {sc} ({risk})")

    with ew2:
        st.subheader("🦠 qSOFA Sepsis Screen")
        q_rr  = st.number_input("RR:",0,60,16,key="q_rr")
        q_gcs = st.number_input("GCS:",3,15,15,key="q_gcs")
        q_sbp = st.number_input("Systolic BP:",50,250,110,key="q_sbp")

        if st.button("🦠 Calculate qSOFA", type="primary"):
            qs = sum([q_rr>=22, q_gcs<15, q_sbp<=100])
            bg = "#6b1a1a" if qs>=2 else "#1e4d1e"
            msg = "HIGH SEPSIS RISK — Activate Sepsis Protocol!" if qs>=2 else "Low-Moderate Risk — Monitor"
            st.markdown(f"""
            <div style='background:{bg};padding:20px;border-radius:12px;color:white;text-align:center'>
              <h2>qSOFA: {qs}/3</h2><p>{msg}</p>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("🧠 AI Deterioration Analysis")
    det_txt = st.text_area("Paste vitals/findings for AI risk assessment:", height=100)
    if st.button("🧠 Analyze Deterioration Risk") and det_txt and is_engine_ready:
        with st.spinner("AI analyzing..."):
            try:
                dp = f"""Critical Care AI: Analyze deterioration risk for: {det_txt}
1. RISK LEVEL (LOW/MEDIUM/HIGH/CRITICAL)
2. WARNING SIGNS
3. PREDICTED COMPLICATIONS (next 4-12 hrs)
4. IMMEDIATE INTERVENTIONS
5. MONITORING ESCALATION
PLAIN TEXT ONLY. NO ASTERISKS."""
                st.info(smart_generate([dp]))
            except Exception as e: st.error(str(e))

# ============================================================
# TAB: MEDICATIONS
# ============================================================
with T("💊 Medications"):
    st.header("💊 Medication Safety & Dose Calculator")
    med1,med2 = st.columns(2)
    with med1:
        st.subheader("⚠️ DDI Checker")
        med_list   = st.text_area("All medications (one per line):", height=180,
            placeholder="Aspirin 75mg OD\nClopidogrel 75mg OD\nEnoxaparin 40mg BD\nAmiodarone 200mg TDS")
        renal      = st.selectbox("Renal Function:",["Normal","Mild (CrCl 60-90)","Moderate (CrCl 30-60)","Severe (CrCl 15-30)","ESRD/Dialysis"])
        hepatic    = st.selectbox("Hepatic Function:",["Normal","Child-Pugh A","Child-Pugh B","Child-Pugh C"])

        if st.button("🔬 Pharmacology Safety Scan", type="primary"):
            if not med_list.strip(): st.warning("Enter medications.")
            elif not is_engine_ready: st.error("AI offline.")
            else:
                with st.spinner("Scanning..."):
                    try:
                        mp = f"""Senior Clinical Pharmacologist — ICU Cardiac, Kerala.
Medications: {med_list}
Renal: {renal} | Hepatic: {hepatic}
1. DANGEROUS DDIs (CONTRAINDICATED/MAJOR/MODERATE/MINOR — be specific)
2. DOSE ADJUSTMENTS for renal impairment (drug name + adjusted dose)
3. HEPATIC ADJUSTMENTS
4. MONITORING PARAMETERS
5. ANTICOAGULATION SAFETY (if applicable)
6. SAFER ALTERNATIVES for any contraindicated combos
PLAIN TEXT ONLY. NO ASTERISKS."""
                        res = smart_generate([mp])
                        log_action("Med safety scan")
                        st.success("Scan complete!")
                        st.info(res)
                    except Exception as e: st.error(str(e))

    with med2:
        st.subheader("💉 ICU Infusion Rate Calculator")
        drug   = st.selectbox("Drug:",["Norepinephrine","Dopamine","Dobutamine","Adrenaline","GTN","Furosemide","Insulin","Midazolam","Morphine","Amiodarone"])
        wt     = st.number_input("Weight (kg):",30.0,200.0,65.0,0.5)
        dose   = st.number_input("Dose (mcg/kg/min):",0.0,100.0,0.1,0.01)
        conc   = st.number_input("Concentration (mcg/ml):",0.1,10000.0,100.0,0.1)

        if st.button("🧮 Calculate Rate"):
            rate = (dose * wt * 60) / conc if conc>0 else 0
            st.success(f"Infusion Rate: **{rate:.2f} ml/hr**")
            st.caption(f"{drug} | {dose} mcg/kg/min | {wt}kg | {conc} mcg/ml")
            log_action(f"Dose calc: {drug} = {rate:.2f} ml/hr")

# ============================================================
# TAB: HANDOVER
# ============================================================
with T("🔄 Handover"):
    st.header("🔄 Shift Handover — ISBAR Format")
    h1c,h2c = st.columns(2)
    with h1c: out_dr = st.text_input("Outgoing Doctor:", value=st.session_state.current_user.split("(")[0].strip())
    with h2c: in_dr  = st.text_input("Incoming Doctor:", placeholder="Name of next duty doctor")
    extra = st.text_area("Pending tasks / concerns:", height=70)

    if st.button("🔄 Generate ISBAR Handover for ALL Patients", type="primary"):
        ap2 = {k:v for k,v in st.session_state.patients_db.items() if v.get("status")=="Active"}
        if not ap2: st.warning("No active patients.")
        elif not is_engine_ready: st.error("AI offline.")
        else:
            with st.spinner("Generating handover..."):
                try:
                    parts = []
                    for pn, pd2 in ap2.items():
                        hist2  = pd2.get("history",[])
                        latest2 = hist2[-1].get("summary","No data") if hist2 else "No data"
                        hp = f"""ISBAR handover for {pn}:
Previous summary: {latest2[:600]}
Write 5 bullet points: current status, active issues, current infusions/meds, pending actions, what incoming doctor must watch.
PLAIN TEXT. NO ASTERISKS."""
                        hr2 = smart_generate([hp])
                        parts.append(f"--- {pn} ---\n{hr2}")

                    full = f"""SHIFT HANDOVER — {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}
Outgoing: {out_dr}
Incoming: {in_dr}
Active Patients: {len(ap2)}

{"=" * 50}
{chr(10).join(parts)}
{"=" * 50}

ADDITIONAL NOTES:
{extra}

Handover completed.
"""
                    st.session_state.handover_notes.insert(0,{"date":str(datetime.datetime.now()),"outgoing":out_dr,"incoming":in_dr,"content":full})
                    log_action(f"Handover: {out_dr} → {in_dr}")
                    st.success("Handover generated!")
                    st.info(full)
                    if FPDF_AVAILABLE:
                        hp2 = generate_pdf("SHIFT HANDOVER", "All Active Patients", full, out_dr)
                        if hp2:
                            with open(hp2,"rb") as f:
                                st.download_button("📥 Download Handover PDF", data=f,
                                    file_name=f"Handover_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                                    mime="application/pdf")
                except Exception as e: st.error(str(e))

# ============================================================
# TAB: ACADEMIC
# ============================================================
with T("🔬 Academic"):
    st.header("🔬 Academic Vault — CME & Clinical Guidelines")

    topic  = st.text_input("Topic:", placeholder="e.g. Cardiogenic Shock, STEMI 2024 guidelines, Vasopressor use in ICU")
    ac1,ac2,ac3 = st.columns(3)
    with ac1: ct  = st.selectbox("Type:",["Clinical Guideline","Drug Protocol","Case Discussion","Procedure Guide","CME Quiz"])
    with ac2: lv  = st.selectbox("Level:",["Resident","Senior Resident","Consultant","Fellowship"])
    with ac3: ref = st.selectbox("Reference:",["AHA/ACC 2024","ESC 2024","SCCM/ESICM","Indian (CSI/ISCCM)","Multiple"])

    if st.button("📚 Generate Academic Content", type="primary"):
        if not topic.strip(): st.warning("Enter a topic.")
        elif not is_engine_ready: st.error("AI offline.")
        else:
            with st.spinner("Generating..."):
                try:
                    ap3 = f"""Medical educator + Intensivist, Cardiac ICU Kerala.
Topic: {topic} | Type: {ct} | Level: {lv} | Reference: {ref}
Write comprehensive {ct}: definition, pathophysiology, diagnosis criteria, step-by-step management,
drug doses (Indian generic names), monitoring targets, complications, clinical pearls.
{"Include 5 MCQs with answers." if ct=="CME Quiz" else ""}
PLAIN TEXT ONLY. NO ASTERISKS."""
                    ar = smart_generate([ap3])
                    log_action(f"Academic: {topic}")
                    st.success("Generated!")
                    st.info(ar)
                    if FPDF_AVAILABLE:
                        apath = generate_pdf(f"{ct.upper()}: {topic[:40].upper()}", "Academic", ar, st.session_state.current_user)
                        if apath:
                            with open(apath,"rb") as f:
                                st.download_button("📥 Download PDF", data=f,
                                    file_name=f"Academic_{topic.replace(' ','_')[:30]}.pdf",
                                    mime="application/pdf")
                except Exception as e: st.error(str(e))

    st.markdown("---")
    st.subheader("⚡ Quick 1-Page Reference Cards")
    quick_list = ["STEMI Protocol","Cardiogenic Shock","Acute Pulmonary Edema","VT/VF Management",
                  "Hypertensive Emergency","Septic Shock Bundle","AKI Management",
                  "NIV/BiPAP Setup","Anticoagulation in AF+ACS","Post-PCI Care"]
    qsel = st.selectbox("Select:", quick_list)
    if st.button("⚡ Quick Generate"):
        with st.spinner("Generating..."):
            try:
                qp = f"""1-PAGE QUICK REFERENCE CARD for: {qsel}
Include ONLY the most critical bedside info:
- 3-5 diagnostic criteria
- 5-8 step management
- Key drug doses
- 3 monitoring targets
- 2 mistakes to avoid
Very concise. PLAIN TEXT. NO ASTERISKS."""
                qr = smart_generate([qp])
                st.success("Ready!")
                st.info(qr)
                log_action(f"Quick ref: {qsel}")
            except Exception as e: st.error(str(e))

# ============================================================
# FOOTER
# ============================================================
st.markdown("---")
st.markdown("""
<div style='text-align:center;color:gray;font-size:12px'>
Dr. Gill's Cardiac ICU Command System v2.0 | Kerala, India |
AI-Powered by Google Gemini | For demonstration & clinical decision support |
Always verify with qualified clinicians
</div>""", unsafe_allow_html=True)
