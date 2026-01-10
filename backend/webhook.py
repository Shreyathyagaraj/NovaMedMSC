import os, json, logging
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Request, HTTPException

import firebase_admin
from firebase_admin import credentials, firestore

from apscheduler.schedulers.background import BackgroundScheduler

# ======================================================
# CONFIG
# ======================================================
TIMEOUT_MINUTES = 5
REMINDER_BEFORE_MIN = 30

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

# ======================================================
# FIREBASE
# ======================================================
if not firebase_admin._apps:
    cred = credentials.Certificate(json.loads(os.getenv("FIREBASE_CREDENTIALS")))
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ======================================================
# ROUTER
# ======================================================
router = APIRouter()

# ======================================================
# WHATSAPP
# ======================================================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WA_API = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"

# ======================================================
# SCHEDULER
# ======================================================
scheduler = BackgroundScheduler()
scheduler.start()

# ======================================================
# DOCTORS
# ======================================================
DOCTORS = {
    "Cardiology": ("10:00", "16:00", 5),
    "Neurology": ("12:00", "16:00", 4),
    "Orthopedics": ("10:00", "16:00", 6),
    "Pediatrics": ("10:00", "16:00", 8),
    "General Medicine": ("09:00", "13:00", 10),
    "Dermatology": ("09:00", "18:00", 12),
}

# ======================================================
# WHATSAPP HELPERS
# ======================================================
async def wa_send(payload):
    async with httpx.AsyncClient(timeout=20) as client:
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

# ======================================================
# STATE MANAGEMENT
# ======================================================
def get_state(user):
    doc = db.collection("states").document(user).get()
    if not doc.exists:
        return None

    state = doc.to_dict()
    updated = state.get("updated")

    if updated:
        if (datetime.utcnow() - updated.replace(tzinfo=None)).total_seconds() > TIMEOUT_MINUTES * 60:
            reset_state(user)
            return None

    return state

def set_state(user, step, data):
    db.collection("states").document(user).set({
        "step": step,
        "data": data,
        "updated": firestore.SERVER_TIMESTAMP
    })

def reset_state(user):
    db.collection("states").document(user).delete()

# ======================================================
# UTILITIES
# ======================================================
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
    return sum(1 for _ in db.collection("patients")
               .where("Department", "==", dept)
               .where("Date", "==", date)
               .where("Time", "==", slot)
               .stream())

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

# ======================================================
# REMINDER
# ======================================================
def schedule_reminder(user, record):
    appt_time = datetime.strptime(
        f"{record['Date']} {record['Time'].split('-')[0]}",
        "%Y-%m-%d %H:%M"
    )
    remind_at = appt_time - timedelta(minutes=REMINDER_BEFORE_MIN)

    if remind_at <= datetime.now():
        return

    scheduler.add_job(
        lambda: send_text(
            user,
            f"⏰ Reminder: Appointment at {record['Time']} ({record['Department']})"
        ),
        trigger="date",
        run_date=remind_at
    )

# ======================================================
# MENU
# ======================================================
async def show_menu(user):
    await send_buttons(
        user,
        "🏥 *NovaMed Multispeciality Care*\n“There is no true illness”",
        ["Book Appointment", "Get Report"]
    )
    set_state(user, "menu", {})

# ======================================================
# MAIN FLOW
# ======================================================
async def process(user, text):
    text = text.strip().lower()

    if text in ["hi", "hello", "hii", "hlo", "hey", "menu"]:
        reset_state(user)
        await show_menu(user)
        return

    state = get_state(user)
    if not state:
        await show_menu(user)
        return

    step = state["step"]
    data = state["data"]

    # ---------------- MENU ----------------
    if step == "menu":
        if text == "book appointment":
            set_state(user, "name", {})
            await send_text(user, "👤 Enter patient name:")
        elif text == "get report":
            set_state(user, "report", {})
            await send_text(user, "🆔 Enter Patient ID:")
        return

    # ---------------- APPOINTMENT ----------------
    if step == "name":
        data["Name"] = text.title()
        set_state(user, "phone", data)
        await send_text(user, "📞 Enter 10-digit phone number:")
        return

    if step == "phone":
        if not text.isdigit() or len(text) != 10:
            await send_text(user, "❌ Phone must be exactly 10 digits")
            return
        data["Phone"] = text
        set_state(user, "department", data)
        await send_list(user, "🏥 Select Department:", list(DOCTORS.keys()))
        return

    if step == "department":
        data["Department"] = text.title()
        set_state(user, "date", data)
        await send_text(user, "📅 Enter appointment date in format YYYY-MM-DD")
        return

    # 🔥 FIXED DATE STEP
    if step == "date":
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            await send_text(user, "❌ Invalid date format. Use YYYY-MM-DD")
            return

        if parsed.date() < datetime.now().date():
            await send_text(user, "❌ Past dates are not allowed")
            return

        data["Date"] = parsed.strftime("%Y-%m-%d")

        start, end, cap = DOCTORS[data["Department"]]
        now = datetime.now()

        slots = []
        for s in generate_slots(start, end):
            slot_time = datetime.strptime(
                f"{data['Date']} {s.split('-')[0]}",
                "%Y-%m-%d %H:%M"
            )

            if slot_time <= now:
                continue

            left = cap - slot_count(data["Department"], data["Date"], s)
            if left > 0:
                slots.append(f"{s} ({left} slots left)")

        if not slots:
            await send_text(user, "❌ No slots available for this date")
            reset_state(user)
            return

        set_state(user, "time", data)
        await send_buttons(user, "⏰ Select Time Slot:", slots)
        return

    if step == "time":
        data["Time"] = text.split(" ")[0]
        set_state(user, "reminder", data)
        await send_buttons(user, "⏰ Do you want reminder?", ["Yes", "No"])
        return

    if step == "reminder":
        pid = generate_patient_id()
        record = {**data, "PatientID": pid}

        db.collection("patients").document(pid).set(record)

        if text == "yes":
            schedule_reminder(user, record)

        await send_text(user, f"✅ Appointment Confirmed\n🆔 {pid}")
        reset_state(user)
        return

    # ---------------- REPORT ----------------
    if step == "report":
        doc = db.collection("patients").document(text.upper()).get()
        if not doc.exists:
            await send_text(user, "❌ Patient ID not found")
            return

        await send_text(user, "📄 Report found. Please visit hospital reception.")
        reset_state(user)

# ======================================================
# WEBHOOK ENDPOINTS
# ======================================================
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
        text = (inter.get("button_reply") or inter.get("list_reply")).get("title", "")
    else:
        text = msg.get("text", {}).get("body", "")

    await process(user, text)
    return {"ok": True}
