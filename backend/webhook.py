import os, json, logging
from datetime import datetime, timedelta
from typing import Dict

import httpx
import dateparser
from fastapi import APIRouter, Request, HTTPException
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from apscheduler.schedulers.background import BackgroundScheduler

import firebase_admin
from firebase_admin import credentials, firestore

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
# CONFIG
# --------------------------------------------------
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

WA_API = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"

# --------------------------------------------------
# SCHEDULER (REMINDER)
# --------------------------------------------------
scheduler = BackgroundScheduler()
scheduler.start()

# --------------------------------------------------
# DEPARTMENTS + DOCTOR HOURS + SLOT CAPACITY
# --------------------------------------------------
DOCTORS = {
    "Cardiology": ("10:00", "16:00", 5),
    "Neurology": ("12:00", "16:00", 4),
    "Orthopedics": ("10:00", "16:00", 6),
    "Pediatrics": ("12:00", "16:00", 8),
    "General Medicine": ("10:00", "16:00", 10),
    "Dermatology": ("12:00", "16:00", 6),
    "ENT": ("10:00", "16:00", 5),
    "Physician": ("10:00", "16:00", 8),
    "Anaesthesiology": ("12:00", "16:00", 4),
    "Ophthalmology": ("10:00", "16:00", 6),
    "Gynecology": ("10:00", "16:00", 6),
    "Dentist": ("10:00", "16:00", 6),
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
                    for b in buttons
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

# --------------------------------------------------
# STATE MANAGEMENT
# --------------------------------------------------
def get_state(user):
    doc = db.collection("states").document(user).get()
    return doc.to_dict() if doc.exists else {"step": None, "data": {}}

def set_state(user, step, data):
    db.collection("states").document(user).set({
        "step": step,
        "data": data,
        "updatedAt": firestore.SERVER_TIMESTAMP
    })

def reset_state(user):
    db.collection("states").document(user).delete()

# --------------------------------------------------
# PATIENT ID
# --------------------------------------------------
def generate_patient_id():
    ref = db.collection("metadata").document("patient_counter")
    transaction = db.transaction()

    @firestore.transactional
    def txn(tx):
        snap = ref.get(transaction=tx)
        last = snap.to_dict().get("count", 1000) if snap.exists else 1000
        new = last + 1
        tx.set(ref, {"count": new})
        return f"P{new}"

    return txn(transaction)

# --------------------------------------------------
# TIME SLOTS
# --------------------------------------------------
def generate_slots(start, end):
    slots = []
    h1 = int(start.split(":")[0])
    h2 = int(end.split(":")[0])
    for h in range(h1, h2):
        slots.append(f"{h}:00-{h+1}:00")
    return slots

# --------------------------------------------------
# PDF REPORT
# --------------------------------------------------
def generate_pdf(patient):
    path = f"/tmp/{patient['PatientID']}.pdf"
    c = canvas.Canvas(path, pagesize=A4)
    c.setFont("Helvetica", 12)
    y = 750
    for k, v in patient.items():
        c.drawString(40, y, f"{k}: {v}")
        y -= 20
    c.save()
    return path

# --------------------------------------------------
# REMINDER
# --------------------------------------------------
def schedule_reminder(phone, date, time):
    appt = datetime.strptime(f"{date} {time.split('-')[0]}", "%Y-%m-%d %H:%M")
    remind_at = appt - timedelta(minutes=10)

    def job():
        import asyncio
        asyncio.run(send_text(phone, "⏰ Reminder: Your appointment is in 10 minutes"))

    scheduler.add_job(job, "date", run_date=remind_at)

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
    state = get_state(user)
    step = state["step"]
    data = state["data"]

    if text.lower() in ["hi", "hello", "menu", "restart"]:
        reset_state(user)
        await show_menu(user)
        return

    if step == "menu":
        if text == "Book Appointment":
            set_state(user, "name", {})
            await send_text(user, "👤 Enter patient name:")
        elif text == "Get Report":
            set_state(user, "report", {})
            await send_text(user, "🆔 Enter Patient ID:")
        return

    if step == "name":
        data["name"] = text
        set_state(user, "phone", data)
        await send_text(user, "📞 Enter 10-digit phone number:")
        return

    if step == "phone":
        if not text.isdigit() or len(text) != 10:
            await send_text(user, "❌ Phone number must be exactly 10 digits")
            return
        data["phone"] = text
        set_state(user, "department", data)
        await send_list(user, "🏥 Select Department:", list(DOCTORS.keys()))
        return

    if step == "department":
        data["department"] = text
        set_state(user, "date", data)
        await send_text(user, "📅 Enter appointment date (YYYY-MM-DD):")
        return

    if step == "date":
        d = dateparser.parse(text)
        if not d or d.date() < datetime.now().date():
            await send_text(user, "❌ Past dates not allowed")
            return
        data["date"] = d.strftime("%Y-%m-%d")

        start, end, _ = DOCTORS[data["department"]]
        slots = generate_slots(start, end)

        set_state(user, "time", data)
        await send_buttons(user, "⏰ Select Time Slot:", slots[:3])
        return

    if step == "time":
        data["time"] = text
        pid = generate_patient_id()

        db.collection("patients").document(pid).set({
            "PatientID": pid,
            "Name": data["name"],
            "Phone": data["phone"],
            "Department": data["department"],
            "RegistrationDate": data["date"],
            "TimeBlock": data["time"]
        })

        set_state(user, "reminder", {"pid": pid, **data})
        await send_buttons(user, "⏰ Need 10-minute reminder?", ["Yes", "No"])
        return

    if step == "reminder":
        if text == "Yes":
            schedule_reminder(user, data["date"], data["time"])
        await send_text(user, f"✅ Appointment Confirmed\n🆔 {data['pid']}")
        reset_state(user)
        return

    if step == "report":
        doc = db.collection("patients").document(text).get()
        if not doc.exists:
            await send_text(user, "❌ Patient ID not found")
        else:
            pdf = generate_pdf(doc.to_dict())
            await send_text(user, "📄 Dummy PDF report generated")
        reset_state(user)

# --------------------------------------------------
# WEBHOOK ENDPOINT
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

    text = ""
    if "text" in msg:
        text = msg["text"]["body"]
    elif "interactive" in msg:
        it = msg["interactive"]
        if it["type"] == "button_reply":
            text = it["button_reply"]["title"]
        elif it["type"] == "list_reply":
            text = it["list_reply"]["title"]

    await process(user, text)
    return {"ok": True}
