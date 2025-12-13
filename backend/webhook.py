# backend/webhook.py

import os
import re
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List

import httpx
from fastapi import APIRouter, Request, HTTPException
from firebase_admin import firestore
import dateparser

# ---------------- FIREBASE INIT ----------------
from firebase_config import init_firebase

db = init_firebase()

router = APIRouter()
logger = logging.getLogger("webhook")
logging.basicConfig(level=logging.INFO)

# ---------------- CONFIG ----------------
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "shreyaWebhook123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

NLP_SUPPORT_URL = os.getenv("NLP_SUPPORT_URL", "")
REPORT_PDF_URL = os.getenv("REPORT_PDF_URL", "")

STATE_TIMEOUT_MINUTES = 10  # 🔥 AUTO RESET TIMEOUT

# ---------------- DOCTOR CONFIG ----------------
doctorSchedule = {
    "Cardiology": ["09:00", "12:00"],
    "Neurology": ["14:00", "17:00"],
    "Orthopedics": ["10:00", "13:00"],
    "Pediatrics": ["15:00", "18:00"],
    "General Medicine": ["09:00", "12:00"],
    "Dermatology": ["09:00", "18:00"],
}

doctorLimits = {
    "Cardiology": 10,
    "Neurology": 8,
    "Orthopedics": 6,
    "Pediatrics": 12,
    "General Medicine": 10,
    "Dermatology": 15,
}

DEPARTMENT_SLOTS = {
    d: {"times": doctorSchedule[d], "capacity": doctorLimits[d]}
    for d in doctorSchedule
}

# ---------------- WHATSAPP HELPERS ----------------
WA_API = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"

async def wa_post(payload: dict):
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    async with httpx.AsyncClient(timeout=15) as client:
        return await client.post(WA_API, json=payload, headers=headers)

async def send_whatsapp_text(to: str, text: str):
    await wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    })

async def send_whatsapp_buttons(to: str, body: str, buttons: List[Dict[str,str]]):
    await wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": b} for b in buttons
                ]
            }
        }
    })

async def send_whatsapp_list(to: str, body: str, btn: str, title: str, rows: list):
    await wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": btn,
                "sections": [{"title": title, "rows": rows}]
            }
        }
    })

# ---------------- UTILITIES ----------------
def normalize_phone(text: str):
    digits = re.sub(r"\D", "", text)
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) > 10:
        return "+" + digits
    return None

def parse_date(text: str):
    p = dateparser.parse(text)
    return p.strftime("%Y-%m-%d") if p else None

# ---------------- STATE HELPERS ----------------
def get_state(sender: str):
    ref = db.collection("registration_states").document(sender)
    snap = ref.get()
    return snap.to_dict() if snap.exists else {}

def set_state(sender: str, step: str, data: dict):
    db.collection("registration_states").document(sender).set({
        "step": step,
        "data": data,
        "updatedAt": firestore.SERVER_TIMESTAMP
    })

def reset_state(sender: str):
    db.collection("registration_states").document(sender).delete()

def is_state_expired(state: dict):
    ts = state.get("updatedAt")
    if not isinstance(ts, datetime):
        return False
    return datetime.now(timezone.utc) - ts > timedelta(minutes=STATE_TIMEOUT_MINUTES)

async def send_main_menu(sender: str):
    await send_whatsapp_buttons(
        sender,
        "🏥 *Welcome to NovaMed*\nChoose an option:",
        [
            {"id": "opt_book", "title": "Book Appointment"},
            {"id": "opt_report", "title": "Get Report"},
            {"id": "opt_support", "title": "Support"},
        ]
    )
    set_state(sender, "menu", {})

# ---------------- TRANSACTION ----------------
def attempt_registration_tx(data: dict):
    slot_id = f"{data['department']}_{data['date']}_{data['time']}"
    slot_ref = db.collection("appointments").document(slot_id)
    counter_ref = db.collection("metadata").document("patient_counter")

    @firestore.transactional
    def register(tx):
        slot_snap = next(tx.get_all([slot_ref]), None)
        count = slot_snap.to_dict().get("count", 0) if slot_snap and slot_snap.exists else 0

        if count >= DEPARTMENT_SLOTS[data["department"]]["capacity"]:
            raise ValueError("Slot full")

        counter_snap = next(tx.get_all([counter_ref]), None)
        new_id = (counter_snap.to_dict().get("count", 1000) + 1) if counter_snap and counter_snap.exists else 1001

        pid = f"P{new_id}"
        tx.set(counter_ref, {"count": new_id}, merge=True)

        tx.set(db.collection("patients").document(pid), {
            "PatientID": pid,
            "FirstName": data["first"],
            "LastName": data["last"],
            "Phone": data["phone"],
            "Department": data["department"],
            "RegistrationDate": data["date"],
            "RegistrationTime": data["time"],
            "createdAt": firestore.SERVER_TIMESTAMP
        })

        tx.set(slot_ref, {"count": count + 1}, merge=True)
        return pid

    return register(db.transaction())

# ---------------- MESSAGE PROCESSOR ----------------
async def process_incoming_message(sender: str, text: str, msg: dict):
    raw = (text or "").strip()
    lower = raw.lower()

    # 🔥 GLOBAL RESET
    if lower in ["hi", "hello", "menu", "0", "start", "restart"]:
        reset_state(sender)
        await send_main_menu(sender)
        return

    state = get_state(sender)

    # ⏱ TIMEOUT RESET
    if is_state_expired(state):
        reset_state(sender)
        await send_whatsapp_text(sender, "⌛ Session expired.")
        await send_main_menu(sender)
        return

    step = state.get("step")
    data = state.get("data", {})

    if not step:
        await send_main_menu(sender)
        return

    # ---- MENU ----
    if step == "menu":
        bid = msg.get("interactive", {}).get("button_reply", {}).get("id")
        if bid == "opt_book":
            await send_whatsapp_text(sender, "Enter First Name:")
            set_state(sender, "first", {})
        elif bid == "opt_report":
            await send_whatsapp_text(sender, "Enter Patient ID:")
            set_state(sender, "report", {})
        elif bid == "opt_support":
            await send_whatsapp_text(sender, "Support mode. Ask your question.")
            set_state(sender, "support", {})
        return

    # ---- BOOK FLOW ----
    if step == "first":
        data["first"] = raw.title()
        set_state(sender, "last", data)
        await send_whatsapp_text(sender, "Enter Last Name:")
        return

    if step == "last":
        data["last"] = raw.title()
        set_state(sender, "phone", data)
        await send_whatsapp_text(sender, "Enter Phone (10 digits):")
        return

    if step == "phone":
        phone = normalize_phone(raw)
        if not phone:
            await send_whatsapp_text(sender, "Invalid phone. Try again.")
            return
        data["phone"] = phone
        rows = [{"id": d, "title": d} for d in DEPARTMENT_SLOTS]
        await send_whatsapp_list(sender, "Select Department:", "Choose", "Departments", rows)
        set_state(sender, "dept", data)
        return

    if step == "dept":
        dept = msg["interactive"]["list_reply"]["id"]
        data["department"] = dept
        await send_whatsapp_text(sender, "Enter appointment date (YYYY-MM-DD):")
        set_state(sender, "date", data)
        return

    if step == "date":
        date = parse_date(raw)
        if not date:
            await send_whatsapp_text(sender, "Invalid date.")
            return
        data["date"] = date

        start, end = DEPARTMENT_SLOTS[data["department"]]["times"]
        times = [f"{h:02d}:00" for h in range(int(start[:2]), int(end[:2]) + 1)]
        rows = [{"id": t, "title": t} for t in times]
        await send_whatsapp_list(sender, "Select Time:", "Choose", "Times", rows)
        data["times"] = times
        set_state(sender, "time", data)
        return

    if step == "time":
        time = msg["interactive"]["list_reply"]["id"]
        data["time"] = time
        pid = attempt_registration_tx(data)
        await send_whatsapp_text(sender, f"✅ Booked!\nPatient ID: {pid}")
        reset_state(sender)
        return

    # ---- SUPPORT ----
    if step == "support":
        if lower in ["exit", "menu", "0"]:
            reset_state(sender)
            await send_main_menu(sender)
        else:
            await send_whatsapp_text(sender, "Support received. Our team will respond.")
        return

# ---------------- WEBHOOK ENDPOINTS ----------------
@router.get("/webhook")
async def verify(request: Request):
    if request.query_params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(request.query_params.get("hub.challenge"))
    raise HTTPException(status_code=403)

@router.post("/webhook")
async def webhook(request: Request):
    body = await request.json()
    entry = body["entry"][0]["changes"][0]["value"]
    messages = entry.get("messages", [])
    if not messages:
        return {"status": "ignored"}

    msg = messages[0]
    sender = msg["from"]
    text = msg.get("text", {}).get("body", "")

    await process_incoming_message(sender, text, msg)
    return {"status": "ok"}
