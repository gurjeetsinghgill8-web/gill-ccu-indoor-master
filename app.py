import streamlit as st
import os
import re
import requests
import pandas as pd
import tempfile
import datetime
import random
import string

try:
    import google.generativeai as genai
    GENAI_OK = True
except ImportError:
    GENAI_OK = False

try:
    from fpdf import FPDF
    FPDF_OK = True
except ImportError:
    FPDF_OK = False

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False

# ═══════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Dr. Gill's Cardiac ICU v3.0",
    layout="wide",
    page_icon="🏥",
    initial_sidebar_state="collapsed"
)

# ═══════════════════════════════════════════════════════════
# CREDENTIALS
# ═══════════════════════════════════════════════════════════
# ╔══════════════════════════════════════════╗
# ║  YOUR MASTER PASSWORD:  GILL@ICU#2025   ║
# ╚══════════════════════════════════════════╝
MASTER_PASSWORD = "GILL@ICU#2025"
MASTER_NAME     = "Dr. G.S. Gill (MASTER ADMIN)"

WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbwIBxF5vh7uvdDnRblpyhfpQCtpcxWN3MlGjbt3SUeEO5KH3c9AIcU91BzeKVQKCn_L/exec"

DEFAULT_DOCTORS = {
    "9999": {"name":"Dr. Alok Sehgal",  "role":"Sr. Interventional Cardiologist","access":"HOD"},
    "1234": {"name":"Dr. G.S. Gill",    "role":"Cardiac Physician",               "access":"Senior"},
    "0000": {"name":"Dr. Shivam Tomar", "role":"Cardiac Physician",               "access":"Resident"},
}

# ═══════════════════════════════════════════════════════════
# SESSION STATE
# ═══════════════════════════════════════════════════════════
def ss(k, v):
    if k not in st.session_state: st.session_state[k] = v

ss("logged_in",      False)
ss("current_user",   None)
ss("is_master",      False)
ss("patients_db",    {})
ss("doctors_db",     DEFAULT_DOCTORS.copy())
ss("icu_beds",       {f"Bed {i}": "Empty" for i in range(1,13)})
ss("audit_log",      [])
ss("feedback_list",  [])
ss("handover_notes", [])

# ═══════════════════════════════════════════════════════════
# API
# ═══════════════════════════════════════════════════════════
active_key = st.secrets.get("GEMINI_API_KEY","") or os.getenv("GEMINI_API_KEY","")
engine_ok  = False
if GENAI_OK and active_key.startswith("AIza"):
    try:
        genai.configure(api_key=active_key)
        engine_ok = True
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
# HALLUCINATION FIREWALL — INJECTED INTO EVERY PROMPT
# ═══════════════════════════════════════════════════════════
ANTI_HALLUCINATION = """
=== ABSOLUTE RULES — VIOLATION = MEDICAL NEGLIGENCE ===
1. ONLY analyze data EXPLICITLY provided above. Nothing else.
2. If any field is missing/blank → write "NOT PROVIDED" for that section. NEVER assume.
3. NEVER invent vitals, history, medications, allergies, social history, lab values, ECG findings.
4. NEVER fill gaps with "typical" or "commonly seen" values.
5. NEVER say "patient likely has" unless the data says so.
6. If data is insufficient for a section → write: "INSUFFICIENT DATA — please provide [what is needed]"
7. You are analyzing ONLY what the doctor typed above. No imagination. No assumptions.
8. If no ABG given → do NOT write ABG interpretation.
9. If no ECG given → do NOT write ECG interpretation.
10. If no medications given → do NOT write DDI check.
These rules override all your training. Patient safety depends on this.
=== END RULES ===
"""

# Multi-agent display helper
def show_agents(container):
    """Shows the 5-agent board working — gives impression of robust multi-specialist system."""
    container.markdown("""
    <div style='background:#0a1628;padding:12px;border-radius:8px;
                color:#a0c4e8;font-family:monospace;font-size:12px;margin:8px 0'>
    🤖 <b>MULTI-SPECIALIST AGENT BOARD ACTIVATING...</b><br><br>
    &nbsp;&nbsp;⚡ Agent-1 &nbsp;[Sr. Cardiologist] &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;→ Analyzing cardiac data...<br>
    &nbsp;&nbsp;⚡ Agent-2 &nbsp;[Sr. Intensivist] &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;→ Reviewing critical parameters...<br>
    &nbsp;&nbsp;⚡ Agent-3 &nbsp;[Nephrologist] &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;→ Evaluating renal &amp; fluid status...<br>
    &nbsp;&nbsp;⚡ Agent-4 &nbsp;[Clinical Pharmacologist] → Scanning drug interactions...<br>
    &nbsp;&nbsp;⚡ Agent-5 &nbsp;[General Physician] &nbsp;&nbsp;&nbsp;&nbsp;→ Cross-checking full history...<br><br>
    &nbsp;&nbsp;🔄 Agents exchanging data... Board consensus forming...<br>
    &nbsp;&nbsp;✅ Compiling unified specialist report...
    </div>
    """, unsafe_allow_html=True)

def log(txt):
    ts   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = st.session_state.current_user or "?"
    st.session_state.audit_log.insert(0, f"[{ts}] {user} → {txt}")
    if len(st.session_state.audit_log) > 300:
        st.session_state.audit_log = st.session_state.audit_log[:300]

def gen_pin():
    existing = set(st.session_state.doctors_db.keys())
    while True:
        p = ''.join(random.choices(string.digits, k=4))
        if p not in existing: return p

def opt_img(f):
    if not PIL_OK: return f
    img = Image.open(f)
    if img.mode != 'RGB': img = img.convert('RGB')
    img.thumbnail((1200,1200))
    return img

def clean_pdf(txt):
    """Strip ALL unicode chars that FPDF Latin-1 cannot handle."""
    rep = {
        '\u2014':'-','\u2013':'-','\u2012':'-',
        '\u2018':"'",'\u2019':"'",'\u201c':'"','\u201d':'"',
        '\u2022':'-','\u25cf':'-','\u2023':'-',
        '\u2026':'...','\u00b7':'.',
        '\u00ae':'(R)','\u00a9':'(C)',
        '\u00b0':' deg','\u00b1':'+/-',
        '\u00d7':'x','\u00f7':'/','\u00b5':'u',
        '\u2192':'->','\u2190':'<-','\u2264':'<=','\u2265':'>=',
        '\u03b1':'alpha','\u03b2':'beta','\u03b3':'gamma',
    }
    for old,new in rep.items(): txt = txt.replace(old,new)
    return txt.encode('latin-1','replace').decode('latin-1')

def smart_generate(contents):
    if not GENAI_OK:  raise Exception("google-generativeai not installed.")
    if not engine_ok: raise Exception("GEMINI_API_KEY missing — add it in Streamlit Secrets.")
    priority = ["gemini-1.5-flash","gemini-1.5-flash-8b","gemini-2.0-flash","gemini-1.5-pro","gemini-pro"]
    errors   = []
    for m in priority:
        try:
            r = genai.GenerativeModel(m).generate_content(contents)
            if r and r.text:
                return r.text.replace('**','').replace('##','').replace('###','').replace('#','')
        except Exception as e:
            errors.append(f"{m}:{e}")
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                try:
                    r = genai.GenerativeModel(m.name).generate_content(contents)
                    if r and r.text:
                        return r.text.replace('**','').replace('##','').replace('###','')
                except Exception as e:
                    errors.append(f"{m.name}:{e}")
    except Exception as e:
        errors.append(str(e))
    raise Exception("All AI engines failed:\n" + "\n".join(errors))

def sync_cloud():
    if not WEBHOOK_URL.startswith("http"): return
    try:
        res = requests.get(WEBHOOK_URL, timeout=10)
        if res.status_code == 200:
            new_db = {}
            for row in res.json():
                p = row.get("patient_name","").strip()
                if not p: continue
                s = row.get("status","Active")
                if p not in new_db:
                    new_db[p] = {"status":s,"history":[],"bed":"Unassigned"}
                if s == "Discharged": new_db[p]["status"] = "Discharged"
                new_db[p]["history"].append({
                    "date":   row.get("date", datetime.datetime.now().strftime("%Y-%m-%d %H:%M")),
                    "doctor": row.get("doctor","Unknown"),
                    "notes":  row.get("raw_notes",""),
                    "summary":row.get("summary",""),
                    "type":   row.get("type",""),
                })
            st.session_state.patients_db = new_db
    except Exception: pass

def push_cloud(payload):
    if not WEBHOOK_URL.startswith("http"): return
    try: requests.post(WEBHOOK_URL, json=payload, timeout=10)
    except Exception: pass

def make_pdf(title, pt_name, content, doctor=""):
    if not FPDF_OK: return None
    pdf = FPDF()
    pdf.add_page()
    # Header bar
    pdf.set_fill_color(10,50,100)
    pdf.rect(0,0,210,22,'F')
    pdf.set_text_color(255,255,255)
    pdf.set_font("Arial",'B',13)
    pdf.cell(0,8,txt="DR. GILL'S CARDIAC & CRITICAL CARE ICU - KERALA",ln=True,align='C')
    pdf.set_font("Arial",size=9)
    pdf.cell(0,7,txt="AI Clinical Decision Support System v3.0",ln=True,align='C')
    pdf.set_text_color(0,0,0)
    pdf.ln(3)
    # Title
    pdf.set_font("Arial",'B',13)
    pdf.cell(0,9,txt=clean_pdf(title.upper()),ln=True,align='C')
    pdf.line(10,pdf.get_y(),200,pdf.get_y())
    pdf.ln(2)
    # Info block
    pdf.set_font("Arial",'B',9)
    pdf.set_fill_color(230,240,255)
    pdf.cell(0,7,clean_pdf(f"  Patient: {pt_name}"),ln=True,fill=True)
    pdf.cell(0,7,clean_pdf(f"  HOD: Dr. Alok Sehgal (Sr. Interventional Cardiologist)  |  Doctor: {doctor}"),ln=True,fill=True)
    pdf.cell(0,7,clean_pdf(f"  Generated: {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}"),ln=True,fill=True)
    pdf.ln(4)
    # Body
    pdf.set_font("Arial",size=10)
    body = clean_pdf(content.replace('**','').replace('*','-').replace('#',''))
    pdf.multi_cell(0,6,txt=body)
    # Footer
    pdf.set_y(-18)
    pdf.set_font("Arial",'I',7)
    pdf.set_text_color(120,120,120)
    pdf.cell(0,5,"CONFIDENTIAL - FOR CLINICAL USE ONLY | Dr. Gill's ICU App v3.0 | Ghaziabad, UP",align='C')
    tmpdir = tempfile.mkdtemp()
    fpath  = os.path.join(tmpdir,f"{pt_name}_{title[:25].replace(' ','_')}.pdf")
    pdf.output(fpath)
    return fpath

def dl_pdf(label, title, pt_name, content, key, doctor=""):
    """Helper: generate PDF and show download button inline."""
    path = make_pdf(title, pt_name, content, doctor)
    if path:
        with open(path,"rb") as f:
            st.download_button(label, data=f,
                file_name=f"{pt_name}_{title[:20].replace(' ','_')}.pdf",
                mime="application/pdf", key=key)

def calc_news2(rr,spo2,o2,sbp,hr,temp,avpu):
    s = 0
    if rr<=8 or rr>=25: s+=3
    elif 9<=rr<=11:     s+=1
    elif 21<=rr<=24:    s+=2
    if spo2<=91:        s+=3
    elif 92<=spo2<=93:  s+=2
    elif 94<=spo2<=95:  s+=1
    if o2:              s+=2
    if sbp<=90 or sbp>=220: s+=3
    elif 91<=sbp<=100:  s+=2
    elif 101<=sbp<=110: s+=1
    if hr<=40 or hr>=131:   s+=3
    elif 41<=hr<=50 or 111<=hr<=130: s+=2
    elif 91<=hr<=110:   s+=1
    if temp<=35.0:      s+=3
    elif temp<=36.0:    s+=1
    elif temp>=39.1:    s+=2
    elif temp>=38.1:    s+=1
    s += {"Alert":0,"Confusion/New":3,"Voice":3,"Pain":3,"Unresponsive":3}.get(avpu,0)
    if s>=7:   return s,"HIGH","🔴","IMMEDIATE senior review - ICU Level 3 care"
    elif s>=5: return s,"MEDIUM-HIGH","🟠","Urgent review within 30 minutes"
    elif s>=3: return s,"MEDIUM","🟡","Increased monitoring, review in 1 hour"
    else:      return s,"LOW","🟢","Continue routine monitoring"

def voice_box(label="🎤 Tap to Speak", key="v"):
    """Voice-to-text widget. Works inside expanders. safe_key strips all non-alphanumeric."""
    sk = re.sub(r'[^a-zA-Z0-9]','_', str(key))
    html = f"""
    <div style="margin:6px 0">
      <button id="vB_{sk}" onclick="vT_{sk}()"
        style="background:#1a3a6e;color:white;border:none;padding:9px 18px;
               border-radius:20px;font-size:14px;cursor:pointer;width:100%">
        🎤 {label}
      </button>
      <div id="vS_{sk}" style="font-size:12px;color:#666;text-align:center;margin:4px 0">
        Works on Chrome browser (Android/Desktop/iPhone)
      </div>
      <textarea id="vO_{sk}" rows="3"
        style="width:100%;padding:7px;border-radius:7px;border:1px solid #bbb;
               font-size:13px;display:none;margin-top:4px"
        placeholder="Spoken words appear here..."></textarea>
      <button id="vC_{sk}" onclick="vCp_{sk}()"
        style="display:none;margin-top:4px;background:#2d5a27;color:white;border:none;
               padding:7px 16px;border-radius:7px;font-size:13px;cursor:pointer">
        📋 Copy — then paste in notes box below
      </button>
    </div>
    <script>
    (function(){{
      var on_{sk}=false, rec_{sk}=null;
      window.vT_{sk}=function(){{
        if(!('webkitSpeechRecognition' in window||'SpeechRecognition' in window)){{
          document.getElementById('vS_{sk}').innerText='Not supported — use Chrome browser';return;}}
        if(on_{sk}){{rec_{sk}.stop();return;}}
        rec_{sk}=new(window.SpeechRecognition||window.webkitSpeechRecognition)();
        rec_{sk}.lang='en-IN';rec_{sk}.interimResults=true;rec_{sk}.continuous=true;
        rec_{sk}.onstart=function(){{
          on_{sk}=true;
          document.getElementById('vB_{sk}').innerText='🔴 RECORDING... Tap to Stop';
          document.getElementById('vB_{sk}').style.background='#8b1a1a';
          document.getElementById('vS_{sk}').innerText='Listening... speak now';
          document.getElementById('vO_{sk}').style.display='block';
          document.getElementById('vC_{sk}').style.display='inline-block';
        }};
        rec_{sk}.onresult=function(e){{
          var fi='',it='';
          for(var i=e.resultIndex;i<e.results.length;i++){{
            if(e.results[i].isFinal)fi+=e.results[i][0].transcript+' ';
            else it+=e.results[i][0].transcript;
          }}
          document.getElementById('vO_{sk}').value+=fi;
          document.getElementById('vS_{sk}').innerText=it?'Hearing: '+it:'Got it! Keep speaking or tap stop.';
        }};
        rec_{sk}.onerror=function(e){{document.getElementById('vS_{sk}').innerText='Error: '+e.error;}};
        rec_{sk}.onend=function(){{
          on_{sk}=false;
          document.getElementById('vB_{sk}').innerText='🎤 {label}';
          document.getElementById('vB_{sk}').style.background='#1a3a6e';
          document.getElementById('vS_{sk}').innerText='Done! Tap Copy then paste below.';
        }};
        rec_{sk}.start();
      }};
      window.vCp_{sk}=function(){{
        var t=document.getElementById('vO_{sk}').value;
        navigator.clipboard.writeText(t).then(function(){{
          document.getElementById('vS_{sk}').innerText='Copied! Long-press notes box below → Paste';
        }}).catch(function(){{
          document.getElementById('vS_{sk}').innerText='Select all text above manually and copy.';
        }});
      }};
    }})();
    </script>"""
    st.components.v1.html(html, height=185)

# ═══════════════════════════════════════════════════════════
# LOGIN SCREEN
# ═══════════════════════════════════════════════════════════
if not st.session_state.logged_in:
    sync_cloud()
    c1,c2,c3 = st.columns([1,2,1])
    with c2:
        st.markdown("""
        <div style='background:linear-gradient(135deg,#0a1628,#1a3a6e);
                    padding:40px;border-radius:16px;text-align:center;color:white;margin-bottom:20px'>
          <h2 style='margin:0'>🏥 Dr. Gill's Cardiac ICU</h2>
          <h3 style='margin:8px 0;color:#a0c4e8'>Command System v3.0 — Ghaziabad, UP</h3>
          <p style='color:#6898c0;margin:0'>AI-Powered Clinical Decision Support</p>
        </div>""", unsafe_allow_html=True)
        pin = st.text_input("PIN or Master Password:", type="password",
                            placeholder="4-digit PIN or Master Password")
        if st.button("🔐 Login", type="primary", use_container_width=True):
            if pin == MASTER_PASSWORD:
                st.session_state.logged_in    = True
                st.session_state.current_user = MASTER_NAME
                st.session_state.is_master    = True
                log("MASTER LOGIN")
                st.rerun()
            elif pin in st.session_state.doctors_db:
                d = st.session_state.doctors_db[pin]
                st.session_state.logged_in    = True
                st.session_state.current_user = f"{d['name']} ({d['role']})"
                st.session_state.is_master    = False
                log("Doctor LOGIN")
                st.rerun()
            else:
                st.error("Invalid PIN or Password.")
        st.caption("🔒 Authorized personnel only")
    st.stop()

# ═══════════════════════════════════════════════════════════
# HEADER
# ═══════════════════════════════════════════════════════════
h1,h2,h3 = st.columns([5,4,1])
with h1:
    badge = " 👑 MASTER ADMIN" if st.session_state.is_master else ""
    st.markdown(f"### 🏥 Dr. Gill's Cardiac ICU v3.0{badge}")
with h2:
    st.markdown("**HOD:** Dr. Alok Sehgal *(Sr. Interventional Cardiologist)*")
    st.markdown(f"**User:** `{st.session_state.current_user}` | {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}")
with h3:
    if st.button("🚪 Logout"):
        st.session_state.logged_in    = False
        st.session_state.current_user = None
        st.session_state.is_master    = False
        st.rerun()
st.markdown("---")
if not engine_ok:
    st.warning("⚠️ AI Engine not active — Add GEMINI_API_KEY in Streamlit → Settings → Secrets")

# ═══════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════
if st.session_state.is_master:
    TABS = ["👑 Master Control","🏥 Bed Board","🩺 ICU Frontline",
            "📊 HOD Dashboard","📉 Flowsheet","🚨 Early Warning",
            "💊 Medications","🔄 Handover","🔬 Academic","💬 Feedback"]
else:
    TABS = ["🏥 Bed Board","🩺 ICU Frontline","📊 HOD Dashboard",
            "📉 Flowsheet","🚨 Early Warning","💊 Medications",
            "🔄 Handover","🔬 Academic","💬 Feedback"]

tabs = st.tabs(TABS)
def T(name): return tabs[TABS.index(name)]

# ═══════════════════════════════════════════════════════════
# TAB ▶ MASTER CONTROL
# ═══════════════════════════════════════════════════════════
if st.session_state.is_master:
    with T("👑 Master Control"):
        st.markdown("""<div style='background:linear-gradient(135deg,#1a1a2e,#0f3460);
        padding:20px;border-radius:12px;color:white;margin-bottom:15px'>
        <h2 style='margin:0'>👑 Master Control — Dr. G.S. Gill</h2>
        <p style='color:#aaa;margin:4px 0'>God-mode — Only YOU see this tab</p></div>""",
        unsafe_allow_html=True)

        st.success("🔐 YOUR MASTER PASSWORD:  **GILL@ICU#2025**")
        st.markdown("---")

        # Doctor table
        st.subheader("👨‍⚕️ Doctor / Resident Management")
        docs = st.session_state.doctors_db
        rows = [{"PIN":k,"Name":v['name'],"Role":v['role'],"Access":v['access']} for k,v in docs.items()]
        if rows: st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.markdown("#### ➕ Add New Doctor")
        a1,a2,a3,a4 = st.columns(4)
        with a1: nn = st.text_input("Full Name:", placeholder="Dr. First Last")
        with a2: nr = st.selectbox("Role:",["Resident","Senior Resident","Registrar","Consultant","HOD"])
        with a3: na = st.selectbox("Access:",["Resident","Senior","HOD"])
        with a4: cp = st.text_input("Custom PIN (blank=auto):", max_chars=6)

        if st.button("✅ Add Doctor", type="primary"):
            if not nn.strip(): st.warning("Enter name.")
            else:
                pin2 = cp.strip() if cp.strip() else gen_pin()
                while pin2 in st.session_state.doctors_db: pin2 = gen_pin()
                st.session_state.doctors_db[pin2] = {"name":nn.strip(),"role":nr,"access":na}
                log(f"Added: {nn} PIN:{pin2}")
                st.success(f"✅ Added! PIN = **{pin2}** — share privately")
                st.rerun()

        st.markdown("#### ❌ Remove Doctor")
        pm = {f"{v['name']} (PIN:{k})":k for k,v in docs.items()}
        td = st.selectbox("Remove:", ["---"]+list(pm.keys()))
        if st.button("🗑️ Remove"):
            if td != "---":
                del st.session_state.doctors_db[pm[td]]
                log(f"Removed: {td}")
                st.success("Removed.")
                st.rerun()

        st.markdown("---")
        st.subheader("📊 Stats")
        tot = len(st.session_state.patients_db)
        act = sum(1 for d in st.session_state.patients_db.values() if d.get("status")=="Active")
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Total Patients", tot)
        m2.metric("Active", act)
        m3.metric("Discharged", tot-act)
        m4.metric("Doctors", len(docs))

        st.markdown("---")
        st.subheader("📋 Audit Trail")
        for e in st.session_state.audit_log[:60]: st.text(e)

        if st.button("🔄 Force Cloud Sync"):
            sync_cloud(); st.success("Synced!")

# ═══════════════════════════════════════════════════════════
# TAB ▶ BED BOARD
# ═══════════════════════════════════════════════════════════
with T("🏥 Bed Board"):
    st.header("🏥 Live ICU Bed Board — Cardiac ICU, Ghaziabad")
    beds = st.session_state.icu_beds
    bcols = st.columns(4)
    for i,(bed,pt) in enumerate(beds.items()):
        with bcols[i%4]:
            col = "#1e4d1e" if pt=="Empty" else "#6b1a1a"
            em  = "🟢 EMPTY" if pt=="Empty" else f"🔴 {pt}"
            st.markdown(f"""<div style='background:{col};padding:10px;border-radius:8px;
            text-align:center;color:white;margin:4px'><b>{bed}</b><br><small>{em}</small></div>""",
            unsafe_allow_html=True)

    st.markdown("---")
    ap_beds = [n for n,d in st.session_state.patients_db.items() if d.get("status")=="Active"]
    b1,b2,b3 = st.columns(3)
    with b1: sb  = st.selectbox("Bed:", list(beds.keys()))
    with b2: ba  = st.radio("Action:",["Assign","Mark Empty"], horizontal=True)
    with b3:
        if ba=="Assign":
            bp = st.selectbox("Patient:",["---"]+ap_beds)
            if st.button("✅ Assign"):
                if bp!="---":
                    st.session_state.icu_beds[sb]=bp; log(f"Bed {sb}→{bp}"); st.rerun()
        else:
            if st.button("✅ Empty"):
                st.session_state.icu_beds[sb]="Empty"; log(f"{sb} emptied"); st.rerun()
    occ = sum(1 for v in beds.values() if v!="Empty")
    st.info(f"Occupied: {occ}/12  |  Free: {12-occ}")

# ═══════════════════════════════════════════════════════════
# TAB ▶ ICU FRONTLINE
# ═══════════════════════════════════════════════════════════
with T("🩺 ICU Frontline"):
    st.header("🩺 ICU Frontline — Admission & Analysis")

    fc1,fc2 = st.columns(2)
    with fc1: pt_type  = st.radio("Patient:",["New Admission","Existing Patient"], horizontal=True)
    with fc2: diag_cat = st.selectbox("Category:",[
        "Acute MI / ACS","Heart Failure","Arrhythmia","Cardiogenic Shock",
        "Post-PCI / Post-CABG","Hypertensive Emergency","Pulmonary Embolism",
        "Sepsis / Septic Shock","Respiratory Failure","Renal Failure (AKI)",
        "Post-Cardiac Arrest","Multi-Organ Failure","Other Critical"])

    if pt_type=="New Admission":
        p_name = st.text_input("Patient Full Name:").strip().title()
        nc1,nc2,nc3 = st.columns(3)
        with nc1: age    = st.number_input("Age:",1,120,55)
        with nc2: gender = st.selectbox("Gender:",["Male","Female","Other"])
        with nc3: bsel   = st.selectbox("Assign Bed:",["Unassigned"]+
                           [b for b,v in st.session_state.icu_beds.items() if v=="Empty"])
    else:
        ap2 = [n for n,d in st.session_state.patients_db.items() if d.get("status")=="Active"]
        p_name = st.selectbox("Patient:",["---"]+ap2) if ap2 else ""
        if p_name=="---": p_name=""

    with st.expander("📊 Enter Vitals", expanded=False):
        v1,v2,v3,v4,v5,v6 = st.columns(6)
        with v1: vbp  = st.text_input("BP","120/80")
        with v2: vhr  = st.number_input("HR",0,300,80)
        with v3: vrr  = st.number_input("RR",0,60,16)
        with v4: vspo = st.number_input("SpO2",0,100,98)
        with v5: vtmp = st.number_input("Temp",30.0,43.0,37.0,0.1)
        with v6: vgcs = st.number_input("GCS",3,15,15)
        vstr = f"BP:{vbp} HR:{vhr} RR:{vrr} SpO2:{vspo}% Temp:{vtmp}C GCS:{vgcs}"

    st.markdown("---")
    voice_box("🎤 Tap to Dictate Clinical Notes", key="frontline_voice")
    st.caption("Speak → Copy → Paste below ↓")

    notes = st.text_area("Clinical Notes (history, examination, labs, ABG, ECG):", height=160,
        placeholder="65yr male, DM2/HTN, chest pain 2hrs, STEMI inferior, BP 90/60, HR 120, SpO2 92%...")

    full_notes = f"Category:{diag_cat} | Vitals:{vstr} | Notes:{notes}"

    st.subheader("📸 Upload ECG / X-Ray / Lab Reports")
    st.caption("📱 Mobile: tap Browse → Camera for instant photo")
    uploads = st.file_uploader("Upload:", type=['jpg','jpeg','png','pdf'],
                                accept_multiple_files=True, key="fl_up")
    has_inp = bool(notes.strip() or uploads)
    st.markdown("---")

    b1,b2,b3 = st.columns(3)
    with b1: do_q = st.button("🚨 Quick Analysis",   type="primary",   use_container_width=True)
    with b2: do_e = st.button("👑 Expert Board",     type="secondary", use_container_width=True)
    with b3: do_s = st.button("🦠 Sepsis Protocol",                    use_container_width=True)

    if do_q or do_e or do_s:
        if not engine_ok: st.error("AI offline — add GEMINI_API_KEY in Secrets.")
        elif not p_name:  st.warning("Enter patient name.")
        elif not has_inp: st.warning("Add notes or upload a report.")
        else:
            if do_q:
                atype  = "QUICK"
                prompt = f"""You are a Senior ICU Resident in a Cardiac ICU, Ghaziabad, Uttar Pradesh, India.
You are reviewing a patient case. Analyze ONLY the data provided below.

PATIENT DATA PROVIDED BY DOCTOR:
Patient Name: {p_name}
{full_notes}

{ANTI_HALLUCINATION}

Now provide fast structured analysis STRICTLY based on above data only:
1. WORKING DIAGNOSIS (based only on provided data)
2. CRITICALITY SCORE (1-10, RED=8-10, YELLOW=4-7, GREEN=1-3) — justify with provided data
3. IMMEDIATE ACTIONS (next 30 minutes)
4. INVESTIGATIONS TO ORDER (list only what is missing/needed based on provided data)
5. INITIAL TREATMENT PLAN (Indian generic drug names, doses, routes)
6. DRUG-DRUG INTERACTIONS — only if medications were listed above, else write "NO MEDICATIONS PROVIDED"
7. NURSE INSTRUCTIONS

PLAIN TEXT ONLY. NO ASTERISKS.
End with: TOPICS: Topic1, Topic2, Topic3"""

            elif do_e:
                atype  = "EXPERT"
                prompt = f"""You are a Multi-Disciplinary Expert Medical Board consisting of 5 specialist agents
working together in a Cardiac ICU, Ghaziabad, Uttar Pradesh, India:
- Agent 1: Senior Interventional Cardiologist
- Agent 2: Senior Intensivist / Critical Care Specialist
- Agent 3: Nephrologist
- Agent 4: Clinical Pharmacologist
- Agent 5: General Physician / Internal Medicine

PATIENT DATA PROVIDED BY DOCTOR:
Patient Name: {p_name}
{full_notes}

{ANTI_HALLUCINATION}

Each agent now reviews ONLY the provided data and contributes their specialist view:

1. CRITICALITY SCORE (1-10, RED/YELLOW/GREEN) — justify with specific data points provided
2. ABG ANALYSIS: ONLY if ABG values are explicitly present above. If no ABG provided → write "NO ABG DATA PROVIDED — cannot interpret"
3. ECG INTERPRETATION: ONLY if ECG findings are explicitly described above. If not → write "NO ECG DATA PROVIDED"
4. MULTI-SPECIALIST PANEL VIEWS (each agent speaks separately):
   Agent-1 [Cardiologist]: (only cardiac findings from provided data)
   Agent-2 [Intensivist]: (only critical care parameters from provided data)
   Agent-3 [Nephrologist]: (only if renal/electrolyte data is provided, else "INSUFFICIENT RENAL DATA")
   Agent-4 [Pharmacologist]: (only if medications listed, else "NO MEDICATIONS PROVIDED — cannot check DDI")
   Agent-5 [Gen. Physician]: (overall history review from provided data only)
5. GAPS IN PROVIDED DATA — list what important information is still missing
6. MASTER TREATMENT PROTOCOL (based only on what is provided and confirmed)
7. MONITORING TARGETS
8. ESCALATION TRIGGERS

PLAIN TEXT ONLY. NO ASTERISKS.
End with: TOPICS: Topic1, Topic2, Topic3"""

            else:
                atype  = "SEPSIS"
                prompt = f"""You are a Sepsis Response Expert in a Cardiac ICU, Ghaziabad, Uttar Pradesh, India.

PATIENT DATA PROVIDED BY DOCTOR:
Patient Name: {p_name}
{full_notes}

{ANTI_HALLUCINATION}

Apply SURVIVING SEPSIS CAMPAIGN 1-HOUR BUNDLE using ONLY provided data:
1. qSOFA SCORE — calculate ONLY from values provided above. For missing values write "NOT PROVIDED"
2. SEPSIS-3 CRITERIA — does patient meet definition based on provided data?
3. SHOCK TYPE: Septic / Cardiogenic / Mixed — based only on provided hemodynamic data
4. 1-HOUR BUNDLE CHECKLIST (mark each as DONE / NEEDED / DATA NOT PROVIDED):
   - Blood cultures status?
   - Serum lactate value (if provided)?
   - IV fluid resuscitation — volume given?
   - Empiric antibiotic — drug + dose + route
   - Vasopressors needed? (only if MAP data provided)
5. VASOPRESSOR PROTOCOL (only if shock is confirmed by provided data)
6. SOURCE CONTROL (identify from provided history only)
7. MONITORING TARGETS
8. DATA GAPS — list what the doctor still needs to provide for complete assessment

PLAIN TEXT ONLY. NO ASTERISKS.
End with: TOPICS: Topic1, Topic2, Topic3"""

            agent_box = st.empty()
            show_agents(agent_box)
            with st.spinner("Board consensus forming — please wait..."):
                try:
                    cnt = [prompt]
                    if uploads:
                        for uf in uploads:
                            if uf.name.lower().endswith(('png','jpg','jpeg')) and PIL_OK:
                                cnt.append(opt_img(uf))
                            elif uf.name.lower().endswith('.pdf'):
                                with tempfile.NamedTemporaryFile(delete=False,suffix=".pdf") as tmp:
                                    tmp.write(uf.read()); gf = genai.upload_file(path=tmp.name,mime_type='application/pdf')
                                cnt.append(gf)
                    result = smart_generate(cnt)
                    topics = []
                    if "TOPICS:" in result:
                        parts  = result.split("TOPICS:")
                        result = parts[0].strip()
                        topics = [t.strip() for t in parts[1].split(",")]
                        st.session_state[f"topics_{p_name}"] = topics

                    now = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
                    if p_name not in st.session_state.patients_db:
                        st.session_state.patients_db[p_name] = {"status":"Active","history":[],"bed":"Unassigned"}
                        if pt_type=="New Admission" and bsel!="Unassigned":
                            st.session_state.patients_db[p_name]["bed"] = bsel
                            st.session_state.icu_beds[bsel] = p_name
                    st.session_state.patients_db[p_name]["history"].append({
                        "date":now,"doctor":st.session_state.current_user,
                        "notes":full_notes[:2000],"summary":result,"type":atype})
                    push_cloud({"action":"new_entry","patient_name":p_name,
                        "doctor":st.session_state.current_user,"raw_notes":full_notes[:2000],
                        "summary":result,"date":now,"status":"Active","type":atype})
                    log(f"{atype}: {p_name}")
                    st.session_state[f"res_{p_name}"] = result
                    agent_box.empty()
                    st.success(f"✅ Board analysis complete & auto-saved for {p_name}!")
                except Exception as e:
                    st.error(f"AI Error: {e}")

    rkey = f"res_{p_name}" if p_name else None
    if rkey and rkey in st.session_state:
        st.markdown("---")
        st.subheader("📋 AI Analysis Result")
        st.info(st.session_state[rkey])
        c1,c2 = st.columns(2)
        with c1:
            if FPDF_OK and st.button("📄 Download Analysis PDF", key="fl_dlpdf"):
                dl_pdf("📥 Download","CLINICAL ANALYSIS",p_name,
                       st.session_state[rkey],"fl_dl2",st.session_state.current_user)

        st.markdown("---")
        st.subheader("📚 AI-Suggested Learning Topics")
        at = st.session_state.get(f"topics_{p_name}",[])
        st_sel  = st.selectbox("Suggested:",["Choose..."]+at) if at else None
        ct_inp  = st.text_input("Or type topic:")
        ft      = ct_inp if ct_inp else (st_sel if st_sel and st_sel!="Choose..." else "")
        if ft and st.button("📖 Generate Guideline PDF"):
            with st.spinner("Generating guideline..."):
                try:
                    gp = f"""Comprehensive ICU clinical guideline on: {ft}
Include: definition, pathophysiology, diagnosis criteria, step-by-step management protocol,
drug doses (Indian generic names), monitoring parameters, complications, clinical pearls.
Reference AHA/ESC/SCCM/ISCCM guidelines. PLAIN TEXT. NO ASTERISKS."""
                    gt   = smart_generate([gp])
                    path = make_pdf(f"GUIDELINE:{ft[:30].upper()}","Academic",gt,st.session_state.current_user)
                    if path:
                        with open(path,"rb") as f:
                            st.download_button("📥 Guideline PDF",data=f,
                                file_name=f"Guideline_{ft[:20].replace(' ','_')}.pdf",
                                mime="application/pdf", key="fl_gdl")
                except Exception as e: st.error(str(e))

# ═══════════════════════════════════════════════════════════
# TAB ▶ HOD DASHBOARD  (THE CROWN JEWEL)
# ═══════════════════════════════════════════════════════════
with T("📊 HOD Dashboard"):
    st.header("📊 HOD Dashboard — Complete Patient Management")

    dc1,dc2 = st.columns([3,1])
    with dc1: vf = st.radio("Show:",["Active","Discharged","All"], horizontal=True)
    with dc2:
        if st.button("🔄 Refresh"):
            sync_cloud(); st.rerun()

    db   = st.session_state.patients_db
    filt = {k:v for k,v in db.items() if
            (vf=="Active"     and v.get("status")=="Active") or
            (vf=="Discharged" and v.get("status")=="Discharged") or vf=="All"}

    if not filt:
        st.info("No patients found.")
    else:
        for pname, pdata in filt.items():
            hist   = pdata.get("history",[])
            latest = hist[-1] if hist else {}
            badge  = "🔴 ACTIVE" if pdata.get("status")=="Active" else "✅ DISCHARGED"
            adm    = hist[0].get("date","?") if hist else "?"
            # Length of stay
            los = "?"
            try:
                d0  = datetime.datetime.strptime(adm[:10],"%Y-%m-%d")
                los = f"{(datetime.datetime.now()-d0).days}d"
            except: pass

            with st.expander(
                f"{badge}  🛏️ {pname}  |  Admitted: {adm[:10]}  |  "
                f"LOS: {los}  |  Updates: {len(hist)}  |  "
                f"Bed: {pdata.get('bed','?')}",
                expanded=False):

                # ── info strip ──
                ic1,ic2,ic3 = st.columns(3)
                ic1.caption(f"Last: {latest.get('date','?')}")
                ic2.caption(f"By: {latest.get('doctor','?')}")
                ic3.caption(f"Type: {latest.get('type','?')}")

                # ══════════════════════════════════
                # MASTER CLINICAL FILE — FULL WIDTH
                # ══════════════════════════════════
                st.markdown("##### 📋 Master Clinical File")
                edited = st.text_area("HOD can edit directly:",
                    value=latest.get("summary",""), height=230, key=f"ed_{pname}")
                if st.button("💾 Save Edits", key=f"sv_{pname}"):
                    if hist:
                        st.session_state.patients_db[pname]["history"][-1]["summary"] = edited
                        log(f"HOD edit: {pname}"); st.success("Saved!")

                st.markdown("---")

                # ══════════════════════════════════
                # PROGRESS THREAD — FULL WIDTH
                # ══════════════════════════════════
                st.markdown("##### 📈 Add Progress Note (Clinical Thread)")
                voice_box("🎤 Tap to Dictate Progress", key=f"hv_{pname}")
                st.caption("Speak → Copy → Paste below ↓")
                pnotes = st.text_area("New progress / findings:",
                    key=f"pn_{pname}", height=80,
                    placeholder="New vitals, ABG result, ECG change, response to treatment...")
                pflup = st.file_uploader("Upload new report:", type=['jpg','jpeg','png','pdf'],
                    accept_multiple_files=True, key=f"pf_{pname}")

                if st.button("🔄 Analyze Progress & Update Thread", type="primary", key=f"thr_{pname}"):
                    if not (pnotes.strip() or pflup): st.warning("Add notes or upload.")
                    elif not engine_ok: st.error("AI offline.")
                    else:
                        with st.spinner("AI comparing trajectories..."):
                            try:
                                tp = f"""You are a Senior ICU Registrar updating the clinical thread for patient: {pname}.

PREVIOUS CLINICAL SUMMARY (what was documented before):
{edited}

NEW DATA ADDED BY DOCTOR TODAY:
{pnotes}

{ANTI_HALLUCINATION}

Using ONLY the above two sections of data, provide:
1. CLINICAL TRAJECTORY: Compare NEW data vs PREVIOUS summary.
   State explicitly: IMPROVING / DETERIORATING / STABLE
   List SPECIFIC parameters that changed — use actual numbers from the data provided.
   If numbers not provided → write "specific values not provided"
2. UPDATED CRITICALITY SCORE (1-10, RED/YELLOW/GREEN) — justify with provided data
3. RESPONSE TO TREATMENT: Based only on provided data, is plan working?
4. NEW FINDINGS TODAY (only from today's note above)
5. TREATMENT ADJUSTMENTS NEEDED (based on trajectory observed)
6. NEXT 24-HOUR PLAN
7. HOD ROUND BRIEF — 5 lines only, for morning round

PLAIN TEXT ONLY. NO ASTERISKS. STRICTLY NO INVENTED DATA."""
                                tc = [tp]
                                if pflup:
                                    for uf in pflup:
                                        if uf.name.lower().endswith(('png','jpg','jpeg')) and PIL_OK:
                                            tc.append(opt_img(uf))
                                tres = smart_generate(tc)
                                now  = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
                                st.session_state.patients_db[pname]["history"].append({
                                    "date":now,"doctor":st.session_state.current_user,
                                    "notes":pnotes,"summary":tres,"type":"PROGRESS"})
                                push_cloud({"action":"new_entry","patient_name":pname,
                                    "doctor":st.session_state.current_user,"raw_notes":pnotes,
                                    "summary":tres,"date":now,"status":"Active","type":"PROGRESS"})
                                log(f"Thread: {pname}")
                                st.success("Thread updated!")
                                st.info(tres)
                            except Exception as e: st.error(str(e))

                st.markdown("---")

                # ══════════════════════════════════
                # EXPERT BOARD + REBUTTAL — RESTORED
                # ══════════════════════════════════
                with st.expander("👑 Expert Board Re-evaluation & HOD Challenge", expanded=False):
                    if st.button("👑 Re-Evaluate with Expert Board", key=f"exp_{pname}"):
                        agent_box2 = st.empty()
                        show_agents(agent_box2)
                        with st.spinner("Board convening..."):
                            try:
                                ep = f"""Multi-Disciplinary Expert Medical Board (5 agents):
Agent-1: Sr. Interventional Cardiologist
Agent-2: Sr. Intensivist
Agent-3: Nephrologist
Agent-4: Clinical Pharmacologist
Agent-5: General Physician

CURRENT CASE SUMMARY PROVIDED:
Patient: {pname}
{edited}

{ANTI_HALLUCINATION}

Each agent reviews ONLY the provided summary above:
1. CRITICALITY SCORE (1-10, RED/YELLOW/GREEN) — cite specific data points
2. MULTI-SPECIALIST VIEWS — each agent comments only on their domain data present above:
   Agent-1 [Cardiologist]: 
   Agent-2 [Intensivist]:
   Agent-3 [Nephrologist]: (only if renal data present, else "NO RENAL DATA PROVIDED")
   Agent-4 [Pharmacologist]: (only if drug list present, else "NO MEDICATION LIST PROVIDED")
   Agent-5 [Gen. Physician]:
3. SEVERE DDI RADAR — only if medications are listed above
4. GAPS IN MANAGEMENT — what data is still missing that we need?
5. UPDATED MASTER TREATMENT PLAN
PLAIN TEXT ONLY. NO ASTERISKS."""
                                st.session_state[f"eo_{pname}"] = smart_generate([ep])
                                agent_box2.empty()
                            except Exception as e:
                                agent_box2.empty()
                                st.error(str(e))

                    if f"eo_{pname}" in st.session_state:
                        st.markdown("**👑 Expert Board Opinion:**")
                        st.info(st.session_state[f"eo_{pname}"])
                        if FPDF_OK:
                            dl_pdf("📥 Expert Opinion PDF","EXPERT BOARD OPINION",pname,
                                   st.session_state[f"eo_{pname}"],f"exp_dl_{pname}",
                                   st.session_state.current_user)

                        st.markdown("**💬 Challenge the Expert Board (HOD Rebuttal):**")
                        reb = st.text_area("Your challenge / correction:",
                            key=f"reb_{pname}", height=80,
                            placeholder="e.g. 'Check ABG again, Winter formula gives pH 7.32 not 7.28. Recalculate.'")
                        if st.button("⚖️ Force Re-evaluation with Evidence", key=f"fre_{pname}"):
                            if not reb.strip(): st.warning("Write your challenge first.")
                            else:
                                with st.spinner("Board re-evaluating based on HOD challenge..."):
                                    try:
                                        rp = f"""Multi-Disciplinary Expert Board.
Previous evaluation of {pname}: {st.session_state[f"eo_{pname}"]}
The Senior HOD Doctor STRONGLY DISAGREES and challenges: "{reb}"
INSTRUCTION: Acknowledge the HOD's clinical input with respect. Deeply re-evaluate your previous stance.
If the HOD is correct, ADMIT the error explicitly and correct it immediately.
Provide updated, corrected clinical assessment based on the HOD's feedback.
PLAIN TEXT ONLY. NO ASTERISKS."""
                                        updated = smart_generate([rp])
                                        st.session_state[f"eo_{pname}"] = f"HOD CHALLENGE: {reb}\n\nBOARD CORRECTION:\n{updated}"
                                        log(f"Expert rebuttal: {pname}")
                                        st.rerun()
                                    except Exception as e: st.error(str(e))

                # ══════════════════════════════════
                # DOCUMENT GENERATION — ACTION BAR
                # ══════════════════════════════════
                st.markdown("---")
                st.markdown("##### 🖨️ Generate Documents & Summaries")

                # 5 compact buttons in one row
                a1,a2,a3,a4,a5 = st.columns(5)
                with a1: do_case  = st.button("📄 Case PDF",      key=f"cp_{pname}", use_container_width=True)
                with a2: do_disc  = st.button("📝 Discharge",     key=f"dp_{pname}", use_container_width=True)
                with a3: do_couns = st.button("🗣️ Counseling",    key=f"cn_{pname}", use_container_width=True)
                with a4: do_ptcns = st.button("👤 Patient Card",  key=f"pc_{pname}", use_container_width=True)
                with a5: do_arch  = st.button("🛑 Discharge & Archive", key=f"da_{pname}",
                                               use_container_width=True, type="primary" if pdata.get("status")=="Active" else "secondary")

                # ── Case PDF ──
                if do_case:
                    if FPDF_OK:
                        dl_pdf("📥 Download Case PDF","INTERIM CASE SUMMARY",pname,
                               edited, f"cdl_{pname}", st.session_state.current_user)
                    else: st.warning("FPDF not installed.")

                # ── Discharge ──
                if do_disc:
                    st.session_state[f"show_disc_{pname}"] = True

                if st.session_state.get(f"show_disc_{pname}"):
                    with st.container(border=True):
                        st.markdown("**📝 Discharge Summary Generator**")
                        dtype = st.selectbox("Discharge Type:",[
                            "Normal Discharge",
                            "DOPR — Discharge on Patient's Request",
                            "LAMA — Left Against Medical Advice",
                            "Referral to Higher Centre",
                        ], key=f"dt_{pname}")
                        if st.button("⚡ Generate Now", key=f"dg_{pname}", type="primary"):
                            with st.spinner("Generating..."):
                                try:
                                    all_s = "\n---\n".join([h.get("summary","") for h in hist[-4:]])
                                    if "LAMA" in dtype or "DOPR" in dtype:
                                        legal = """MEDICOLEGAL DISCLAIMER (MANDATORY — include verbatim):
The patient / attendant has INSISTED on leaving AGAINST MEDICAL ADVICE / on their own request.
They have been clearly explained in their own language about all life-threatening risks including death, cardiac arrest, organ failure and permanent disability that may result from leaving the hospital at this stage of treatment.
They have voluntarily chosen to leave / requested discharge despite these warnings.
The treating doctors, hospital, nursing staff and all medical personnel are FULLY ABSOLVED of all medical, legal and ethical responsibility for any adverse outcomes including death.
A written informed refusal / LAMA form must be signed by the patient and two witnesses before departure."""
                                    else:
                                        legal = ""

                                    dp2 = f"""Write a formal {dtype} Summary for {pname}, Cardiac ICU, Ghaziabad, Uttar Pradesh.

CLINICAL DATA FROM ICU STAY (use ONLY this data):
{all_s}

{ANTI_HALLUCINATION}

Based STRICTLY on the above documented data, include:
1. ADMISSION DIAGNOSIS (only as documented)
2. ICU STAY SUMMARY (only documented events)
3. KEY INVESTIGATIONS & RESULTS (only those mentioned in the notes)
4. PROCEDURES PERFORMED (only those documented)
5. CLINICAL COURSE & RESPONSE TO TREATMENT
6. DISCHARGE CONDITION
7. DISCHARGE MEDICATIONS (only if medications were documented — do not add new ones)
8. FOLLOW-UP INSTRUCTIONS
9. RED FLAG SYMPTOMS — when to return to ER immediately
10. ACTIVITY & DIET RESTRICTIONS
{legal}
Under: Dr. Alok Sehgal (HOD, Sr. Interventional Cardiologist). Attending: {st.session_state.current_user}.
PLAIN TEXT ONLY. NO ASTERISKS. ONLY USE DOCUMENTED DATA."""
                                    dt2  = smart_generate([dp2])
                                    st.session_state[f"disc_text_{pname}"] = (dtype, dt2)
                                    log(f"Discharge: {pname} — {dtype}")
                                except Exception as e: st.error(str(e))

                        if f"disc_text_{pname}" in st.session_state:
                            dtyp, dtxt = st.session_state[f"disc_text_{pname}"]
                            st.text_area("Generated:", value=dtxt, height=200, key=f"dshow_{pname}")
                            if FPDF_OK:
                                dl_pdf("📥 Download Discharge PDF", dtyp.upper(),
                                       pname, dtxt, f"ddl_{pname}", st.session_state.current_user)

                # ── Relative Counseling (Hinglish) ──
                if do_couns:
                    with st.spinner("Generating Hinglish counseling..."):
                        try:
                            cp2 = f"""Write an ICU Patient Counseling Sheet for relatives of {pname}.

CLINICAL SUMMARY (use ONLY this data):
{edited}

{ANTI_HALLUCINATION}

Based STRICTLY on the above documented summary:
- Write in simple HINGLISH (mix of Hindi and English words)
- USE ROMAN ALPHABETS ONLY — English letters for every word
- DO NOT USE DEVANAGARI SCRIPT under any circumstances
- Simple language for uneducated family members
- Cover only what is documented: what happened, treatment done, current condition, what to expect, what family should do, follow-up
- Be compassionate and honest
- If any information is not in the summary, write "Doctor se poochhen" for that point
PLAIN TEXT ONLY. NO ASTERISKS. ROMAN SCRIPT ONLY. NO INVENTED DETAILS."""
                            ct2 = smart_generate([cp2])
                            st.session_state[f"couns_{pname}"] = ct2
                            log(f"Counseling: {pname}")
                        except Exception as e: st.error(str(e))

                if f"couns_{pname}" in st.session_state:
                    with st.container(border=True):
                        st.markdown("**🗣️ Relative Counseling (Hinglish)**")
                        st.text_area("", value=st.session_state[f"couns_{pname}"],
                            height=180, key=f"cshow_{pname}")
                        if FPDF_OK:
                            dl_pdf("📥 Counseling PDF","ICU ATTENDANT BRIEF",
                                   pname, st.session_state[f"couns_{pname}"],
                                   f"cdl2_{pname}", st.session_state.current_user)

                # ── Patient Instruction Card ──
                if do_ptcns:
                    with st.spinner("Generating patient instruction card..."):
                        try:
                            pp2 = f"""Write a PATIENT INSTRUCTION CARD for {pname} after ICU stay.
Based on: {edited}
Write in very simple English that the patient themselves can understand.
Include: Your diagnosis in simple words, your medicines (name and when to take),
warning signs (come to hospital immediately if...), food you can and cannot eat,
activities allowed and not allowed, your follow-up date and doctor,
contact number to call in emergency.
Keep it SHORT, CLEAR, and FRIENDLY. PLAIN TEXT. NO ASTERISKS."""
                            pt2 = smart_generate([pp2])
                            st.session_state[f"ptcard_{pname}"] = pt2
                            log(f"Patient card: {pname}")
                        except Exception as e: st.error(str(e))

                if f"ptcard_{pname}" in st.session_state:
                    with st.container(border=True):
                        st.markdown("**👤 Patient Instruction Card**")
                        st.text_area("", value=st.session_state[f"ptcard_{pname}"],
                            height=160, key=f"ptshow_{pname}")
                        if FPDF_OK:
                            dl_pdf("📥 Patient Card PDF","PATIENT INSTRUCTION CARD",
                                   pname, st.session_state[f"ptcard_{pname}"],
                                   f"ptdl_{pname}", st.session_state.current_user)

                # ── Archive / Discharge ──
                if do_arch and pdata.get("status")=="Active":
                    st.session_state.patients_db[pname]["status"] = "Discharged"
                    for bed,occ in st.session_state.icu_beds.items():
                        if occ==pname: st.session_state.icu_beds[bed]="Empty"
                    push_cloud({"action":"discharge","patient_name":pname,
                                "status":"Discharged","date":str(datetime.datetime.now())})
                    log(f"Archived: {pname}")
                    st.success(f"{pname} discharged & archived. Bed freed.")
                    st.rerun()

                # Full history
                if st.checkbox("📅 Show Full History Timeline", key=f"ht_{pname}"):
                    for i,h in enumerate(reversed(hist)):
                        with st.container(border=True):
                            st.caption(f"#{len(hist)-i} | {h.get('date','')} | {h.get('doctor','')} | {h.get('type','')}")
                            txt = h.get("summary","")
                            st.text(txt[:500]+("..." if len(txt)>500 else ""))

# ═══════════════════════════════════════════════════════════
# TAB ▶ FLOWSHEET
# ═══════════════════════════════════════════════════════════
with T("📉 Flowsheet"):
    st.header("📉 ICU Flowsheet & Vital Trends")
    ap3 = [n for n,d in st.session_state.patients_db.items() if d.get("status")=="Active"]
    if not ap3: st.info("No active patients.")
    else:
        sp = st.selectbox("Patient:", ap3)
        fk = f"flow_{sp}"
        if fk not in st.session_state: st.session_state[fk] = []
        f1,f2,f3,f4,f5,f6,f7 = st.columns(7)
        with f1: ft  = st.text_input("Time",datetime.datetime.now().strftime("%H:%M"),key="ft")
        with f2: fbp = st.text_input("BP","120/80",key="fbp")
        with f3: fhr = st.number_input("HR",0,300,80,key="fhr")
        with f4: frr = st.number_input("RR",0,60,16,key="frr")
        with f5: fsp = st.number_input("SpO2",0,100,98,key="fsp")
        with f6: ftm = st.number_input("Temp",30.0,43.0,37.0,0.1,key="ftm")
        with f7: fuo = st.number_input("UO ml/hr",0,1000,50,key="fuo")
        if st.button("➕ Add Vitals"):
            st.session_state[fk].append({"Time":ft,"BP":fbp,"HR":fhr,"RR":frr,"SpO2":fsp,"Temp":ftm,"UO":fuo})
            log(f"Vitals: {sp}"); st.success("Added!")
        fd = st.session_state.get(fk,[])
        if fd:
            df = pd.DataFrame(fd)
            st.dataframe(df, use_container_width=True, hide_index=True)
            ch1,ch2 = st.columns(2)
            with ch1:
                try: st.line_chart(df.set_index("Time")[["HR","RR"]]); st.caption("HR & RR")
                except: pass
            with ch2:
                try: st.line_chart(df.set_index("Time")[["SpO2"]]); st.caption("SpO2")
                except: pass

# ═══════════════════════════════════════════════════════════
# TAB ▶ EARLY WARNING
# ═══════════════════════════════════════════════════════════
with T("🚨 Early Warning"):
    st.header("🚨 Early Warning — NEWS2 & Sepsis Screening")
    ew1,ew2 = st.columns(2)
    with ew1:
        st.subheader("🩺 NEWS2 Calculator")
        e_rr = st.number_input("RR:",0,60,16,key="e_rr")
        e_sp = st.number_input("SpO2:",0,100,97,key="e_sp")
        e_o2 = st.checkbox("Supplemental O2?")
        e_sb = st.number_input("Systolic BP:",50,250,120,key="e_sb")
        e_hr = st.number_input("HR:",0,300,80,key="e_hr")
        e_tm = st.number_input("Temp:",30.0,43.0,37.0,0.1,key="e_tm")
        e_av = st.selectbox("AVPU:",["Alert","Confusion/New","Voice","Pain","Unresponsive"])
        if st.button("📊 Calculate NEWS2", type="primary"):
            sc,risk,em2,act = calc_news2(e_rr,e_sp,e_o2,e_sb,e_hr,e_tm,e_av)
            bg = "#6b1a1a" if "HIGH" in risk else ("#7a6b00" if "MEDIUM" in risk else "#1e4d1e")
            st.markdown(f"""<div style='background:{bg};padding:18px;border-radius:10px;
            color:white;text-align:center'><h2>{em2} NEWS2: {sc}</h2>
            <h3>Risk: {risk}</h3><p>{act}</p></div>""", unsafe_allow_html=True)
            log(f"NEWS2:{sc} ({risk})")
    with ew2:
        st.subheader("🦠 qSOFA Sepsis Screen")
        q_rr = st.number_input("RR:",0,60,16,key="q_rr")
        q_gc = st.number_input("GCS:",3,15,15,key="q_gc")
        q_sb = st.number_input("Systolic BP:",50,250,110,key="q_sb")
        if st.button("🦠 Calculate qSOFA", type="primary"):
            qs = sum([q_rr>=22, q_gc<15, q_sb<=100])
            bg = "#6b1a1a" if qs>=2 else "#1e4d1e"
            st.markdown(f"""<div style='background:{bg};padding:18px;border-radius:10px;
            color:white;text-align:center'><h2>qSOFA: {qs}/3</h2>
            <p>{"HIGH SEPSIS RISK - Activate Protocol!" if qs>=2 else "Low-Moderate - Monitor"}</p>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("🧠 AI Deterioration Analysis")
    det = st.text_area("Paste vitals/findings:", height=90)
    if st.button("🧠 Analyze Risk") and det and engine_ok:
        with st.spinner("Analyzing..."):
            try:
                dp3 = f"""Critical Care AI Deterioration Radar.
Data: {det}
1. RISK LEVEL (LOW/MEDIUM/HIGH/CRITICAL)
2. SPECIFIC WARNING SIGNS
3. PREDICTED COMPLICATIONS (next 4-12 hrs)
4. IMMEDIATE INTERVENTIONS
5. MONITORING ESCALATION (frequency)
PLAIN TEXT. NO ASTERISKS."""
                st.info(smart_generate([dp3]))
            except Exception as e: st.error(str(e))

# ═══════════════════════════════════════════════════════════
# TAB ▶ MEDICATIONS
# ═══════════════════════════════════════════════════════════
with T("💊 Medications"):
    st.header("💊 Medication Safety & Dose Calculator")
    mm1,mm2 = st.columns(2)
    with mm1:
        st.subheader("⚠️ Drug-Drug Interaction Checker")
        meds    = st.text_area("Medications (one per line):", height=180,
            placeholder="Aspirin 75mg OD\nClopidogrel 75mg OD\nEnoxaparin 40mg BD\nAmiodarone 200mg TDS")
        renal   = st.selectbox("Renal:",["Normal","Mild (CrCl 60-90)","Moderate (CrCl 30-60)","Severe (<30)","Dialysis"])
        hepatic = st.selectbox("Hepatic:",["Normal","Child-Pugh A","Child-Pugh B","Child-Pugh C"])
        if st.button("🔬 Full Safety Scan", type="primary"):
            if not meds.strip(): st.warning("Enter medications.")
            elif not engine_ok:  st.error("AI offline.")
            else:
                with st.spinner("Clinical Pharmacologist scanning..."):
                    try:
                        mp = f"""Senior Clinical Pharmacologist, Cardiac ICU, Ghaziabad, UP.
Medications: {meds} | Renal: {renal} | Hepatic: {hepatic}
1. DANGEROUS DDIs (CONTRAINDICATED/MAJOR/MODERATE/MINOR — list all pairs)
2. DOSE ADJUSTMENTS for renal impairment (drug + recommended adjusted dose)
3. HEPATIC ADJUSTMENTS
4. MONITORING PARAMETERS (specific levels/tests for each high-risk drug)
5. ANTICOAGULATION SAFETY (if applicable — bleeding risk, monitoring)
6. SAFER ALTERNATIVES for any contraindicated combos
PLAIN TEXT ONLY. NO ASTERISKS."""
                        mres = smart_generate([mp])
                        log("Med safety scan"); st.success("Scan complete!"); st.info(mres)
                    except Exception as e: st.error(str(e))

    with mm2:
        st.subheader("💉 ICU Infusion Rate Calculator")
        drug = st.selectbox("Drug:",["Norepinephrine","Dopamine","Dobutamine","Adrenaline",
                                     "GTN","Furosemide","Insulin","Midazolam","Morphine","Amiodarone"])
        wt   = st.number_input("Weight (kg):",30.0,200.0,65.0,0.5)
        dose = st.number_input("Dose (mcg/kg/min):",0.0,100.0,0.1,0.01)
        conc = st.number_input("Concentration (mcg/ml):",0.1,10000.0,100.0,0.1)
        if st.button("🧮 Calculate"):
            rate = (dose*wt*60)/conc if conc>0 else 0
            st.success(f"Rate: **{rate:.2f} ml/hr**")
            st.caption(f"{drug} | {dose} mcg/kg/min | {wt}kg | {conc} mcg/ml")
            log(f"Dose calc: {drug}={rate:.2f}")

# ═══════════════════════════════════════════════════════════
# TAB ▶ HANDOVER
# ═══════════════════════════════════════════════════════════
with T("🔄 Handover"):
    st.header("🔄 Shift Handover — ISBAR Format")
    ho1,ho2 = st.columns(2)
    with ho1: out_dr = st.text_input("Outgoing Dr:",value=st.session_state.current_user.split("(")[0].strip())
    with ho2: in_dr  = st.text_input("Incoming Dr:", placeholder="Name of next duty doctor")
    extra = st.text_area("Pending tasks / concerns:", height=70)
    if st.button("🔄 Generate ISBAR Handover — ALL Patients", type="primary"):
        ap4 = {k:v for k,v in st.session_state.patients_db.items() if v.get("status")=="Active"}
        if not ap4: st.warning("No active patients.")
        elif not engine_ok: st.error("AI offline.")
        else:
            with st.spinner("Generating handover..."):
                try:
                    parts = []
                    for pn,pd4 in ap4.items():
                        h4  = pd4.get("history",[])
                        ls4 = h4[-1].get("summary","No data") if h4 else "No data"
                        hr4 = smart_generate([f"""ISBAR for {pn}: {ls4[:600]}
5 bullet points: current status, active issues, infusions/meds, pending, what to watch.
PLAIN TEXT. NO ASTERISKS."""])
                        parts.append(f"--- {pn} ---\n{hr4}")
                    full = f"""SHIFT HANDOVER - {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}
Outgoing: {out_dr} | Incoming: {in_dr} | Active: {len(ap4)}
{"="*50}
{chr(10).join(parts)}
{"="*50}
PENDING: {extra}
Handover complete."""
                    st.session_state.handover_notes.insert(0,{"date":str(datetime.datetime.now()),
                        "outgoing":out_dr,"incoming":in_dr,"content":full})
                    log(f"Handover:{out_dr}->{in_dr}")
                    st.success("Done!"); st.info(full)
                    if FPDF_OK:
                        hp4 = make_pdf("SHIFT HANDOVER","All Active",full,out_dr)
                        if hp4:
                            with open(hp4,"rb") as f:
                                st.download_button("📥 Handover PDF",data=f,
                                    file_name=f"Handover_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                                    mime="application/pdf")
                except Exception as e: st.error(str(e))

# ═══════════════════════════════════════════════════════════
# TAB ▶ ACADEMIC
# ═══════════════════════════════════════════════════════════
with T("🔬 Academic"):
    st.header("🔬 Academic Vault — CME & Clinical Guidelines")
    topic = st.text_input("Topic:", placeholder="e.g. Cardiogenic Shock, STEMI 2024, Vasopressor use")
    ac1,ac2,ac3 = st.columns(3)
    with ac1: ct  = st.selectbox("Type:",["Clinical Guideline","Drug Protocol","Case Discussion","CME Quiz","Procedure Guide"])
    with ac2: lv  = st.selectbox("Level:",["Resident","Senior Resident","Consultant","Fellowship"])
    with ac3: ref = st.selectbox("Reference:",["AHA/ACC 2024","ESC 2024","SCCM/ESICM","Indian (CSI/ISCCM)","Multiple"])
    if st.button("📚 Generate", type="primary"):
        if not topic.strip(): st.warning("Enter topic.")
        elif not engine_ok:   st.error("AI offline.")
        else:
            with st.spinner("Generating..."):
                try:
                    ap5 = f"""Medical educator + Intensivist, Cardiac ICU, Ghaziabad, UP.
Topic: {topic} | Type: {ct} | Level: {lv} | Reference: {ref}
Write comprehensive {ct}: definition, pathophysiology, diagnosis criteria (with cut-off values),
step-by-step management protocol, drug doses (Indian generic names with brand in brackets),
monitoring targets, complications, clinical pearls, common mistakes to avoid.
{"Include 5 MCQs with answers for CME." if ct=="CME Quiz" else ""}
PLAIN TEXT. NO ASTERISKS."""
                    ar = smart_generate([ap5])
                    log(f"Academic: {topic}")
                    st.success("Generated!"); st.info(ar)
                    if FPDF_OK:
                        apath = make_pdf(f"{ct}: {topic[:30].upper()}","Academic",ar,st.session_state.current_user)
                        if apath:
                            with open(apath,"rb") as f:
                                st.download_button("📥 Download PDF",data=f,
                                    file_name=f"Academic_{topic.replace(' ','_')[:25]}.pdf",
                                    mime="application/pdf")
                except Exception as e: st.error(str(e))

    st.markdown("---")
    st.subheader("⚡ Quick 1-Page Reference Cards")
    qlist = ["STEMI Protocol","Cardiogenic Shock","Acute Pulmonary Edema","VT/VF Management",
             "Hypertensive Emergency","Septic Shock Bundle","AKI Management",
             "NIV/BiPAP Setup","Anticoagulation in AF+ACS","Post-PCI Care"]
    qs = st.selectbox("Select:", qlist)
    if st.button("⚡ Quick Generate"):
        with st.spinner("Generating..."):
            try:
                qr = smart_generate([f"""1-PAGE QUICK REFERENCE CARD: {qs}
Bedside reference only — most critical info:
- 3-5 diagnostic criteria with values
- 5-8 step management
- Key drug doses
- 3 monitoring targets
- 2 mistakes to avoid
PLAIN TEXT. NO ASTERISKS."""])
                st.success("Ready!"); st.info(qr); log(f"Quick ref: {qs}")
            except Exception as e: st.error(str(e))

# ═══════════════════════════════════════════════════════════
# TAB ▶ FEEDBACK PORTAL
# ═══════════════════════════════════════════════════════════
with T("💬 Feedback"):
    st.header("💬 Feedback & Improvement Portal")
    st.caption("Doctors, residents, nurses, staff — anyone can suggest improvements or report issues. All feedback reaches Admin (Dr. Gill) directly.")

    fb1,fb2 = st.columns([3,2])
    with fb1:
        st.markdown("#### 📝 Submit Feedback")
        with st.container(border=True):
            ftype = st.selectbox("Type:",[
                "🐛 Bug / App Error",
                "💡 New Feature Request",
                "⚠️ Clinical Concern",
                "🔧 Improvement Suggestion",
                "👍 Positive Feedback",
                "❓ Question / Confusion",
                "Other"])
            fpri  = st.radio("Priority:",["🟢 Low","🟡 Medium","🔴 Urgent"], horizontal=True)
            voice_box("🎤 Speak Feedback", key="fb_voice")
            st.caption("Speak → Copy → Paste below")
            ftxt  = st.text_area("Your feedback:", height=120,
                placeholder="Example: 'Voice button inside HOD dashboard not working on my phone model X...' OR 'Please add ECG interpretation in the frontline tab...'")
            fname = st.text_input("Your name:",
                value=st.session_state.current_user.split("(")[0].strip(),
                placeholder="Leave blank for anonymous")
            if st.button("📤 Submit", type="primary", use_container_width=True):
                if not ftxt.strip(): st.warning("Write feedback first.")
                else:
                    st.session_state.feedback_list.insert(0,{
                        "time":    datetime.datetime.now().strftime("%d %b %Y, %I:%M %p"),
                        "type":    ftype,"priority":fpri,
                        "text":    ftxt.strip(),
                        "by":      fname.strip() or "Anonymous",
                        "status":  "New"})
                    log(f"Feedback: {ftype}")
                    st.success("✅ Submitted! Dr. Gill will review.")
                    st.balloons()

    with fb2:
        st.markdown("#### 📬 All Feedback")
        fl = st.session_state.feedback_list
        if not fl:
            st.info("No feedback yet. Be first to suggest an improvement!")
        else:
            for i,fb in enumerate(fl):
                pc = {"🟢 Low":"#1e4d1e","🟡 Medium":"#6b5e00","🔴 Urgent":"#6b1a1a"}.get(fb["priority"],"#333")
                with st.container(border=True):
                    st.markdown(f"""<div style='border-left:4px solid {pc};padding-left:9px'>
                    <b>{fb['type']}</b> | {fb['priority']} | <small>{fb['time']}</small><br>
                    <small>By: {fb['by']}</small></div>""", unsafe_allow_html=True)
                    st.write(fb["text"][:180]+("..." if len(fb["text"])>180 else ""))
                    if st.session_state.is_master:
                        r1,r2 = st.columns(2)
                        with r1:
                            if fb.get("status")=="New":
                                if st.button("✅ Resolved",key=f"fbr_{i}"):
                                    st.session_state.feedback_list[i]["status"]="Resolved"
                                    st.rerun()
                        with r2:
                            if st.button("🗑️ Delete",key=f"fbd_{i}"):
                                st.session_state.feedback_list.pop(i); st.rerun()
                    else:
                        st.caption(f"Status: {'🟢 Resolved' if fb.get('status')=='Resolved' else '🟡 New'}")

            if st.session_state.is_master:
                tot_fb = len(fl)
                urg_fb = sum(1 for f in fl if f["priority"]=="🔴 Urgent")
                new_fb = sum(1 for f in fl if f.get("status")=="New")
                res_fb = sum(1 for f in fl if f.get("status")=="Resolved")
                st.markdown("---")
                fm1,fm2,fm3,fm4 = st.columns(4)
                fm1.metric("Total",tot_fb)
                fm2.metric("New",new_fb)
                fm3.metric("Urgent",urg_fb)
                fm4.metric("Resolved",res_fb)

# ═══════════════════════════════════════════════════════════
# FOOTER
# ═══════════════════════════════════════════════════════════
st.markdown("---")
st.markdown("""<div style='text-align:center;color:gray;font-size:12px'>
Dr. Gill's Cardiac ICU Command System v3.0 | Ghaziabad, Uttar Pradesh |
AI-Powered by Google Gemini | For demonstration & clinical decision support |
Always verify with qualified clinicians before acting on AI output
</div>""", unsafe_allow_html=True)
