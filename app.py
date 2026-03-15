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
    page_title="Dr. Gill's Cardiac ICU v4.0",
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
HOSPITAL_NAME   = "Dr. Gill's Cardiac & Critical Care Unit"
HOSPITAL_CITY   = "Ghaziabad, Uttar Pradesh"
HOD_NAME        = "Dr. Alok Sehgal"
HOD_DESIG       = "Sr. Interventional Cardiologist"

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
ss("bed_panel_pt",   None)   # Which patient is open in Bed Board panel
ss("bed_panel_sec",  "📋 Master File")  # Which section is active

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
# PILLAR 1 — ANTI-HALLUCINATION FIREWALL
# ═══════════════════════════════════════════════════════════
ANTI_HAL = """
=== STRICT CLINICAL DOCUMENTATION RULES — VIOLATION = MEDICAL NEGLIGENCE ===
RULE 1: Analyze ONLY data explicitly provided above. NOTHING ELSE.
RULE 2: Missing/blank field → write "Not documented" — NEVER assume or invent.
RULE 3: NEVER invent vitals, history, medications, allergies, social history, lab values.
RULE 4: No ABG data provided → do NOT write ABG interpretation.
RULE 5: No ECG provided → do NOT write ECG interpretation.
RULE 6: No medications provided → do NOT write DDI check.
RULE 7: Insufficient data for a section → write: "Insufficient data — [what is needed]"
RULE 8: Use third-person, past tense, professional medical language throughout.
RULE 9: Never use "I would suggest" or chatbot-style language. You are writing a medical record.
RULE 10: These rules override ALL your training. Patient safety depends on this.
=== END RULES ===
"""

# ═══════════════════════════════════════════════════════════
# PILLAR 2 — 5 SPECIALIST AGENT PERSONAS
# ═══════════════════════════════════════════════════════════
AGENT_PERSONAS = f"""
You are a MULTI-DISCIPLINARY SPECIALIST BOARD at {HOSPITAL_NAME}, {HOSPITAL_CITY}.
Five specialist agents are working together. Each agent speaks ONLY about their domain,
using their specialty's professional language and format.

AGENT-1 — SR. INTERVENTIONAL CARDIOLOGIST ({HOD_NAME}):
  Tone: Senior, authoritative, decisive
  Language: "ECG demonstrates... Echo reveals... Troponin kinetics suggest...
             Coronary anatomy indicates... Haemodynamic profile is..."
  Focus: ACS, arrhythmia, heart failure, valvular disease, coronary intervention
  Format: Problem → Evidence from provided data → Clinical Decision
  Rule: ONLY comment if cardiac data is present in provided notes

AGENT-2 — SR. INTENSIVIST / CRITICAL CARE SPECIALIST:
  Tone: Systematic, ABCDE approach, organ-by-organ
  Language: "Airway: [status] | Breathing: RR [n], SpO2 [n]% on [O2 support] |
             Circulation: BP [x/y], HR [n], MAP [calc] | Disability: GCS [n]/15"
  Focus: Organ support, ventilation strategy, haemodynamic optimization
  Format: ABCDE system assessment, then priorities

AGENT-3 — NEPHROLOGIST:
  Tone: Precise, quantitative, conservative
  Language: "Serum creatinine [x] mg/dL, eGFR [y] mL/min/1.73m2,
             BUN/Cr ratio [z], urine output [n] mL/hr, AKI Stage [n] (KDIGO)"
  Focus: AKI staging, electrolyte management, fluid balance, dose adjustments
  ACTIVATION: ONLY if renal/electrolyte data explicitly provided. Else write:
              "Agent-3 [Nephrologist]: Renal parameters not provided — cannot assess"

AGENT-4 — CLINICAL PHARMACOLOGIST:
  Tone: Technical, evidence-based, safety-focused
  Language: "Drug A + Drug B: [CONTRAINDICATED/MAJOR/MODERATE] interaction
             via [mechanism]. Risk: [specific adverse effect]. Action: [specific recommendation]"
  Focus: DDI screening, dose adjustment for organ impairment, pharmacokinetics
  ACTIVATION: ONLY if medication list is explicitly provided. Else write:
              "Agent-4 [Pharmacologist]: No medication list provided — DDI screening not possible"
  Format: Table-style: Drug | Interaction | Severity | Action Required

AGENT-5 — GENERAL PHYSICIAN / INTERNAL MEDICINE:
  Tone: Holistic, systematic, narrative
  Language: "Overall, the patient presents with... The dominant problem is...
             Comorbidities include... Systemic review reveals..."
  Focus: Full history review, comorbidity management, systemic complications
  Format: Problem list with priority ranking
"""

# ═══════════════════════════════════════════════════════════
# PILLAR 1 — PROFESSIONAL OUTPUT FORMAT TEMPLATE
# ═══════════════════════════════════════════════════════════
def get_assessment_format(pt_name, doctor, dt_str):
    return f"""
You MUST produce output in EXACTLY this professional Indian hospital format.
Do NOT deviate from this structure. Do NOT add conversational text outside these sections.

════════════════════════════════════════════════════════
{HOSPITAL_NAME.upper()}
CARDIAC INTENSIVE CARE UNIT — {HOSPITAL_CITY.upper()}
════════════════════════════════════════════════════════
DATE: {dt_str}
ADMITTING PHYSICIAN: {doctor}
HOD: {HOD_NAME} ({HOD_DESIG})
────────────────────────────────────────────────────────
PATIENT: {pt_name}
UNIT: Cardiac ICU
────────────────────────────────────────────────────────

PRESENTING COMPLAINT:
[1 line — chief complaint ONLY from provided data]

HISTORY OF PRESENT ILLNESS:
[Narrative: "A [age]-year-old [sex] with known h/o [ONLY listed comorbidities],
presented with [complaint] for [duration], [relevant history from notes only]..."]

PAST MEDICAL HISTORY:     [ONLY if provided | else: Not documented]
PAST SURGICAL HISTORY:    [ONLY if provided | else: Not documented]
DRUG HISTORY:             [ONLY if provided | else: Not documented]
ALLERGIES:                [ONLY if provided | else: NKDA — Not documented]
FAMILY HISTORY:           [ONLY if provided | else: Not documented]
SOCIAL HISTORY:           [ONLY if provided | else: Not documented]

────────────────────────────────────────────────────────
ON EXAMINATION:
General Condition:  [from notes only]
Vitals:             BP: [x/y] mmHg | HR: [n] bpm | RR: [n]/min | SpO2: [n]% | Temp: [n]°C | GCS: [n]/15
Cardiovascular:     [from notes only | else: Not examined / Not documented]
Respiratory:        [from notes only | else: Not documented]
Abdomen:            [from notes only | else: Not documented]
Neurology:          [from notes only | else: Not documented]
Peripheral Pulses:  [from notes only | else: Not documented]

────────────────────────────────────────────────────────
INVESTIGATIONS:
[List ONLY values explicitly provided. For each missing investigation write: "Pending / Not provided"]
ECG:    [findings only if described | else: Pending]
Echo:   [findings only if described | else: Pending]
ABG:    [values only if provided | else: Pending]
CXR:    [findings only if described | else: Pending]
Labs:   [only listed values with units]

────────────────────────────────────────────────────────
ASSESSMENT:
Primary Diagnosis:        [most supported by provided data]
Secondary Diagnoses:      [only if data supports | else: None documented]
Differential Diagnoses:   [2-3 possibilities based on available data]
Criticality Score:        [1-10] — [RED (8-10 Critical) / YELLOW (4-7 Guarded) / GREEN (1-3 Stable)]

────────────────────────────────────────────────────────
MULTI-SPECIALIST BOARD OPINION:

Agent-1 [Sr. Cardiologist — {HOD_NAME}]:
[Cardiac opinion using cardiologist's professional language — only if cardiac data present]

Agent-2 [Sr. Intensivist]:
[ABCDE-format ICU assessment — based only on provided data]

Agent-3 [Nephrologist]:
[Renal assessment — ONLY if renal data provided | else: "Renal parameters not provided"]

Agent-4 [Clinical Pharmacologist]:
[DDI table — ONLY if medications listed | else: "No medication list — DDI screening not possible"]

Agent-5 [General Physician]:
[Problem list with priorities — based on provided history]

────────────────────────────────────────────────────────
TREATMENT PLAN:
1. Monitoring:          [parameters, frequency — hourly/4-hrly/daily]
2. IV Access & Fluids:  [type, rate, monitoring]
3. Medications:
   [Drug Name | Dose | Route | Frequency | Duration]
4. Investigations Ordered: [list what is still needed]
5. Nursing Instructions:   [specific tasks, vitals frequency, alerts]
6. Escalation Triggers:    [specific parameters that require senior call]

────────────────────────────────────────────────────────
DOCUMENTATION GAPS:
[List important missing data that doctor should provide for complete assessment]

────────────────────────────────────────────────────────
Signed: {doctor} | {dt_str}
HOD: {HOD_NAME} | {HOSPITAL_NAME}
════════════════════════════════════════════════════════
"""

# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════
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
    rep = {
        '\u2014':'-','\u2013':'-','\u2012':'-',
        '\u2018':"'",'\u2019':"'",'\u201c':'"','\u201d':'"',
        '\u2022':'-','\u25cf':'-','\u2023':'-',
        '\u2026':'...','\u00b7':'.','\u00ae':'(R)','\u00a9':'(C)',
        '\u00b0':' deg','\u00b1':'+/-','\u00d7':'x','\u00f7':'/',
        '\u00b5':'u','\u2192':'->','\u2190':'<-',
        '\u2264':'<=','\u2265':'>=',
        '\u03b1':'alpha','\u03b2':'beta','\u03b3':'gamma',
    }
    for old,new in rep.items(): txt = txt.replace(old,new)
    return txt.encode('latin-1','replace').decode('latin-1')

def smart_generate(contents):
    if not GENAI_OK:  raise Exception("google-generativeai not installed.")
    if not engine_ok: raise Exception("GEMINI_API_KEY missing — add in Streamlit Secrets.")
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
    pdf.set_fill_color(10,50,100)
    pdf.rect(0,0,210,24,'F')
    pdf.set_text_color(255,255,255)
    pdf.set_font("Arial",'B',13)
    pdf.cell(0,8,txt=clean_pdf(HOSPITAL_NAME.upper()),ln=True,align='C')
    pdf.set_font("Arial",'B',10)
    pdf.cell(0,7,txt=clean_pdf(f"Cardiac ICU | {HOSPITAL_CITY}"),ln=True,align='C')
    pdf.set_text_color(0,0,0); pdf.ln(3)
    pdf.set_font("Arial",'B',13)
    pdf.cell(0,9,txt=clean_pdf(title.upper()),ln=True,align='C')
    pdf.line(10,pdf.get_y(),200,pdf.get_y()); pdf.ln(2)
    pdf.set_font("Arial",'B',9)
    pdf.set_fill_color(230,240,255)
    pdf.cell(0,7,clean_pdf(f"  Patient: {pt_name}"),ln=True,fill=True)
    pdf.cell(0,7,clean_pdf(f"  HOD: {HOD_NAME} ({HOD_DESIG})  |  Doctor: {doctor}"),ln=True,fill=True)
    pdf.cell(0,7,clean_pdf(f"  Generated: {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}"),ln=True,fill=True)
    pdf.ln(4)
    pdf.set_font("Arial",size=10)
    body = clean_pdf(content.replace('**','').replace('*','-').replace('#',''))
    pdf.multi_cell(0,6,txt=body)
    pdf.set_y(-18); pdf.set_font("Arial",'I',7); pdf.set_text_color(120,120,120)
    pdf.cell(0,5,clean_pdf(f"CONFIDENTIAL - FOR CLINICAL USE ONLY | {HOSPITAL_NAME} | {HOSPITAL_CITY}"),align='C')
    tmpdir = tempfile.mkdtemp()
    fpath  = os.path.join(tmpdir,f"{pt_name}_{title[:20].replace(' ','_')}.pdf")
    pdf.output(fpath)
    return fpath

def dl_pdf_btn(label, title, pt_name, content, key, doctor=""):
    path = make_pdf(title, pt_name, content, doctor)
    if path:
        with open(path,"rb") as f:
            st.download_button(label, data=f,
                file_name=f"{pt_name}_{title[:18].replace(' ','_')}.pdf",
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
    if s>=7:   return s,"HIGH","🔴","IMMEDIATE — Senior review now, consider ICU Level 3"
    elif s>=5: return s,"MEDIUM-HIGH","🟠","Urgent review within 30 minutes"
    elif s>=3: return s,"MEDIUM","🟡","Increased monitoring, review within 1 hour"
    else:      return s,"LOW","🟢","Continue routine monitoring"

def voice_box(label="🎤 Tap to Speak", key="v"):
    sk = re.sub(r'[^a-zA-Z0-9]','_', str(key))
    html = f"""
    <div style="margin:5px 0">
      <button id="vB_{sk}" onclick="vT_{sk}()"
        style="background:#1a3a6e;color:white;border:none;padding:8px 16px;
               border-radius:18px;font-size:13px;cursor:pointer;width:100%">
        🎤 {label}
      </button>
      <div id="vS_{sk}" style="font-size:11px;color:#777;text-align:center;margin:3px 0">
        Works on Chrome browser
      </div>
      <textarea id="vO_{sk}" rows="2"
        style="width:100%;padding:6px;border-radius:6px;border:1px solid #bbb;
               font-size:12px;display:none;margin-top:3px"
        placeholder="Spoken words appear here..."></textarea>
      <button id="vC_{sk}" onclick="vCp_{sk}()"
        style="display:none;margin-top:3px;background:#2d5a27;color:white;border:none;
               padding:6px 14px;border-radius:6px;font-size:12px;cursor:pointer">
        📋 Copy — paste in notes below
      </button>
    </div>
    <script>
    (function(){{
      var on_{sk}=false,rec_{sk}=null;
      window.vT_{sk}=function(){{
        if(!('webkitSpeechRecognition' in window||'SpeechRecognition' in window)){{
          document.getElementById('vS_{sk}').innerText='Use Chrome browser for voice';return;}}
        if(on_{sk}){{rec_{sk}.stop();return;}}
        rec_{sk}=new(window.SpeechRecognition||window.webkitSpeechRecognition)();
        rec_{sk}.lang='en-IN';rec_{sk}.interimResults=true;rec_{sk}.continuous=true;
        rec_{sk}.onstart=function(){{
          on_{sk}=true;
          document.getElementById('vB_{sk}').innerText='🔴 Recording... Tap to stop';
          document.getElementById('vB_{sk}').style.background='#8b1a1a';
          document.getElementById('vS_{sk}').innerText='Listening...';
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
          document.getElementById('vS_{sk}').innerText=it?'Hearing: '+it:'Keep speaking or tap stop.';
        }};
        rec_{sk}.onerror=function(e){{document.getElementById('vS_{sk}').innerText='Error: '+e.error;}};
        rec_{sk}.onend=function(){{
          on_{sk}=false;
          document.getElementById('vB_{sk}').innerText='🎤 {label}';
          document.getElementById('vB_{sk}').style.background='#1a3a6e';
          document.getElementById('vS_{sk}').innerText='Done! Copy then paste below.';
        }};
        rec_{sk}.start();
      }};
      window.vCp_{sk}=function(){{
        var t=document.getElementById('vO_{sk}').value;
        navigator.clipboard.writeText(t).then(function(){{
          document.getElementById('vS_{sk}').innerText='Copied! Paste in notes box below.';
        }}).catch(function(){{
          document.getElementById('vS_{sk}').innerText='Select text above manually and copy.';
        }});
      }};
    }})();
    </script>"""
    st.components.v1.html(html, height=160)

def show_agents():
    st.markdown("""
    <div style='background:#0a1628;padding:10px 14px;border-radius:8px;
                color:#a0c4e8;font-family:monospace;font-size:11px;margin:6px 0'>
    🤖 <b>MULTI-SPECIALIST AGENT BOARD — ACTIVATING</b><br>
    &nbsp;⚡ Agent-1 [Sr. Cardiologist]&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;→ Analyzing cardiac data...<br>
    &nbsp;⚡ Agent-2 [Sr. Intensivist]&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;→ ABCDE critical review...<br>
    &nbsp;⚡ Agent-3 [Nephrologist]&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;→ Renal &amp; electrolyte check...<br>
    &nbsp;⚡ Agent-4 [Pharmacologist]&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;→ DDI scanning...<br>
    &nbsp;⚡ Agent-5 [General Physician]&nbsp;&nbsp;→ Systemic review...<br>
    &nbsp;🔄 Board consensus forming...
    </div>""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════
# PATIENT PANEL — used in BOTH Bed Board AND HOD Dashboard
# ═══════════════════════════════════════════════════════════
def render_patient_panel(pname, pdata):
    """
    FULL-SCREEN PATIENT PANEL — Accordion layout.
    Left: section buttons (fixed).  Right: selected section full width.
    On mobile: buttons on top, content below.
    """
    hist   = pdata.get("history",[])
    latest = hist[-1] if hist else {}
    badge  = "🔴 ACTIVE" if pdata.get("status")=="Active" else "✅ DISCHARGED"
    bed    = pdata.get("bed","Unassigned")

    # ── Patient header strip ──
    st.markdown(f"""
    <div style='background:linear-gradient(90deg,#0a1628,#1a3a6e);
                padding:12px 18px;border-radius:10px;color:white;margin-bottom:10px'>
      <span style='font-size:18px;font-weight:bold'>🛏️ {pname}</span>
      &nbsp;&nbsp;|&nbsp;&nbsp;{badge}
      &nbsp;&nbsp;|&nbsp;&nbsp;Bed: {bed}
      &nbsp;&nbsp;|&nbsp;&nbsp;Admitted: {hist[0].get('date','?')[:10] if hist else '?'}
      &nbsp;&nbsp;|&nbsp;&nbsp;Updates: {len(hist)}
      &nbsp;&nbsp;|&nbsp;&nbsp;Last Dr: {latest.get('doctor','?')}
    </div>""", unsafe_allow_html=True)

    # ── Section key ──
    panel_key = f"sec_{re.sub(r'[^a-zA-Z0-9]','_',pname)}"
    ss(panel_key, "📋 Master File")

    SECTIONS = [
        "📋 Master File",
        "📈 Progress Note",
        "👑 Expert Board",
        "📄 Documents",
        "🔀 Transfer Bed",
        "🛑 Discharge"
    ]

    # ── LAYOUT: buttons col + content col ──
    btn_col, content_col = st.columns([1, 4])

    with btn_col:
        st.markdown("**Sections:**")
        for sec in SECTIONS:
            is_active = st.session_state[panel_key] == sec
            btn_style = "primary" if is_active else "secondary"
            if st.button(sec, key=f"btn_{panel_key}_{sec}", use_container_width=True, type=btn_style):
                st.session_state[panel_key] = sec
                st.rerun()

    with content_col:
        active_sec = st.session_state[panel_key]
        st.markdown(f"#### {active_sec}")
        st.markdown("---")

        # ══════════════════════════════════════════
        # SECTION: MASTER FILE
        # ══════════════════════════════════════════
        if active_sec == "📋 Master File":
            edited = st.text_area(
                "Master Clinical File — HOD can edit:",
                value=latest.get("summary","No data yet."),
                height=420,
                key=f"mf_{pname}"
            )
            c1,c2 = st.columns(2)
            with c1:
                if st.button("💾 Save Edits", key=f"mfsave_{pname}", type="primary"):
                    if hist:
                        st.session_state.patients_db[pname]["history"][-1]["summary"] = edited
                        log(f"HOD edit: {pname}"); st.success("✅ Saved!")
            with c2:
                if FPDF_OK and st.button("📄 Download as PDF", key=f"mfdl_{pname}"):
                    dl_pdf_btn("📥 Download Case PDF","INTERIM CASE SUMMARY",
                               pname, edited, f"mfdl2_{pname}", st.session_state.current_user)

            # Full history toggle
            st.markdown("---")
            if st.checkbox("📅 Show Full History Timeline", key=f"ht_{pname}"):
                for i,h in enumerate(reversed(hist)):
                    with st.container(border=True):
                        st.caption(f"#{len(hist)-i} | {h.get('date','')} | {h.get('doctor','')} | {h.get('type','')}")
                        txt = h.get("summary","")
                        st.text(txt[:600]+("..." if len(txt)>600 else ""))

        # ══════════════════════════════════════════
        # SECTION: PROGRESS NOTE (SOAP format)
        # ══════════════════════════════════════════
        elif active_sec == "📈 Progress Note":
            los_day = "?"
            try:
                d0  = datetime.datetime.strptime(hist[0].get("date","")[:10],"%Y-%m-%d")
                los_day = f"Day {(datetime.datetime.now()-d0).days + 1} of admission"
            except: pass
            st.caption(f"{los_day} | Duty: {st.session_state.current_user}")

            voice_box("🎤 Dictate Progress Note", key=f"pv_{pname}")
            st.caption("Speak → Copy → Paste below ↓")

            pnotes = st.text_area(
                "New progress / findings today:",
                key=f"pn_{pname}", height=160,
                placeholder="""Enter today's data:
- Vitals: BP [x/y], HR [n], RR [n], SpO2 [n]%, Temp [n]
- Subjective: Patient complaints / nursing report
- Today's labs / ECG / X-ray findings
- Response to treatment
- Any new events overnight"""
            )
            pflup = st.file_uploader("Upload new ECG / Report / Image:",
                type=['jpg','jpeg','png','pdf'], accept_multiple_files=True, key=f"pf_{pname}")

            if st.button("🔄 Analyze Progress & Update Thread",
                         type="primary", key=f"pthr_{pname}", use_container_width=True):
                if not (pnotes.strip() or pflup):
                    st.warning("Add notes or upload a report.")
                elif not engine_ok:
                    st.error("AI offline.")
                else:
                    prev_summary = latest.get("summary","No previous data.")
                    show_agents()
                    with st.spinner("Board analyzing progress..."):
                        try:
                            now_str = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
                            los_day2 = los_day
                            tp = f"""{AGENT_PERSONAS}
{ANTI_HAL}

You are producing a formal ICU PROGRESS NOTE (SOAP format).

PATIENT: {pname}
DATE: {now_str} | {los_day2}
DUTY DOCTOR: {st.session_state.current_user}
HOD: {HOD_NAME} ({HOD_DESIG})
HOSPITAL: {HOSPITAL_NAME}, {HOSPITAL_CITY}

PREVIOUS CLINICAL SUMMARY (documented before):
{prev_summary}

NEW DATA PROVIDED TODAY:
{pnotes}

{ANTI_HAL}

Produce output in EXACTLY this SOAP format:

════════════════════════════════════════════════
ICU PROGRESS NOTE — {HOSPITAL_NAME.upper()}
DATE: {now_str} | {los_day2}
Duty Doctor: {st.session_state.current_user}
HOD: {HOD_NAME} | {HOSPITAL_CITY}
────────────────────────────────────────────────
SUBJECTIVE:
[Patient complaints from today's notes only | Nursing overnight report if mentioned]

OBJECTIVE:
Vitals today:     [ONLY from today's provided data]
Current infusions: [ONLY if mentioned in today's note | else: Not updated]
Labs today:        [ONLY values provided today]
ECG today:         [ONLY if described today | else: Not provided]
CXR today:         [ONLY if described today | else: Not provided]

ASSESSMENT:
Clinical Trajectory: [IMPROVING / DETERIORATING / STABLE]
Evidence: [List specific parameters that changed with numbers from provided data]
Updated Criticality Score: [1-10] — [RED/YELLOW/GREEN]
Response to Treatment: [based only on provided trajectory data]

PLAN (Problem-by-Problem):
Problem 1: [diagnosis] → [action today]
Problem 2: [diagnosis] → [action today]
Treatment Adjustments: [what to add/stop/modify based on provided data]
Next 24-Hour Plan: [specific plan]

HOD ROUND BRIEF (5 lines max, for morning round):
[Concise summary for HOD round]

Signed: {st.session_state.current_user} | {now_str}
════════════════════════════════════════════════

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
                            log(f"Progress: {pname}")
                            st.success("✅ Progress note added to clinical thread!")
                            st.info(tres)
                        except Exception as e: st.error(str(e))

        # ══════════════════════════════════════════
        # SECTION: EXPERT BOARD + REBUTTAL
        # ══════════════════════════════════════════
        elif active_sec == "👑 Expert Board":
            edited_for_exp = latest.get("summary","")
            st.caption("Multi-Disciplinary Board will review the current Master File")

            if st.button("👑 Convene Expert Board",
                         type="primary", key=f"exp_{pname}", use_container_width=True):
                show_agents()
                with st.spinner("Board convening..."):
                    try:
                        now_str = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
                        ep = f"""{AGENT_PERSONAS}
{ANTI_HAL}

PATIENT: {pname}
DATE: {now_str}
DUTY DOCTOR: {st.session_state.current_user}
HOD: {HOD_NAME} ({HOD_DESIG})

CURRENT DOCUMENTED CASE SUMMARY:
{edited_for_exp}

{ANTI_HAL}

Each specialist agent reviews ONLY the documented data above and provides their opinion:

════════════════════════════════════════════════
MULTI-SPECIALIST BOARD ASSESSMENT — {HOSPITAL_NAME.upper()}
DATE: {now_str} | Patient: {pname}
════════════════════════════════════════════════

CRITICALITY SCORE: [1-10] — [RED/YELLOW/GREEN] — justify with specific documented data

Agent-1 [Sr. Cardiologist — {HOD_NAME}]:
[Cardiac assessment using cardiologist professional language — only cardiac data documented]

Agent-2 [Sr. Intensivist]:
[ABCDE assessment — based only on documented data]

Agent-3 [Nephrologist]:
[Renal assessment — ONLY if renal data documented | else: "Renal parameters not documented"]

Agent-4 [Clinical Pharmacologist]:
Drug | Interaction | Severity | Action
[ONLY if medication list documented | else: "No medication list — DDI not possible"]

Agent-5 [General Physician]:
Problem List (priority order):
1. [problem] — [status from documented data]
2. [problem] — [status from documented data]

GAPS IN MANAGEMENT:
[What important data is missing that could affect management]

UPDATED TREATMENT PLAN:
[Based strictly on documented data]

════════════════════════════════════════════════
PLAIN TEXT ONLY. NO ASTERISKS. STRICTLY NO INVENTED DATA."""
                        st.session_state[f"eo_{pname}"] = smart_generate([ep])
                        log(f"Expert board: {pname}")
                    except Exception as e: st.error(str(e))

            if f"eo_{pname}" in st.session_state:
                st.info(st.session_state[f"eo_{pname}"])
                if FPDF_OK:
                    dl_pdf_btn("📥 Expert Board PDF","EXPERT BOARD ASSESSMENT",
                               pname, st.session_state[f"eo_{pname}"],
                               f"expdl_{pname}", st.session_state.current_user)

                st.markdown("---")
                st.markdown("**💬 HOD Challenge — Disagree with the Board?**")
                st.caption("If the board made an error, challenge it here. The board will correct itself.")
                reb = st.text_area(
                    "Your challenge / correction:",
                    key=f"reb_{pname}", height=100,
                    placeholder="e.g. 'ABG shows pH 7.28, pCO2 58, HCO3 26 — recalculate with Boston criteria. Respiratory acidosis not metabolic.'"
                )
                if st.button("⚖️ Force Board Re-evaluation",
                             key=f"fre_{pname}", use_container_width=True):
                    if not reb.strip():
                        st.warning("Write your challenge first.")
                    else:
                        show_agents()
                        with st.spinner("Board re-evaluating with HOD correction..."):
                            try:
                                rp = f"""{AGENT_PERSONAS}
You previously evaluated patient {pname}.
Your previous assessment: {st.session_state[f"eo_{pname}"]}
The Senior HOD Doctor challenges this assessment: "{reb}"

INSTRUCTION: With utmost respect to the HOD's clinical expertise:
1. Carefully re-examine the HOD's challenge
2. If the HOD is correct — EXPLICITLY acknowledge the error and correct it
3. If further clarification is needed — ask for specific data
4. Provide the corrected assessment in the same professional format
PLAIN TEXT ONLY. NO ASTERISKS."""
                                updated = smart_generate([rp])
                                st.session_state[f"eo_{pname}"] = f"HOD CHALLENGE:\n{reb}\n\nBOARD CORRECTED RESPONSE:\n{updated}"
                                log(f"Board rebuttal: {pname}")
                                st.rerun()
                            except Exception as e: st.error(str(e))

        # ══════════════════════════════════════════
        # SECTION: DOCUMENTS (All 7 types)
        # ══════════════════════════════════════════
        elif active_sec == "📄 Documents":
            all_summaries = "\n---\n".join([h.get("summary","") for h in hist[-4:]])
            st.caption("Select document type → Generate → Download PDF")

            doc_type = st.selectbox("Select Document Type:", [
                "-- Choose --",
                "📋 Interim Case Summary (Current Status)",
                "🏥 Discharge Summary — Normal",
                "📋 DOPR — Discharge on Patient's Request",
                "⚠️ LAMA — Left Against Medical Advice",
                "🚑 Referral to Higher Centre",
                "🗣️ Relative Counseling (Hinglish — Roman Script)",
                "👤 Patient Instruction Card (Simple English)",
                "🌙 Shift / Handover Summary",
            ], key=f"doctype_{pname}")

            if st.button("⚡ Generate Document", type="primary",
                         key=f"gendoc_{pname}", use_container_width=True):
                if doc_type == "-- Choose --":
                    st.warning("Select a document type.")
                elif not engine_ok:
                    st.error("AI offline.")
                else:
                    now_str = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")

                    # LAMA / DOPR legal disclaimer
                    lama_legal = f"""
MEDICOLEGAL DISCLAIMER — MANDATORY — INCLUDE VERBATIM:
The patient / family member has INSISTED on leaving hospital AGAINST MEDICAL ADVICE / on their own request.
They have been clearly counselled in their own language regarding ALL life-threatening risks including:
sudden cardiac death, irreversible organ failure, stroke, and other permanent disabilities
that may result from premature departure from hospital at this stage of treatment.
They have VOLUNTARILY chosen to leave / requested discharge despite full understanding of these risks.
The treating physicians, {HOSPITAL_NAME}, and all medical staff are FULLY AND COMPLETELY ABSOLVED
of all medical, legal, and ethical responsibility for any adverse outcomes including death.
A written, signed LAMA/DOPR form MUST be obtained, countersigned by two witnesses, before departure.
"""
                    prompts = {
                        "📋 Interim Case Summary (Current Status)": f"""You are a medical scribe at {HOSPITAL_NAME}, {HOSPITAL_CITY}.
{ANTI_HAL}
PATIENT: {pname} | DATE: {now_str}
HOD: {HOD_NAME} ({HOD_DESIG}) | DOCTOR: {st.session_state.current_user}
DOCUMENTED CLINICAL DATA: {all_summaries}
{ANTI_HAL}
Produce a professional INTERIM CASE SUMMARY using only documented data.
Format: Diagnosis | Clinical Status | Active Problems | Current Treatment | Monitoring Plan
Third-person, past tense, professional medical language. PLAIN TEXT. NO ASTERISKS.""",

                        "🏥 Discharge Summary — Normal": f"""You are a medical scribe at {HOSPITAL_NAME}, {HOSPITAL_CITY}.
{ANTI_HAL}
PATIENT: {pname} | DATE: {now_str}
HOD: {HOD_NAME} ({HOD_DESIG}) | DOCTOR: {st.session_state.current_user}
DOCUMENTED ICU STAY DATA: {all_summaries}
{ANTI_HAL}
Produce formal HOSPITAL DISCHARGE SUMMARY in standard Indian hospital format:
Hospital Name | HOD | Admitting Doctor | Dates | LOS
FINAL DIAGNOSIS (Primary + Secondary — only documented)
ICD-10 CODE: [if identifiable from documented diagnosis]
BRIEF CLINICAL HISTORY: [narrative from documented data only]
INVESTIGATIONS: [only values documented]
PROCEDURES PERFORMED: [only documented]
HOSPITAL COURSE: [documented events only]
CONDITION AT DISCHARGE: [from documented data]
DISCHARGE MEDICATIONS:
Sr | Drug | Dose | Route | Frequency | Duration
[only medications documented — do not add new ones]
FOLLOW-UP: [date/department if documented | else: As advised by HOD]
RED FLAGS: Return immediately if [relevant to diagnosis]
DIET RESTRICTIONS: [relevant to documented diagnosis]
ACTIVITY RESTRICTIONS: [relevant to documented diagnosis]
Signed: {st.session_state.current_user} | HOD: {HOD_NAME}
PLAIN TEXT. NO ASTERISKS. ONLY DOCUMENTED DATA.""",

                        "📋 DOPR — Discharge on Patient's Request": f"""You are a medical scribe at {HOSPITAL_NAME}, {HOSPITAL_CITY}.
PATIENT: {pname} | DATE: {now_str} | DOCTOR: {st.session_state.current_user}
DOCUMENTED DATA: {all_summaries}
{ANTI_HAL}
{lama_legal}
Write formal DOPR DISCHARGE SUMMARY. Include full medicolegal disclaimer above verbatim.
Document: current diagnosis, treatment given so far, current status, reason for DOPR.
PLAIN TEXT. NO ASTERISKS.""",

                        "⚠️ LAMA — Left Against Medical Advice": f"""You are a medical scribe at {HOSPITAL_NAME}, {HOSPITAL_CITY}.
PATIENT: {pname} | DATE: {now_str} | DOCTOR: {st.session_state.current_user}
DOCUMENTED DATA: {all_summaries}
{ANTI_HAL}
{lama_legal}
Write formal LAMA DISCHARGE SUMMARY. Include full medicolegal disclaimer above verbatim.
This must be legally defensible. Document all counselling provided, all risks explained.
PLAIN TEXT. NO ASTERISKS.""",

                        "🚑 Referral to Higher Centre": f"""You are a medical scribe at {HOSPITAL_NAME}, {HOSPITAL_CITY}.
{ANTI_HAL}
PATIENT: {pname} | DATE: {now_str}
REFERRING DOCTOR: {st.session_state.current_user} | HOD: {HOD_NAME} ({HOD_DESIG})
DOCUMENTED ICU DATA: {all_summaries}
{ANTI_HAL}
Write formal REFERRAL LETTER in standard Indian medical format:
To: [Receiving Hospital/Specialist — write "Concerned Specialist/HOD" if not documented]
From: {st.session_state.current_user}, {HOSPITAL_NAME}, {HOSPITAL_CITY}
Date: {now_str}
Re: [Patient name, Age/Sex from documented data]
Dear Colleague,
[Formal referral letter — only documented clinical information]
Sections: Reason for Referral | Brief History | Investigations Done (with results) |
Treatment Given | Current Status | Special Instructions for Receiving Team
Yours sincerely, {st.session_state.current_user}
HOD: {HOD_NAME} | {HOSPITAL_NAME} | {HOSPITAL_CITY}
PLAIN TEXT. NO ASTERISKS. ONLY DOCUMENTED DATA.""",

                        "🗣️ Relative Counseling (Hinglish — Roman Script)": f"""You are a compassionate medical counsellor at {HOSPITAL_NAME}, {HOSPITAL_CITY}.
{ANTI_HAL}
PATIENT: {pname} | DATE: {now_str}
DOCUMENTED CLINICAL SUMMARY: {all_summaries}
{ANTI_HAL}
Write ICU RELATIVE COUNSELING SHEET based STRICTLY on documented data.
STRICT FORMAT RULES:
- Language: Simple HINGLISH (Hindi + English mixed)
- Script: ROMAN ALPHABETS ONLY — ABSOLUTELY NO DEVANAGARI (no हिंदी script)
- Tone: Compassionate, simple, honest — family should fully understand
- Level: Assume family has no medical education
- For any undocumented aspect → write "Is baare mein doctor se poochhen"
Sections:
1. Kya hua hai patient ko (simple words, documented diagnosis only)
2. ICU mein kyon rakhna pada
3. Abhi kya treatment ho raha hai (only documented)
4. Abhi patient ki condition kaisi hai (from documented data)
5. Aage kya hoga (realistic, based on documented trajectory)
6. Family ko kya karna chahiye
7. Kab turant hospital aana hai (red flags for documented condition)
8. Follow-up aur dawaiyan (only documented)
PLAIN TEXT. ROMAN SCRIPT ONLY. NO ASTERISKS.""",

                        "👤 Patient Instruction Card (Simple English)": f"""You are a medical educator at {HOSPITAL_NAME}, {HOSPITAL_CITY}.
{ANTI_HAL}
PATIENT: {pname} | DATE: {now_str} | DOCTOR: {st.session_state.current_user}
DOCUMENTED DATA: {all_summaries}
{ANTI_HAL}
Write PATIENT DISCHARGE INSTRUCTION CARD in very simple English that the patient can read themselves.
Keep it SHORT, CLEAR, FRIENDLY. Use simple words, not medical jargon.
Sections (ONLY from documented data):
- YOUR DIAGNOSIS: [in simple words]
- YOUR MEDICINES: [name, when to take, for how long — only documented]
- COME TO HOSPITAL IMMEDIATELY IF: [red flags relevant to documented condition]
- FOODS TO AVOID: [relevant to documented condition]
- ACTIVITIES: [what you can and cannot do]
- YOUR FOLLOW-UP: [date/doctor if documented]
- EMERGENCY CONTACT: [leave blank if not documented]
PLAIN TEXT. NO ASTERISKS. SIMPLE LANGUAGE.""",

                        "🌙 Shift / Handover Summary": f"""You are a duty doctor at {HOSPITAL_NAME}, {HOSPITAL_CITY}.
{ANTI_HAL}
PATIENT: {pname} | DATE: {now_str} | OUTGOING: {st.session_state.current_user}
DOCUMENTED DATA: {all_summaries}
{ANTI_HAL}
Write ISBAR SHIFT HANDOVER for this patient based on documented data only:
I — IDENTIFY: Patient name, age/sex, bed, admission date, diagnosis
S — SITUATION: Current status RIGHT NOW (from most recent documented data)
B — BACKGROUND: Brief relevant history (documented)
A — ASSESSMENT: Current criticality, active problems (documented)
R — RECOMMENDATION: What incoming doctor MUST do, watch for, escalate
PENDING ACTIONS: [any tasks not yet completed]
ESCALATION PLAN: [specific triggers to call senior]
Signed: {st.session_state.current_user} | {now_str}
PLAIN TEXT. NO ASTERISKS. ONLY DOCUMENTED DATA.""",
                    }

                    chosen = prompts.get(doc_type, "")
                    if chosen:
                        show_agents()
                        with st.spinner(f"Generating {doc_type}..."):
                            try:
                                result_text = smart_generate([chosen])
                                st.session_state[f"doc_result_{pname}"] = (doc_type, result_text)
                                log(f"Document: {doc_type} for {pname}")
                            except Exception as e: st.error(str(e))

            if f"doc_result_{pname}" in st.session_state:
                dtyp, dtxt = st.session_state[f"doc_result_{pname}"]
                st.success(f"✅ Ready: {dtyp}")
                st.text_area("Generated Document:", value=dtxt, height=400, key=f"docshow_{pname}")
                if FPDF_OK:
                    clean_type = re.sub(r'[^\w\s]','',dtyp).strip()
                    dl_pdf_btn(f"📥 Download PDF", clean_type.upper(),
                               pname, dtxt, f"docdl_{pname}", st.session_state.current_user)

        # ══════════════════════════════════════════
        # SECTION: TRANSFER BED
        # ══════════════════════════════════════════
        elif active_sec == "🔀 Transfer Bed":
            current_bed = pdata.get("bed","Unassigned")
            st.info(f"**{pname}** is currently in: **{current_bed}**")

            empty_beds = [b for b,v in st.session_state.icu_beds.items() if v=="Empty"]
            if not empty_beds:
                st.warning("No empty beds available for transfer.")
            else:
                new_bed = st.selectbox("Transfer to:", empty_beds, key=f"tb_{pname}")
                st.caption(f"This will free {current_bed} and assign {pname} to {new_bed}")
                if st.button("✅ Confirm Transfer", type="primary",
                             key=f"tbc_{pname}", use_container_width=True):
                    # Free old bed
                    if current_bed != "Unassigned":
                        st.session_state.icu_beds[current_bed] = "Empty"
                    # Assign new bed
                    st.session_state.icu_beds[new_bed] = pname
                    st.session_state.patients_db[pname]["bed"] = new_bed
                    log(f"Transfer: {pname} | {current_bed} → {new_bed}")
                    st.success(f"✅ {pname} transferred from {current_bed} → {new_bed}")
                    st.session_state.bed_panel_pt = pname
                    st.rerun()

        # ══════════════════════════════════════════
        # SECTION: DISCHARGE & ARCHIVE
        # ══════════════════════════════════════════
        elif active_sec == "🛑 Discharge":
            if pdata.get("status") != "Active":
                st.success(f"{pname} is already discharged.")
            else:
                st.warning(f"⚠️ This will discharge {pname} and free their bed.")
                st.caption("Use '📄 Documents' tab to generate discharge summary BEFORE archiving.")
                confirm = st.checkbox(f"I confirm discharge of {pname}", key=f"dcc_{pname}")
                if confirm:
                    if st.button("🛑 DISCHARGE & ARCHIVE", type="primary",
                                 key=f"dca_{pname}", use_container_width=True):
                        st.session_state.patients_db[pname]["status"] = "Discharged"
                        for bed,occ in st.session_state.icu_beds.items():
                            if occ==pname: st.session_state.icu_beds[bed]="Empty"
                        push_cloud({"action":"discharge","patient_name":pname,
                                    "status":"Discharged","date":str(datetime.datetime.now())})
                        log(f"Discharged: {pname}")
                        st.success(f"✅ {pname} discharged. Bed freed.")
                        st.session_state.bed_panel_pt = None
                        st.rerun()

# ═══════════════════════════════════════════════════════════
# LOGIN SCREEN
# ═══════════════════════════════════════════════════════════
if not st.session_state.logged_in:
    sync_cloud()
    c1,c2,c3 = st.columns([1,2,1])
    with c2:
        st.markdown(f"""
        <div style='background:linear-gradient(135deg,#0a1628,#1a3a6e);
                    padding:40px;border-radius:16px;text-align:center;color:white;margin-bottom:20px'>
          <h2 style='margin:0'>🏥 {HOSPITAL_NAME}</h2>
          <h3 style='margin:8px 0;color:#a0c4e8'>Cardiac ICU Command System v4.0</h3>
          <p style='color:#6898c0;margin:0'>{HOSPITAL_CITY} | AI Clinical Decision Support</p>
        </div>""", unsafe_allow_html=True)
        pin = st.text_input("PIN or Master Password:", type="password",
                            placeholder="4-digit PIN or Master Password")
        if st.button("🔐 Login", type="primary", use_container_width=True):
            if pin == MASTER_PASSWORD:
                st.session_state.logged_in    = True
                st.session_state.current_user = MASTER_NAME
                st.session_state.is_master    = True
                log("MASTER LOGIN"); st.rerun()
            elif pin in st.session_state.doctors_db:
                d = st.session_state.doctors_db[pin]
                st.session_state.logged_in    = True
                st.session_state.current_user = f"{d['name']} ({d['role']})"
                st.session_state.is_master    = False
                log("Doctor LOGIN"); st.rerun()
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
    st.markdown(f"### 🏥 {HOSPITAL_NAME} — ICU v4.0{badge}")
with h2:
    st.markdown(f"**HOD:** {HOD_NAME} *({HOD_DESIG})*")
    st.markdown(f"**User:** `{st.session_state.current_user}` | {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}")
with h3:
    if st.button("🚪 Logout"):
        st.session_state.logged_in = False
        st.session_state.current_user = None
        st.session_state.is_master = False
        st.rerun()
st.markdown("---")
if not engine_ok:
    st.warning("⚠️ AI Engine not active — Add GEMINI_API_KEY in Streamlit → Settings → Secrets")

# ═══════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════
if st.session_state.is_master:
    TABS = ["👑 Master","🏥 Bed Board","🩺 ICU Frontline","📊 HOD Dashboard",
            "📉 Flowsheet","🚨 Early Warning","💊 Medications","🔄 Handover","🔬 Academic","💬 Feedback"]
else:
    TABS = ["🏥 Bed Board","🩺 ICU Frontline","📊 HOD Dashboard",
            "📉 Flowsheet","🚨 Early Warning","💊 Medications","🔄 Handover","🔬 Academic","💬 Feedback"]

tabs = st.tabs(TABS)
def T(name): return tabs[TABS.index(name)]

# ═══════════════════════════════════════════════════════════
# TAB: MASTER CONTROL
# ═══════════════════════════════════════════════════════════
if st.session_state.is_master:
    with T("👑 Master"):
        st.markdown(f"""<div style='background:linear-gradient(135deg,#1a1a2e,#0f3460);
        padding:20px;border-radius:12px;color:white;margin-bottom:15px'>
        <h2 style='margin:0'>👑 Master Control — Dr. G.S. Gill</h2>
        <p style='color:#aaa;margin:4px 0'>God-mode — Only YOU see this tab</p></div>""",
        unsafe_allow_html=True)
        st.success("🔐 YOUR MASTER PASSWORD: **GILL@ICU#2025**")
        st.markdown("---")
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
                st.success(f"✅ Added! PIN = **{pin2}** — share privately"); st.rerun()
        st.markdown("#### ❌ Remove Doctor")
        pm = {f"{v['name']} (PIN:{k})":k for k,v in docs.items()}
        td = st.selectbox("Remove:", ["---"]+list(pm.keys()))
        if st.button("🗑️ Remove"):
            if td != "---":
                del st.session_state.doctors_db[pm[td]]
                log(f"Removed: {td}"); st.success("Removed."); st.rerun()
        st.markdown("---")
        st.subheader("📊 System Stats")
        tot = len(st.session_state.patients_db)
        act = sum(1 for d in st.session_state.patients_db.values() if d.get("status")=="Active")
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Total Patients",tot); m2.metric("Active",act)
        m3.metric("Discharged",tot-act); m4.metric("Doctors",len(docs))
        st.markdown("---")
        st.subheader("📋 Audit Trail")
        for e in st.session_state.audit_log[:60]: st.text(e)
        if st.button("🔄 Force Cloud Sync"):
            sync_cloud(); st.success("Synced!")

# ═══════════════════════════════════════════════════════════
# TAB: BED BOARD v2 — Click bed → Full Patient Panel
# ═══════════════════════════════════════════════════════════
with T("🏥 Bed Board"):
    beds = st.session_state.icu_beds
    occ  = sum(1 for v in beds.values() if v!="Empty")
    st.markdown(f"### 🏥 ICU Bed Board — {HOSPITAL_NAME}")
    st.caption(f"{HOSPITAL_CITY} | Occupied: {occ}/12 | Free: {12-occ}")

    # If a patient panel is open — show it
    if st.session_state.bed_panel_pt:
        pname = st.session_state.bed_panel_pt
        pdata = st.session_state.patients_db.get(pname)
        if pdata:
            col_back, _ = st.columns([1,5])
            with col_back:
                if st.button("← Back to Bed Board", key="back_to_board"):
                    st.session_state.bed_panel_pt = None
                    st.rerun()
            st.markdown("---")
            render_patient_panel(pname, pdata)
        else:
            st.session_state.bed_panel_pt = None
            st.rerun()
    else:
        # Show the 12-bed grid
        st.markdown("#### Click any occupied bed to open patient panel:")
        bcols = st.columns(4)
        for i,(bed,pt) in enumerate(beds.items()):
            with bcols[i%4]:
                if pt == "Empty":
                    st.markdown(f"""
                    <div style='background:#1e4d1e;padding:12px;border-radius:8px;
                    text-align:center;color:white;margin:4px'>
                    <b>{bed}</b><br><small>🟢 EMPTY</small></div>""",
                    unsafe_allow_html=True)
                    # Assign patient to empty bed
                    ap2 = [n for n,d in st.session_state.patients_db.items() if d.get("status")=="Active"]
                    if ap2:
                        with st.expander(f"+ Assign to {bed}", expanded=False):
                            bpt = st.selectbox("Patient:",["---"]+ap2, key=f"assign_{bed}")
                            if st.button("✅ Assign", key=f"assignbtn_{bed}"):
                                if bpt != "---":
                                    st.session_state.icu_beds[bed] = bpt
                                    st.session_state.patients_db[bpt]["bed"] = bed
                                    log(f"Bed {bed}→{bpt}"); st.rerun()
                else:
                    # OCCUPIED — clickable button
                    if st.button(
                        f"🔴 {bed}\n{pt}",
                        key=f"bedopen_{bed}",
                        use_container_width=True,
                        help=f"Click to open {pt}'s panel"
                    ):
                        st.session_state.bed_panel_pt = pt
                        st.session_state[f"sec_{re.sub(r'[^a-zA-Z0-9]','_',pt)}"] = "📋 Master File"
                        st.rerun()

# ═══════════════════════════════════════════════════════════
# TAB: ICU FRONTLINE
# ═══════════════════════════════════════════════════════════
with T("🩺 ICU Frontline"):
    st.header("🩺 ICU Frontline — New Admission & Analysis")

    fc1,fc2 = st.columns(2)
    with fc1: pt_type  = st.radio("Patient:",["New Admission","Existing Patient"],horizontal=True)
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

    with st.expander("📊 Enter Vitals", expanded=True):
        v1,v2,v3,v4,v5,v6 = st.columns(6)
        with v1: vbp  = st.text_input("BP","120/80")
        with v2: vhr  = st.number_input("HR",0,300,80)
        with v3: vrr  = st.number_input("RR",0,60,16)
        with v4: vspo = st.number_input("SpO2",0,100,98)
        with v5: vtmp = st.number_input("Temp",30.0,43.0,37.0,0.1)
        with v6: vgcs = st.number_input("GCS",3,15,15)
        vstr = f"BP:{vbp} mmHg | HR:{vhr} bpm | RR:{vrr}/min | SpO2:{vspo}% | Temp:{vtmp}C | GCS:{vgcs}/15"

    st.markdown("---")
    voice_box("🎤 Dictate Clinical Notes", key="fl_voice")
    st.caption("Speak → Copy → Paste below ↓")
    notes = st.text_area(
        "Clinical Notes — History, Examination, Labs, ABG, ECG findings:",
        height=180,
        placeholder="""Type the complete clinical picture:
- Chief complaint and duration
- Relevant history (comorbidities, medications if known)
- Examination findings
- ECG findings (if available)
- Lab / ABG values (if available)
- Any other relevant information

Leave blank fields empty — do NOT guess or fill defaults."""
    )
    full_notes = f"Diagnosis Category: {diag_cat}\nVitals: {vstr}\nClinical Notes: {notes if notes.strip() else 'Not provided'}"
    if pt_type=="New Admission":
        full_notes += f"\nAge: {age} years | Gender: {gender}"

    st.subheader("📸 Upload ECG / X-Ray / Lab Reports")
    st.caption("📱 Mobile: tap Browse → select Camera")
    uploads = st.file_uploader("Upload:", type=['jpg','jpeg','png','pdf'],
                                accept_multiple_files=True, key="fl_up")
    has_inp = bool(notes.strip() or uploads)
    st.markdown("---")

    b1,b2,b3 = st.columns(3)
    with b1: do_q = st.button("🚨 Quick Analysis",  type="primary",   use_container_width=True)
    with b2: do_e = st.button("👑 Expert Board",    type="secondary", use_container_width=True)
    with b3: do_s = st.button("🦠 Sepsis Protocol",                   use_container_width=True)

    if do_q or do_e or do_s:
        if not engine_ok: st.error("AI offline — add GEMINI_API_KEY in Secrets.")
        elif not p_name:  st.warning("Enter patient name.")
        elif not has_inp: st.warning("Add clinical notes or upload a report.")
        else:
            now_str = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
            fmt     = get_assessment_format(p_name, st.session_state.current_user, now_str)

            if do_q:
                atype  = "QUICK"
                prompt = f"""{AGENT_PERSONAS}
{ANTI_HAL}

You are an ICU Resident producing a formal clinical note.

PATIENT DATA PROVIDED BY DOCTOR:
{full_notes}

{ANTI_HAL}

{fmt}

ADDITIONAL FOR QUICK ANALYSIS:
After the standard format above, add:
IMMEDIATE ACTIONS (Next 30 minutes):
[numbered list of urgent actions based on provided data]

INVESTIGATIONS TO ORDER NOW:
[what is still missing and needed urgently]

NURSING INSTRUCTIONS:
[specific tasks, monitoring frequency, red flags to call doctor]

PLAIN TEXT ONLY. NO ASTERISKS. STRICTLY NO INVENTED DATA.
End with: TOPICS: Topic1, Topic2, Topic3"""

            elif do_e:
                atype  = "EXPERT"
                prompt = f"""{AGENT_PERSONAS}
{ANTI_HAL}

PATIENT DATA PROVIDED BY DOCTOR:
{full_notes}

{ANTI_HAL}

{fmt}

PLAIN TEXT ONLY. NO ASTERISKS. STRICTLY NO INVENTED DATA.
End with: TOPICS: Topic1, Topic2, Topic3"""

            else:
                atype  = "SEPSIS"
                prompt = f"""{AGENT_PERSONAS}
{ANTI_HAL}

PATIENT DATA PROVIDED:
{full_notes}

{ANTI_HAL}

Produce formal ICU SEPSIS ASSESSMENT NOTE:

════════════════════════════════════════════
SEPSIS SCREENING & MANAGEMENT — {HOSPITAL_NAME.upper()}
DATE: {now_str} | Patient: {p_name}
Doctor: {st.session_state.current_user}
════════════════════════════════════════════

qSOFA SCORE:
RR ≥22: [from provided data | Not provided]
GCS <15: [from provided data | Not provided]
SBP ≤100: [from provided data | Not provided]
qSOFA TOTAL: [calculated | "Insufficient data"]

SEPSIS-3 CRITERIA:
Suspected infection: [from provided notes | Not documented]
Organ dysfunction (SOFA): [from provided data | Insufficient data]
Sepsis-3 met: [YES/NO/Insufficient data]

SHOCK ASSESSMENT:
Type: Septic / Cardiogenic / Mixed / Insufficient data
Evidence: [from provided data only]

1-HOUR BUNDLE (mark each):
Blood cultures: [DONE/ORDER NOW/Not documented]
Serum lactate: [value if provided | ORDER NOW]
IV Fluids 30ml/kg: [DONE/ORDER/Not documented]
Empiric antibiotics: [drug|dose|route — based on documented source]
Vasopressors: [needed/not needed — based on provided MAP/BP data]

VASOPRESSOR PROTOCOL: [ONLY if shock documented]
SOURCE CONTROL: [ONLY from provided history]
MONITORING TARGETS: [Lactate, MAP, UO — based on documented data]
GAPS: [What data is still needed]

PLAIN TEXT ONLY. NO ASTERISKS. STRICTLY NO INVENTED DATA.
End with: TOPICS: Topic1, Topic2, Topic3"""

            show_agents()
            with st.spinner("Board producing clinical document..."):
                try:
                    cnt = [prompt]
                    if uploads:
                        for uf in uploads:
                            if uf.name.lower().endswith(('png','jpg','jpeg')) and PIL_OK:
                                cnt.append(opt_img(uf))
                            elif uf.name.lower().endswith('.pdf'):
                                with tempfile.NamedTemporaryFile(delete=False,suffix=".pdf") as tmp:
                                    tmp.write(uf.read())
                                gf = genai.upload_file(path=tmp.name,mime_type='application/pdf')
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
                    st.success(f"✅ Clinical document generated & saved for {p_name}!")
                except Exception as e:
                    st.error(f"AI Error: {e}")

    rkey = f"res_{p_name}" if p_name else None
    if rkey and rkey in st.session_state:
        st.markdown("---")
        st.subheader("📋 Clinical Assessment Document")
        st.info(st.session_state[rkey])
        c1,c2 = st.columns(2)
        with c1:
            if FPDF_OK and st.button("📄 Download as PDF", key="fl_dlpdf"):
                dl_pdf_btn("📥 Download PDF","CLINICAL ASSESSMENT",p_name,
                           st.session_state[rkey],"fl_dl2",st.session_state.current_user)
        with c2:
            if st.button("🏥 Open Patient Panel", key="fl_openpanel"):
                st.session_state.bed_panel_pt = p_name
                st.rerun()

        st.markdown("---")
        st.subheader("📚 AI-Suggested Learning Topics")
        at = st.session_state.get(f"topics_{p_name}",[])
        st_sel  = st.selectbox("Suggested:",["Choose..."]+at) if at else None
        ct_inp  = st.text_input("Or type topic:")
        ft      = ct_inp if ct_inp else (st_sel if st_sel and st_sel!="Choose..." else "")
        if ft and st.button("📖 Generate Guideline PDF"):
            with st.spinner("Generating..."):
                try:
                    gp = f"""Write a comprehensive ICU clinical guideline on: {ft}
Include: Definition, pathophysiology, diagnostic criteria with values,
step-by-step management, drug doses (Indian generic names with brand in brackets),
monitoring targets, complications, clinical pearls.
Reference: AHA/ACC 2024, ESC 2024, SCCM, Indian guidelines (CSI/ISCCM).
Professional medical language. PLAIN TEXT. NO ASTERISKS."""
                    gt   = smart_generate([gp])
                    path = make_pdf(f"GUIDELINE:{ft[:25].upper()}","Academic",gt,st.session_state.current_user)
                    if path:
                        with open(path,"rb") as f:
                            st.download_button("📥 Guideline PDF",data=f,
                                file_name=f"Guideline_{ft[:20].replace(' ','_')}.pdf",
                                mime="application/pdf", key="fl_gdl")
                except Exception as e: st.error(str(e))

# ═══════════════════════════════════════════════════════════
# TAB: HOD DASHBOARD
# ═══════════════════════════════════════════════════════════
with T("📊 HOD Dashboard"):
    st.header("📊 HOD Dashboard — Full Patient Management")
    dc1,dc2 = st.columns([3,1])
    with dc1: vf = st.radio("Show:",["Active","Discharged","All"],horizontal=True)
    with dc2:
        if st.button("🔄 Refresh"): sync_cloud(); st.rerun()

    db   = st.session_state.patients_db
    filt = {k:v for k,v in db.items() if
            (vf=="Active" and v.get("status")=="Active") or
            (vf=="Discharged" and v.get("status")=="Discharged") or vf=="All"}

    if not filt:
        st.info("No patients found.")
    else:
        for pname, pdata in filt.items():
            hist   = pdata.get("history",[])
            badge  = "🔴" if pdata.get("status")=="Active" else "✅"
            adm    = hist[0].get("date","?")[:10] if hist else "?"
            los = "?"
            try:
                d0 = datetime.datetime.strptime(adm,"%Y-%m-%d")
                los = f"{(datetime.datetime.now()-d0).days}d"
            except: pass
            with st.expander(
                f"{badge} {pname}  |  Admitted: {adm}  |  LOS: {los}  |  Bed: {pdata.get('bed','?')}  |  Updates: {len(hist)}",
                expanded=False):
                render_patient_panel(pname, pdata)

# ═══════════════════════════════════════════════════════════
# TAB: FLOWSHEET
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
            st.dataframe(df,use_container_width=True,hide_index=True)
            ch1,ch2 = st.columns(2)
            with ch1:
                try: st.line_chart(df.set_index("Time")[["HR","RR"]]); st.caption("HR & RR")
                except: pass
            with ch2:
                try: st.line_chart(df.set_index("Time")[["SpO2"]]); st.caption("SpO2")
                except: pass

# ═══════════════════════════════════════════════════════════
# TAB: EARLY WARNING
# ═══════════════════════════════════════════════════════════
with T("🚨 Early Warning"):
    st.header("🚨 Early Warning — NEWS2 & Sepsis Screening")
    ew1,ew2 = st.columns(2)
    with ew1:
        st.subheader("🩺 NEWS2 Calculator")
        e_rr=st.number_input("RR:",0,60,16,key="e_rr")
        e_sp=st.number_input("SpO2:",0,100,97,key="e_sp")
        e_o2=st.checkbox("Supplemental O2?")
        e_sb=st.number_input("Systolic BP:",50,250,120,key="e_sb")
        e_hr=st.number_input("HR:",0,300,80,key="e_hr")
        e_tm=st.number_input("Temp:",30.0,43.0,37.0,0.1,key="e_tm")
        e_av=st.selectbox("AVPU:",["Alert","Confusion/New","Voice","Pain","Unresponsive"])
        if st.button("📊 Calculate NEWS2",type="primary"):
            sc,risk,em2,act=calc_news2(e_rr,e_sp,e_o2,e_sb,e_hr,e_tm,e_av)
            bg="#6b1a1a" if "HIGH" in risk else ("#7a6b00" if "MEDIUM" in risk else "#1e4d1e")
            st.markdown(f"""<div style='background:{bg};padding:18px;border-radius:10px;
            color:white;text-align:center'><h2>{em2} NEWS2: {sc}</h2>
            <h3>Risk: {risk}</h3><p>{act}</p></div>""",unsafe_allow_html=True)
            log(f"NEWS2:{sc} ({risk})")
    with ew2:
        st.subheader("🦠 qSOFA Sepsis Screen")
        q_rr=st.number_input("RR:",0,60,16,key="q_rr")
        q_gc=st.number_input("GCS:",3,15,15,key="q_gc")
        q_sb=st.number_input("Systolic BP:",50,250,110,key="q_sb")
        if st.button("🦠 Calculate qSOFA",type="primary"):
            qs=sum([q_rr>=22,q_gc<15,q_sb<=100])
            bg="#6b1a1a" if qs>=2 else "#1e4d1e"
            st.markdown(f"""<div style='background:{bg};padding:18px;border-radius:10px;
            color:white;text-align:center'><h2>qSOFA: {qs}/3</h2>
            <p>{"HIGH SEPSIS RISK — Activate Protocol!" if qs>=2 else "Low-Moderate — Monitor closely"}</p>
            </div>""",unsafe_allow_html=True)
    st.markdown("---")
    st.subheader("🧠 AI Deterioration Analysis")
    det=st.text_area("Paste vitals/findings for AI risk assessment:",height=90)
    if st.button("🧠 Analyze Risk") and det and engine_ok:
        with st.spinner("Analyzing..."):
            try:
                dp3=f"""{ANTI_HAL}
Critical Care AI Deterioration Radar. Data provided: {det}
{ANTI_HAL}
Based ONLY on provided data:
1. RISK LEVEL (LOW/MEDIUM/HIGH/CRITICAL) — justify with provided numbers
2. SPECIFIC WARNING SIGNS (from provided data)
3. PREDICTED COMPLICATIONS (next 4-12 hrs)
4. IMMEDIATE INTERVENTIONS
5. MONITORING ESCALATION
PLAIN TEXT. NO ASTERISKS. NO INVENTED DATA."""
                st.info(smart_generate([dp3]))
            except Exception as e: st.error(str(e))

# ═══════════════════════════════════════════════════════════
# TAB: MEDICATIONS
# ═══════════════════════════════════════════════════════════
with T("💊 Medications"):
    st.header("💊 Medication Safety & Dose Calculator")
    mm1,mm2=st.columns(2)
    with mm1:
        st.subheader("⚠️ DDI Checker")
        meds=st.text_area("Medications (one per line):",height=160,
            placeholder="Tab Aspirin 75mg OD\nTab Clopidogrel 75mg OD\nInj Enoxaparin 40mg BD\nTab Amiodarone 200mg TDS")
        renal=st.selectbox("Renal:",["Normal","Mild (CrCl 60-90)","Moderate (CrCl 30-60)","Severe (<30)","Dialysis"])
        hepatic=st.selectbox("Hepatic:",["Normal","Child-Pugh A","Child-Pugh B","Child-Pugh C"])
        if st.button("🔬 Full Safety Scan",type="primary"):
            if not meds.strip(): st.warning("Enter medications.")
            elif not engine_ok: st.error("AI offline.")
            else:
                with st.spinner("Clinical Pharmacologist scanning..."):
                    try:
                        mp=f"""You are a Senior Clinical Pharmacologist, {HOSPITAL_NAME}, {HOSPITAL_CITY}.
{ANTI_HAL}
MEDICATION LIST PROVIDED: {meds}
RENAL FUNCTION: {renal} | HEPATIC FUNCTION: {hepatic}
{ANTI_HAL}
Analyze ONLY the medications listed above:
1. DDI TABLE:
Drug 1 | Drug 2 | Severity | Mechanism | Risk | Action Required
[List ALL clinically significant interactions — CONTRAINDICATED/MAJOR/MODERATE/MINOR]
2. RENAL DOSE ADJUSTMENTS (for listed drugs only, based on {renal}):
Drug | Standard Dose | Adjusted Dose | Monitoring
3. HEPATIC ADJUSTMENTS (for listed drugs, based on {hepatic})
4. MONITORING PARAMETERS for high-risk drugs
5. ANTICOAGULATION SAFETY (only if anticoagulants listed)
6. SAFER ALTERNATIVES for any CONTRAINDICATED combos
PLAIN TEXT. NO ASTERISKS. ONLY ANALYZE LISTED DRUGS."""
                        mres=smart_generate([mp])
                        log("Med safety scan"); st.success("Complete!"); st.info(mres)
                    except Exception as e: st.error(str(e))
    with mm2:
        st.subheader("💉 ICU Infusion Calculator")
        drug=st.selectbox("Drug:",["Norepinephrine","Dopamine","Dobutamine","Adrenaline",
                                   "GTN","Furosemide","Insulin","Midazolam","Morphine","Amiodarone"])
        wt=st.number_input("Weight (kg):",30.0,200.0,65.0,0.5)
        dose=st.number_input("Dose (mcg/kg/min):",0.0,100.0,0.1,0.01)
        conc=st.number_input("Concentration (mcg/ml):",0.1,10000.0,100.0,0.1)
        if st.button("🧮 Calculate Rate"):
            rate=(dose*wt*60)/conc if conc>0 else 0
            st.success(f"**{rate:.2f} ml/hr**")
            st.caption(f"{drug} | {dose} mcg/kg/min | {wt}kg | {conc}mcg/ml")
            log(f"Dose: {drug}={rate:.2f}")

# ═══════════════════════════════════════════════════════════
# TAB: HANDOVER
# ═══════════════════════════════════════════════════════════
with T("🔄 Handover"):
    st.header("🔄 Shift Handover — ISBAR Format")
    ho1,ho2=st.columns(2)
    with ho1: out_dr=st.text_input("Outgoing Dr:",value=st.session_state.current_user.split("(")[0].strip())
    with ho2: in_dr=st.text_input("Incoming Dr:",placeholder="Name of next duty doctor")
    extra=st.text_area("Pending tasks / concerns:",height=70)
    if st.button("🔄 Generate ISBAR Handover — ALL Active Patients",type="primary"):
        ap4={k:v for k,v in st.session_state.patients_db.items() if v.get("status")=="Active"}
        if not ap4: st.warning("No active patients.")
        elif not engine_ok: st.error("AI offline.")
        else:
            with st.spinner("Generating handover..."):
                try:
                    parts=[]
                    for pn,pd4 in ap4.items():
                        h4=pd4.get("history",[])
                        ls4=h4[-1].get("summary","No data") if h4 else "No data"
                        hr4=smart_generate([f"""{ANTI_HAL}
ISBAR handover for {pn}. Documented data: {ls4[:600]}
{ANTI_HAL}
Write ISBAR in 5-7 bullet points based ONLY on documented data:
- I: Identity (name, age/sex, bed, diagnosis from data)
- S: Situation (current status from most recent data)
- B: Background (brief relevant history from data)
- A: Assessment (criticality, active problems from data)
- R: Recommendations (what incoming doctor must do/watch)
PLAIN TEXT. NO ASTERISKS. NO INVENTED DATA."""])
                        parts.append(f"--- {pn} (Bed:{pd4.get('bed','?')}) ---\n{hr4}")
                    full=f"""SHIFT HANDOVER — {HOSPITAL_NAME.upper()}
{HOSPITAL_CITY} | {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}
Outgoing: {out_dr} | Incoming: {in_dr} | Active Patients: {len(ap4)}
{"="*50}
{chr(10).join(parts)}
{"="*50}
PENDING TASKS: {extra}
Handover complete. Both doctors to sign."""
                    st.session_state.handover_notes.insert(0,{"date":str(datetime.datetime.now()),
                        "outgoing":out_dr,"incoming":in_dr,"content":full})
                    log(f"Handover:{out_dr}->{in_dr}")
                    st.success("Done!"); st.info(full)
                    if FPDF_OK:
                        hp4=make_pdf("SHIFT HANDOVER","All Active Patients",full,out_dr)
                        if hp4:
                            with open(hp4,"rb") as f:
                                st.download_button("📥 Handover PDF",data=f,
                                    file_name=f"Handover_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                                    mime="application/pdf")
                except Exception as e: st.error(str(e))

# ═══════════════════════════════════════════════════════════
# TAB: ACADEMIC
# ═══════════════════════════════════════════════════════════
with T("🔬 Academic"):
    st.header("🔬 Academic Vault — CME & Clinical Guidelines")
    topic=st.text_input("Topic:",placeholder="e.g. Cardiogenic Shock, STEMI 2024, Vasopressors in ICU")
    ac1,ac2,ac3=st.columns(3)
    with ac1: ct=st.selectbox("Type:",["Clinical Guideline","Drug Protocol","Case Discussion","CME Quiz","Procedure Guide"])
    with ac2: lv=st.selectbox("Level:",["Resident","Senior Resident","Consultant","Fellowship"])
    with ac3: ref=st.selectbox("Reference:",["AHA/ACC 2024","ESC 2024","SCCM/ESICM","Indian (CSI/ISCCM)","Multiple"])
    if st.button("📚 Generate",type="primary"):
        if not topic.strip(): st.warning("Enter topic.")
        elif not engine_ok: st.error("AI offline.")
        else:
            with st.spinner("Generating..."):
                try:
                    ap5=f"""Senior medical educator + Intensivist, {HOSPITAL_NAME}, {HOSPITAL_CITY}.
Topic: {topic} | Type: {ct} | Level: {lv} | Reference: {ref}
Write comprehensive {ct}:
- Definition and pathophysiology
- Diagnostic criteria with specific values/thresholds
- Step-by-step management protocol (numbered)
- Drug doses: [Generic name (Brand)] | Dose | Route | Frequency
- Monitoring parameters and targets
- Complications and management
- Clinical pearls (3-5 key points)
- Common mistakes to avoid
{"Include 5 MCQs with answers and explanations." if ct=="CME Quiz" else ""}
Professional medical language. PLAIN TEXT. NO ASTERISKS."""
                    ar=smart_generate([ap5])
                    log(f"Academic: {topic}")
                    st.success("Generated!"); st.info(ar)
                    if FPDF_OK:
                        apath=make_pdf(f"{ct}: {topic[:25].upper()}","Academic",ar,st.session_state.current_user)
                        if apath:
                            with open(apath,"rb") as f:
                                st.download_button("📥 Download PDF",data=f,
                                    file_name=f"Academic_{topic.replace(' ','_')[:20]}.pdf",
                                    mime="application/pdf")
                except Exception as e: st.error(str(e))
    st.markdown("---")
    st.subheader("⚡ Quick Reference Cards")
    qlist=["STEMI Protocol","Cardiogenic Shock","Acute Pulmonary Edema","VT/VF Management",
           "Hypertensive Emergency","Septic Shock Bundle","AKI Management",
           "NIV/BiPAP Setup","Anticoagulation in AF+ACS","Post-PCI Care"]
    qs=st.selectbox("Select:",qlist)
    if st.button("⚡ Quick Generate"):
        with st.spinner("Generating..."):
            try:
                qr=smart_generate([f"""1-PAGE BEDSIDE QUICK REFERENCE CARD: {qs}
Ghaziabad ICU. Most critical information only:
- 3-5 diagnostic criteria with values
- 5-8 step management (numbered)
- Key drug doses [generic (brand)] | dose | route
- 3 monitoring targets with specific values
- 2 mistakes to avoid
Professional language. PLAIN TEXT. NO ASTERISKS."""])
                st.success("Ready!"); st.info(qr); log(f"Quick ref: {qs}")
            except Exception as e: st.error(str(e))

# ═══════════════════════════════════════════════════════════
# TAB: FEEDBACK
# ═══════════════════════════════════════════════════════════
with T("💬 Feedback"):
    st.header("💬 Feedback & Improvement Portal")
    st.caption("Doctors, residents, nurses, staff — anyone can suggest improvements or report issues.")
    fb1,fb2=st.columns([3,2])
    with fb1:
        st.markdown("#### 📝 Submit Feedback")
        with st.container(border=True):
            ftype=st.selectbox("Type:","🐛 Bug/Error,💡 Feature Request,⚠️ Clinical Concern,🔧 Improvement,👍 Positive,❓ Question,Other".split(","))
            fpri=st.radio("Priority:",["🟢 Low","🟡 Medium","🔴 Urgent"],horizontal=True)
            voice_box("🎤 Speak Feedback",key="fb_voice")
            st.caption("Speak → Copy → Paste below")
            ftxt=st.text_area("Your feedback:",height=120,
                placeholder="Describe the issue, suggestion, or improvement...")
            fname=st.text_input("Your name:",value=st.session_state.current_user.split("(")[0].strip())
            if st.button("📤 Submit",type="primary",use_container_width=True):
                if not ftxt.strip(): st.warning("Write feedback first.")
                else:
                    st.session_state.feedback_list.insert(0,{
                        "time":datetime.datetime.now().strftime("%d %b %Y, %I:%M %p"),
                        "type":ftype,"priority":fpri,"text":ftxt.strip(),
                        "by":fname.strip() or "Anonymous","status":"New"})
                    log(f"Feedback: {ftype}")
                    st.success("✅ Submitted! Dr. Gill will review."); st.balloons()
    with fb2:
        st.markdown("#### 📬 All Feedback")
        fl=st.session_state.feedback_list
        if not fl: st.info("No feedback yet.")
        else:
            for i,fb in enumerate(fl):
                pc={"🟢 Low":"#1e4d1e","🟡 Medium":"#6b5e00","🔴 Urgent":"#6b1a1a"}.get(fb["priority"],"#333")
                with st.container(border=True):
                    st.markdown(f"""<div style='border-left:4px solid {pc};padding-left:8px'>
                    <b>{fb['type']}</b> | {fb['priority']} | <small>{fb['time']}</small><br>
                    <small>By: {fb['by']}</small></div>""",unsafe_allow_html=True)
                    st.write(fb["text"][:180]+("..." if len(fb["text"])>180 else ""))
                    if st.session_state.is_master:
                        r1,r2=st.columns(2)
                        with r1:
                            if fb.get("status")=="New":
                                if st.button("✅ Resolved",key=f"fbr_{i}"):
                                    st.session_state.feedback_list[i]["status"]="Resolved"; st.rerun()
                        with r2:
                            if st.button("🗑️ Delete",key=f"fbd_{i}"):
                                st.session_state.feedback_list.pop(i); st.rerun()
                    else:
                        st.caption(f"Status: {'🟢 Resolved' if fb.get('status')=='Resolved' else '🟡 New'}")
            if st.session_state.is_master:
                tot_fb=len(fl); urg_fb=sum(1 for f in fl if f["priority"]=="🔴 Urgent")
                new_fb=sum(1 for f in fl if f.get("status")=="New")
                res_fb=sum(1 for f in fl if f.get("status")=="Resolved")
                st.markdown("---")
                fm1,fm2,fm3,fm4=st.columns(4)
                fm1.metric("Total",tot_fb); fm2.metric("New",new_fb)
                fm3.metric("Urgent",urg_fb); fm4.metric("Resolved",res_fb)

# ═══════════════════════════════════════════════════════════
# FOOTER
# ═══════════════════════════════════════════════════════════
st.markdown("---")
st.markdown(f"""<div style='text-align:center;color:gray;font-size:12px'>
{HOSPITAL_NAME} | Cardiac ICU Command System v4.0 | {HOSPITAL_CITY} |
AI-Powered by Google Gemini | For clinical decision support — always verify with qualified clinicians
</div>""", unsafe_allow_html=True)
