import os, json, logging
from datetime import datetime, timedelta
from typing import List

import httpx, dateparser
from fastapi import APIRouter, Request, HTTPException

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from apscheduler.schedulers.background import BackgroundScheduler

import firebase_admin
from firebase_admin import credentials, firestore

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

# ---------------- FIREBASE INIT ----------------
if not firebase_admin._apps:
    cred = credentials.Certificate(json.loads(os.getenv("FIREBASE_CREDENTIALS")))
    firebase_admin.initialize_app(cred)

db = firestore.client()
router = APIRouter()

# ---------------- CONFIG ----------------
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WA_API = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"

# ---------------- SCHEDULER ----------------
scheduler = BackgroundScheduler()
scheduler.start()

# ---------------- DEPARTMENTS & SCHEDULE ----------------
DEPARTMENTS = {
    "Cardiology": ("10:00", "16:00"),
    "Neurology": ("10:00", "16:00"),
    "Orthopedics": ("10:00", "16:00"),
    "Pediatrics": ("12:00", "16:00"),
    "General Medicine": ("10:00", "16:00"),
    "Dermatology": ("10:00", "16:00"),
    "ENT": ("10:00", "14:00"),
    "Physician": ("10:00", "14:00"),
    "Anaesthesiology": ("10:00", "13:00"),
    "Ophthalmology": ("10:00", "13:00"),
    "Gynecology": ("12:00", "16:00"),
    "Dentist": ("10:00", "14:00"),
}

SLOT_CAPACITY = 5

# ---------------- WHATSAPP HELPERS ----------------
async def wa_send(payload):
    async with httpx.AsyncClient(timeout=15) as c:
        await c.post(
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

async def send_buttons(to, body, buttons: List[str]):
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

async def send_list(to, body, rows: List[str]):
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

# ---------------- STATE ----------------
def get_state(user):
    doc = db.collection("states").document(user).get()
    return doc.to_dict() if doc.exists else {}

def set_state(user, step, data):
    db.collection("states").document(user).set({
        "step": step,
        "data": data,
        "updatedAt": firestore.SERVER_TIMESTAMP
    })

def reset_state(user):
    db.collection("states").document(user).delete()

# ---------------- PATIENT ID ----------------
def generate_patient_id():
    ref = db.collection("meta").document("patient_counter")
    tx = db.transaction()

    @firestore.transactional
    def update(txn):
        snap = ref.get(transaction=txn)
        last = snap.to_dict().get("count", 1000) if snap.exists else 1000
        new = last + 1
        txn.set(ref, {"count": new})
        return f"P{new}"

    return update(tx)

# ---------------- TIME SLOTS ----------------
def generate_slots(start, end):
    slots = []
    s = datetime.strptime(start, "%H:%M")
    e = datetime.strptime(end, "%H:%M")
    while s < e:
        nxt = s + timedelta(hours=1)
        slots.append(f"{s.strftime('%H')}-{nxt.strftime('%H')}")
        s = nxt
    return slots

# ---------------- PDF ----------------
def generate_pdf(pid):
    path = f"/tmp/{pid}.pdf"
    c = canvas.Canvas(path, pagesize=A4)
    c.drawString(100, 750, "NovaMed Hospital")
    c.drawString(100, 720, f"Patient ID: {pid}")
    c.drawString(100, 690, "Report: Normal (Dummy Report)")
    c.save()
    return path

# ---------------- REMINDER ----------------
def schedule_reminder(phone, date, slot):
    time = slot.split("-")[0]
    appt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H")
    remind = appt - timedelta(minutes=10)

    def job():
        import asyncio
        asyncio.run(send_text(phone, "⏰ Reminder: Appointment in 10 minutes"))

    scheduler.add_job(job, "date", run_date=remind)

# ---------------- MAIN FLOW ----------------
async def process(user, text):
    if text.lower() in ["hi", "hello", "menu", "restart"]:
        reset_state(user)
        await send_buttons(user, "🏥 NovaMed\nChoose:", ["Book Appointment", "Get Report"])
        set_state(user, "menu", {})
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
        data["name"] = text
        set_state(user, "phone", data)
        await send_text(user, "📞 Enter 10-digit phone number:")
        return

    if step == "phone":
        if not text.isdigit() or len(text) != 10:
            await send_text(user, "❌ Phone must be exactly 10 digits")
            return
        data["phone"] = text
        set_state(user, "department", data)
        await send_list(user, "🏥 Select Department:", list(DEPARTMENTS.keys()))
        return

    if step == "department":
        data["department"] = text
        set_state(user, "date", data)
        await send_text(user, "📅 Enter date (YYYY-MM-DD):")
        return

    if step == "date":
        parsed = dateparser.parse(text)
        if not parsed or parsed.date() < datetime.now().date():
            await send_text(user, "❌ Date cannot be past")
            return
        data["date"] = parsed.strftime("%Y-%m-%d")
        start, end = DEPARTMENTS[data["department"]]
        slots = generate_slots(start, end)
        set_state(user, "time", data)
        await send_buttons(user, "⏰ Select Time Slot:", slots[:3])
        return

    if step == "time":
        data["slot"] = text
        pid = generate_patient_id()

        db.collection("patients").document(pid).set({
            "PatientID": pid,
            "Name": data["name"],
            "Phone": data["phone"],
            "Department": data["department"],
            "Date": data["date"],
            "Slot": data["slot"]
        })

        set_state(user, "reminder", {"pid": pid, **data})
        await send_buttons(user, "⏰ Need reminder 10 minutes earlier?", ["Yes", "No"])
        return

    if step == "reminder":
        if text == "Yes":
            schedule_reminder(user, data["date"], data["slot"])
        await send_text(user, f"✅ Appointment Confirmed\n🆔 {data['pid']}")
        reset_state(user)
        return

    if step == "report":
        doc = db.collection("patients").document(text).get()
        if not doc.exists:
            await send_text(user, "❌ Patient ID not found")
        else:
            pdf = generate_pdf(text)
            await send_text(user, "📄 Dummy PDF report generated (for demo)")
        reset_state(user)

# ---------------- WEBHOOK ----------------
@router.get("/webhook")
async def verify(req: Request):
    if req.query_params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(req.query_params.get("hub.challenge"))
    raise HTTPException(403)

@router.post("/webhook")
async def receive(req: Request):
    body = await req.json()
    value = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})

    if "messages" not in value:
        return {"ok": True}

    msg = value["messages"][0]
    user = msg["from"]

    text = ""
    if msg.get("text"):
        text = msg["text"]["body"].strip()
    elif msg.get("interactive"):
        it = msg["interactive"]
        if it.get("button_reply"):
            text = it["button_reply"]["title"]
        elif it.get("list_reply"):
            text = it["list_reply"]["title"]

    await process(user, text)
    return {"ok": True}
