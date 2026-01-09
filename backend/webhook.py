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
# CONFIG
# --------------------------------------------------
STATE_TIMEOUT_MINUTES = 5

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
# DOCTORS
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
        "document": {"id": media_id, "filename": os.path.basename(file_path)}
    })

# --------------------------------------------------
# STATE MANAGEMENT
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

def is_state_expired(state):
    ts = state.get("updated")
    if not ts:
        return True
    return datetime.utcnow() - ts.replace(tzinfo=None) > timedelta(minutes=STATE_TIMEOUT_MINUTES)

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
# SLOTS
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
# PDF
# --------------------------------------------------
def create_pdf(patient):
    path = f"/tmp/{patient['PatientID']}_report.pdf"
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(path, pagesize=A4)
    story = []

    story.append(Paragraph("<b>NovaMed Multispeciality Care</b>", styles["Title"]))
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
    await send_buttons(
        user,
        "🏥 *NovaMed Multispeciality Care*\n“There is no true illness”\n\nChoose:",
        ["Book Appointment", "Get Report"]
    )
    set_state(user, "menu", {})

# --------------------------------------------------
# MAIN FLOW
# --------------------------------------------------
async def process(user, text):
    text = text.strip()
    greetings = ["hi", "hello", "hii", "hlo", "hyy", "hey", "menu", "restart"]

    if text.lower() in greetings:
        reset_state(user)
        await show_menu(user)
        return

    state = get_state(user)

    if state and is_state_expired(state):
        reset_state(user)
        await send_text(user, "⌛ Session expired.")
        await show_menu(user)
        return

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

    if step == "report":
        pid = text.upper().strip()
        doc = db.collection("patients").document(pid).get()
        if not doc.exists:
            await send_text(user, "❌ Patient ID not found")
            return
        pdf = create_pdf(doc.to_dict())
        await send_document(user, pdf)
        reset_state(user)
        return

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
