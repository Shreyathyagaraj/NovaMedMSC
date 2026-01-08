import os, json, logging, random
from datetime import datetime, timedelta
from typing import Dict

import httpx, dateparser
from fastapi import APIRouter, Request, HTTPException

import firebase_admin
from firebase_admin import credentials, firestore

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch

from apscheduler.schedulers.background import BackgroundScheduler

# --------------------------------------------------
# LOGGING
# --------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

# --------------------------------------------------
# FIREBASE INIT
# --------------------------------------------------
if not firebase_admin._apps:
    cred = credentials.Certificate(json.loads(os.getenv("FIREBASE_CREDENTIALS")))
    firebase_admin.initialize_app(cred)

db = firestore.client()

# --------------------------------------------------
# ROUTER
# --------------------------------------------------
router = APIRouter()

# --------------------------------------------------
# WHATSAPP CONFIG
# --------------------------------------------------
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WA_API = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"

# --------------------------------------------------
# SCHEDULER
# --------------------------------------------------
scheduler = BackgroundScheduler()
scheduler.start()

# --------------------------------------------------
# DEPARTMENTS (REDUCED & SAFE)
# --------------------------------------------------
DOCTORS = {
    "Cardiology": ("10:00", "16:00", 5),
    "Neurology": ("12:00", "16:00", 4),
    "Orthopedics": ("10:00", "16:00", 6),
    "Pediatrics": ("10:00", "16:00", 8),
    "General Medicine": ("09:00", "13:00", 10),
    "Dermatology": ("09:00", "18:00", 12),
}

# --------------------------------------------------
# WHATSAPP HELPERS
# --------------------------------------------------
async def wa_send(payload):
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(
            WA_API,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            json=payload
        )

async def send_text(to, text):
    await wa_send({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    })

async def send_buttons(to, body, buttons):
    await wa_send({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b, "title": b}}
                    for b in buttons[:3]
                ]
            }
        }
    })

async def send_list(to, body, rows):
    await wa_send({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": "Select",
                "sections": [{
                    "title": "Departments",
                    "rows": [{"id": r, "title": r} for r in rows]
                }]
            }
        }
    })

async def send_document(to, file_path):
    async with httpx.AsyncClient(timeout=30) as client:
        with open(file_path, "rb") as f:
            res = await client.post(
                f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/media",
                headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
                files={"file": f},
                data={"messaging_product": "whatsapp", "type": "document"}
            )

    media_id = res.json()["id"]

    await wa_send({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": os.path.basename(file_path)
        }
    })

# --------------------------------------------------
# STATE HANDLING
# --------------------------------------------------
def get_state(user):
    doc = db.collection("states").document(user).get()
    return doc.to_dict() if doc.exists else {}

def set_state(user, step, data):
    db.collection("states").document(user).set({
        "step": step,
        "data": data,
        "updated": firestore.SERVER_TIMESTAMP
    })

def reset_state(user):
    db.collection("states").document(user).delete()

# --------------------------------------------------
# PATIENT ID
# --------------------------------------------------
def generate_patient_id():
    ref = db.collection("metadata").document("patient_counter")
    tx = db.transaction()

    @firestore.transactional
    def run(tx):
        snap = ref.get(transaction=tx)
        last = snap.to_dict().get("count", 1000) if snap.exists else 1000
        new = last + 1
        tx.set(ref, {"count": new})
        return f"P{new}"

    return run(tx)

# --------------------------------------------------
# TIME SLOTS
# --------------------------------------------------
def generate_slots(start, end):
    s = datetime.strptime(start, "%H:%M")
    e = datetime.strptime(end, "%H:%M")
    slots = []
    while s < e:
        n = s + timedelta(hours=1)
        slots.append(f"{s.strftime('%H:%M')}-{n.strftime('%H:%M')}")
        s = n
    return slots

def slot_count(dept, date, slot):
    q = db.collection("patients") \
        .where("Department", "==", dept) \
        .where("Date", "==", date) \
        .where("Time", "==", slot) \
        .stream()
    return sum(1 for _ in q)

# --------------------------------------------------
# PDF REPORT
# --------------------------------------------------
def create_pdf(patient):
    path = f"/tmp/{patient['PatientID']}_report.pdf"
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(path, pagesize=A4)

    story = []
    story.append(Paragraph("<b>NovaMed Multispeciality Hospital</b>", styles["Title"]))
    story.append(Spacer(1, 0.3 * inch))

    story.append(Paragraph("<b>Patient Medical Report</b>", styles["Heading2"]))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph(
        f"""
        Patient ID: {patient['PatientID']}<br/>
        Name: {patient['Name']}<br/>
        Phone: {patient['Phone']}<br/>
        Department: {patient['Department']}<br/>
        Date: {patient['Date']}<br/>
        Time: {patient['Time']}<br/>
        """, styles["Normal"]
    ))

    story.append(Spacer(1, 0.3 * inch))

    story.append(Paragraph(
        f"""
        <b>Test Results</b><br/>
        BP: {random.randint(110,130)}/{random.randint(70,90)} mmHg<br/>
        Sugar: {random.randint(90,140)} mg/dL<br/>
        Heart Rate: {random.randint(65,95)} bpm
        """, styles["Normal"]
    ))

    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph(
        "<i>This is a system generated medical report.</i>",
        styles["Italic"]
    ))

    doc.build(story)
    return path

# --------------------------------------------------
# REMINDER
# --------------------------------------------------
def schedule_reminder(user, patient):
    t = datetime.strptime(
        f"{patient['Date']} {patient['Time'].split('-')[0]}",
        "%Y-%m-%d %H:%M"
    ) - timedelta(minutes=10)

    def job():
        import asyncio
        asyncio.run(send_text(user, "⏰ Reminder: Appointment in 10 minutes"))

    scheduler.add_job(job, "date", run_date=t)

# --------------------------------------------------
# MENU
# --------------------------------------------------
async def show_menu(user):
    await send_buttons(user, "🏥 *NovaMed*\nChoose:", ["Book Appointment", "Get Report"])
    set_state(user, "menu", {})

# --------------------------------------------------
# MAIN FLOW
# --------------------------------------------------
async def process(user, text):
    text = text.strip()

    if text.lower() in ["hi", "hello", "hii", "menu", "restart"]:
        reset_state(user)
        await show_menu(user)
        return

    state = get_state(user)
    step = state.get("step")
    data = state.get("data", {})

    if step == "menu":
        if text == "Book Appointment":
            set_state(user, "name", {})
            await send_text(user, "👤 Enter patient name:")
        elif text == "Get Report":
            set_state(user, "report", {})
            await send_text(user, "🆔 Enter Patient ID:")
        return

    if step == "name":
        data["Name"] = text
        set_state(user, "phone", data)
        await send_text(user, "📞 Enter 10-digit phone number:")
        return

    if step == "phone":
        if not text.isdigit() or len(text) != 10:
            await send_text(user, "❌ Phone number must be exactly 10 digits")
            return
        data["Phone"] = text
        set_state(user, "department", data)
        await send_list(user, "🏥 Select Department:", list(DOCTORS.keys()))
        return

    if step == "department":
        if text not in DOCTORS:
            await send_text(user, "❌ Invalid department")
            return
        data["Department"] = text
        set_state(user, "date", data)
        await send_text(user, "📅 Enter date (YYYY-MM-DD):")
        return

    if step == "date":
        parsed = dateparser.parse(text)
        if not parsed or parsed.date() < datetime.now().date():
            await send_text(user, "❌ Date cannot be in the past")
            return
        data["Date"] = parsed.strftime("%Y-%m-%d")

        start, end, cap = DOCTORS[data["Department"]]
        slots = generate_slots(start, end)

        available = []
        for s in slots:
            left = cap - slot_count(data["Department"], data["Date"], s)
            if left > 0:
                available.append(f"{s} ({left} left)")

        if not available:
            await send_text(user, "❌ No slots available")
            reset_state(user)
            return

        set_state(user, "time", data)
        await send_buttons(user, "⏰ Select Time Slot:", available)
        return

    if step == "time":
        slot = text.split(" ")[0]
        data["Time"] = slot
        pid = generate_patient_id()

        record = {
            "PatientID": pid,
            **data,
            "WhatsApp": user,
            "createdAt": firestore.SERVER_TIMESTAMP
        }

        db.collection("patients").document(pid).set(record)
        set_state(user, "reminder", record)
        await send_buttons(user, "⏰ Need 10-min reminder?", ["Yes", "No"])
        return

    if step == "reminder":
        if text == "Yes":
            schedule_reminder(user, data)
        await send_text(user, f"✅ Appointment Confirmed\n🆔 {data['PatientID']}")
        reset_state(user)
        return

    if step == "report":
        doc = db.collection("patients").document(text).get()
        if not doc.exists:
            await send_text(user, "❌ Patient ID not found")
            return
        pdf = create_pdf(doc.to_dict())
        await send_document(user, pdf)
        reset_state(user)

# --------------------------------------------------
# WEBHOOK ENDPOINTS
# --------------------------------------------------
@router.get("/webhook")
async def verify(req: Request):
    if req.query_params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(req.query_params.get("hub.challenge"))
    raise HTTPException(403)

@router.post("/webhook")
async def receive(req: Request):
    body = await req.json()
    value = body["entry"][0]["changes"][0]["value"]

    if "messages" not in value:
        return {"ok": True}

    msg = value["messages"][0]
    user = msg["from"]

    if msg.get("interactive"):
        inter = msg["interactive"]
        text = (
            inter.get("button_reply", {}) or
            inter.get("list_reply", {})
        ).get("title", "")
    else:
        text = msg.get("text", {}).get("body", "")

    await process(user, text)
    return {"ok": True}
