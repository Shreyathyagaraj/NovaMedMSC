import os, json, logging
from datetime import datetime, timedelta

import httpx, dateparser
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
# DOCTORS (REDUCED + SAFE)
# --------------------------------------------------
DOCTORS = {
    "Cardiology": ("10:00", "14:00", 5),
    "Neurology": ("10:00", "14:00", 4),
    "Orthopedics": ("10:00", "14:00", 6),
    "Pediatrics": ("10:00", "14:00", 8),
    "General Medicine": ("10:00", "14:00", 10),
    "Dermatology": ("10:00", "14:00", 6),
    "ENT": ("10:00", "14:00", 5),
    "Physician": ("10:00", "14:00", 6),
}

# --------------------------------------------------
# WHATSAPP HELPERS
# --------------------------------------------------
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

# --------------------------------------------------
# STATE
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
# TIME SLOTS (WITH REMAINING COUNT)
# --------------------------------------------------
def generate_slots(dept, date):
    start, end, cap = DOCTORS[dept]
    s = datetime.strptime(start, "%H:%M")
    e = datetime.strptime(end, "%H:%M")

    slots = []
    while s < e:
        n = s + timedelta(hours=1)
        block = f"{s.strftime('%H:%M')}-{n.strftime('%H:%M')}"

        booked = db.collection("patients") \
            .where("Department", "==", dept) \
            .where("Date", "==", date) \
            .where("Time", "==", block) \
            .stream()

        remaining = cap - sum(1 for _ in booked)
        if remaining > 0:
            slots.append(f"{block} ({remaining} left)")
        s = n

    return slots

# --------------------------------------------------
# PDF (DUMMY REPORT)
# --------------------------------------------------
def create_pdf(patient):
    path = f"/tmp/{patient['PatientID']}.pdf"
    c = canvas.Canvas(path, pagesize=A4)
    y = 750
    c.setFont("Helvetica", 12)

    for k, v in patient.items():
        c.drawString(50, y, f"{k}: {v}")
        y -= 20

    c.save()
    return path

# --------------------------------------------------
# MENU
# --------------------------------------------------
async def show_menu(user):
    await send_buttons(user, "🏥 *NovaMed*\nChoose:", ["Book Appointment", "Get Report"])
    set_state(user, "menu", {})

# --------------------------------------------------
# MAIN FLOW (STRICT & SAFE)
# --------------------------------------------------
async def process(user, text):
    text = text.strip()

    if text.lower() in ["hi", "hello", "menu", "restart"]:
        reset_state(user)
        await show_menu(user)
        return

    state = get_state(user)
    step = state.get("step")
    data = state.get("data", {})

    # ---------- MENU ----------
    if step == "menu":
        if text == "Book Appointment":
            set_state(user, "name", {})
            await send_text(user, "👤 Enter patient name:")
        elif text == "Get Report":
            set_state(user, "report", {})
            await send_text(user, "🆔 Enter Patient ID:")
        return

    # ---------- NAME ----------
    if step == "name":
        data["Name"] = text
        set_state(user, "phone", data)
        await send_text(user, "📞 Enter 10-digit phone number:")
        return

    # ---------- PHONE ----------
    if step == "phone":
        if not text.isdigit() or len(text) != 10:
            await send_text(user, "❌ Phone number must be exactly 10 digits")
            return
        data["Phone"] = text
        set_state(user, "department", data)
        await send_list(user, "🏥 Select Department:", list(DOCTORS.keys()))
        return

    # ---------- DEPARTMENT ----------
    if step == "department":
        if text not in DOCTORS:
            await send_text(user, "❌ Please select a department from the list")
            return
        data["Department"] = text
        set_state(user, "date", data)
        await send_text(user, "📅 Enter date (YYYY-MM-DD):")
        return

    # ---------- DATE ----------
    if step == "date":
        parsed = dateparser.parse(text)
        if not parsed or parsed.date() < datetime.now().date():
            await send_text(user, "❌ Date cannot be in the past")
            return

        data["Date"] = parsed.strftime("%Y-%m-%d")
        slots = generate_slots(data["Department"], data["Date"])

        if not slots:
            await send_text(user, "❌ No slots available for this date")
            reset_state(user)
            return

        set_state(user, "time", data)
        await send_buttons(user, "⏰ Select Time Slot:", slots)
        return

    # ---------- TIME ----------
    if step == "time":
        block = text.split(" (")[0]
        data["Time"] = block
        pid = generate_patient_id()

        record = {
            "PatientID": pid,
            **data,
            "WhatsApp": user,
            "createdAt": firestore.SERVER_TIMESTAMP
        }

        db.collection("patients").document(pid).set(record)
        await send_text(user, f"✅ Appointment Confirmed\n🆔 {pid}")
        reset_state(user)
        return

    # ---------- REPORT ----------
    if step == "report":
        doc = db.collection("patients").document(text).get()
        if not doc.exists:
            await send_text(user, "❌ Patient ID not found")
        else:
            create_pdf(doc.to_dict())
            await send_text(user, "📄 Dummy PDF report generated")
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
        it = msg["interactive"]
        text = (
            it.get("button_reply", {}) or
            it.get("list_reply", {})
        ).get("title", "")
    else:
        text = msg.get("text", {}).get("body", "")

    await process(user, text)
    return {"ok": True}
