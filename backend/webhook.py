import os
import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict

import httpx
from fastapi import APIRouter, Request, HTTPException
from firebase_admin import firestore
import dateparser

from firebase_config import init_firebase
from report_utils import generate_report_pdf

# ---------------- INIT ----------------
db = init_firebase()
router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

# ---------------- CONFIG ----------------
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "shreyaWebhook123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
REPORT_PDF_URL = os.getenv("REPORT_PDF_URL")

WA_API = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"

# ---------------- DOCTOR CONFIG ----------------
doctorSchedule = {
    "Cardiology": ["09:00", "12:00"],
    "Neurology": ["14:00", "17:00"],
    "Orthopedics": ["10:00", "13:00"],
    "Pediatrics": ["15:00", "18:00"],
    "General Medicine": ["09:00", "12:00"],
    "Dermatology": ["09:00", "18:00"],
}

DAILY_LIMITS = {
    "Cardiology": 12,
    "Neurology": 10,
    "Orthopedics": 14,
    "Pediatrics": 16,
    "General Medicine": 20,
    "Dermatology": 18,
}

SLOT_LIMIT = 2
DEPARTMENTS = list(doctorSchedule.keys())

# ---------------- WHATSAPP HELPERS ----------------
async def wa_post(payload: dict):
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(
            WA_API,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            json=payload,
        )

async def send_text(to: str, text: str):
    await wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    })

async def send_buttons(to: str, body: str, buttons: List[Dict[str, str]]):
    await wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in buttons
                ]
            },
        },
    })

async def send_list(to: str, body: str, rows: List[Dict[str, str]]):
    await wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": "Select",
                "sections": [{"title": "Departments", "rows": rows}],
            },
        },
    })

async def send_document(to: str, url: str, filename: str):
    await wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {"link": url, "filename": filename},
    })

# ---------------- UTIL ----------------
def generate_slots(start: str, end: str):
    slots = []
    t = datetime.strptime(start, "%H:%M")
    e = datetime.strptime(end, "%H:%M")
    while t < e:
        slots.append(t.strftime("%H:%M"))
        t += timedelta(minutes=30)
    return slots

# ✅ PATIENT ID: P1000+
def generate_patient_id():
    ref = db.collection("metadata").document("patient_counter")

    @firestore.transactional
    def txn(transaction):
        snap = ref.get(transaction=transaction)
        last = snap.to_dict().get("count", 999) if snap.exists else 999
        new = last + 1
        transaction.set(ref, {"count": new})
        return f"P{new}"

    return txn(db.transaction())

# ---------------- ATOMIC LIMIT CHECK ----------------
def book_slot_atomic(dept, date, time):
    slot_ref = db.collection("slot_counters").document(f"{dept}_{date}_{time}")
    day_ref = db.collection("daily_counters").document(f"{dept}_{date}")

    @firestore.transactional
    def txn(transaction):
        day_snap = day_ref.get(transaction=transaction)
        day_count = day_snap.to_dict().get("count", 0) if day_snap.exists else 0
        if day_count >= DAILY_LIMITS[dept]:
            raise Exception("DAILY_LIMIT_REACHED")

        slot_snap = slot_ref.get(transaction=transaction)
        slot_count = slot_snap.to_dict().get("count", 0) if slot_snap.exists else 0
        if slot_count >= SLOT_LIMIT:
            raise Exception("SLOT_FULL")

        transaction.set(day_ref, {"count": day_count + 1}, merge=True)
        transaction.set(slot_ref, {"count": slot_count + 1}, merge=True)

    txn(db.transaction())

# ---------------- STATE ----------------
def get_state(sender):
    ref = db.collection("registration_states").document(sender)
    snap = ref.get()
    return snap.to_dict() if snap.exists else {"step": None, "data": {}}

def set_state(sender, step, data):
    db.collection("registration_states").document(sender).set({
        "step": step,
        "data": data,
        "updatedAt": firestore.SERVER_TIMESTAMP
    })

def reset_state(sender):
    db.collection("registration_states").document(sender).delete()

# ---------------- MENU ----------------
async def show_menu(sender):
    await send_buttons(sender, "🏥 *NovaMed Multispeciality Care*", [
        {"id": "book", "title": "📅 Book Appointment"},
        {"id": "report", "title": "📄 Get Report"},
    ])
    set_state(sender, "menu", {})

# ---------------- MAIN FLOW ----------------
async def process_message(sender, text, msg):
    now = datetime.now()
    state = get_state(sender)
    step = state.get("step")
    data = state.get("data", {})

    if text.lower() in ["hi", "hello", "menu", "restart"]:
        reset_state(sender)
        await show_menu(sender)
        return

    if not step:
        await show_menu(sender)
        return

    if step == "menu":
        bid = msg["interactive"]["button_reply"]["id"]
        if bid == "book":
            set_state(sender, "first", {})
            await send_text(sender, "👤 Enter *First Name*:")
        else:
            set_state(sender, "report", {})
            await send_text(sender, "🆔 Enter *Patient ID*:")
        return

    if step == "first":
        data["first"] = text.title()
        set_state(sender, "last", data)
        await send_text(sender, "👤 Enter *Last Name*:")
        return

    if step == "last":
        data["last"] = text.title()
        set_state(sender, "phone", data)
        await send_text(sender, "📞 Enter *Phone Number* (10 digits):")
        return

    # ✅ PHONE STEP
    if step == "phone":
        phone = re.sub(r"\D", "", text)
        if len(phone) != 10:
            await send_text(sender, "❌ Invalid phone number. Enter 10 digits.")
            return

        data["phone"] = "+91" + phone
        set_state(sender, "department", data)
        await send_list(sender, "🏥 Select Department:",
                        [{"id": d, "title": d} for d in DEPARTMENTS])
        return

    if step == "department":
        data["department"] = msg["interactive"]["list_reply"]["id"]
        set_state(sender, "date", data)
        await send_text(sender, "📅 Enter appointment date (YYYY-MM-DD):")
        return

    if step == "date":
        parsed = dateparser.parse(text)
        if not parsed or parsed.date() < now.date():
            await send_text(sender, "❌ Invalid or past date.")
            return

        data["date"] = parsed.strftime("%Y-%m-%d")
        slots = generate_slots(*doctorSchedule[data["department"]])

        available = []
        for s in slots:
            slot_dt = datetime.strptime(f"{data['date']} {s}", "%Y-%m-%d %H:%M")
            if data["date"] == now.strftime("%Y-%m-%d") and slot_dt <= now:
                continue
            available.append(s)

        if not available:
            await send_text(sender, "❌ No future slots available.")
            reset_state(sender)
            return

        set_state(sender, "time", data)
        await send_buttons(sender, "⏰ Select Time:",
                           [{"id": s, "title": s} for s in available[:3]])
        return

    if step == "time":
        time = msg["interactive"]["button_reply"]["id"]

        try:
            book_slot_atomic(data["department"], data["date"], time)
        except Exception as e:
            await send_text(sender, "❌ Slot unavailable. Try another.")
            reset_state(sender)
            return

        pid = generate_patient_id()
        appt_dt = datetime.strptime(f"{data['date']} {time}", "%Y-%m-%d %H:%M")

        db.collection("patients").document(pid).set({
            "PatientID": pid,
            "FirstName": data["first"],
            "LastName": data["last"],
            "Phone": data["phone"],
            "Department": data["department"],
            "RegistrationDate": data["date"],
            "RegistrationTime": time,
            "AppointmentDateTime": appt_dt.isoformat(),
            "ReminderSent": False,
        })

        await send_text(sender,
            f"✅ *Appointment Confirmed!*\n"
            f"🆔 {pid}\n📅 {data['date']} ⏰ {time}"
        )
        reset_state(sender)

# ---------------- WEBHOOK ----------------
@router.get("/webhook")
async def verify(request: Request):
    if request.query_params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(request.query_params.get("hub.challenge"))
    raise HTTPException(status_code=403)

@router.post("/webhook")
async def receive(request: Request):
    body = await request.json()
    value = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
    if "messages" not in value:
        return {"status": "ignored"}

    msg = value["messages"][0]
    sender = msg["from"]

    text = (
        msg.get("text", {}).get("body")
        or msg.get("interactive", {}).get("button_reply", {}).get("title")
        or msg.get("interactive", {}).get("list_reply", {}).get("title")
        or ""
    )

    await process_message(sender, text, msg)
    return {"status": "ok"}
