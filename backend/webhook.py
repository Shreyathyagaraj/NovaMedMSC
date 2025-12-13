# backend/webhook.py

import os
import re
import logging
from datetime import datetime, timedelta
from typing import List

import httpx
from fastapi import APIRouter, Request, HTTPException
from firebase_admin import firestore
import dateparser

from firebase_config import init_firebase

# ================= INIT =================
db = init_firebase()
router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

# ================= CONFIG =================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "shreyaWebhook123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

NLP_SUPPORT_URL = os.getenv("NLP_SUPPORT_URL", "")
REPORT_PDF_URL = os.getenv("REPORT_PDF_URL", "")

WA_API = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"

STATE_TIMEOUT_MINUTES = 10

# ================= DOCTOR CONFIG =================
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

# ================= WHATSAPP HELPERS =================
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

async def send_whatsapp_buttons(to: str, body: str, buttons: List[dict]):
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

async def send_whatsapp_list(to, body, button, section, rows):
    await wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": button,
                "sections": [{"title": section, "rows": rows}]
            }
        }
    })

async def send_whatsapp_document(to, url, name):
    await wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {"link": url, "filename": name}
    })

# ================= UTILITIES =================
def normalize_phone(phone):
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) > 10:
        return "+" + digits
    return None

def parse_date(text):
    d = dateparser.parse(text)
    return d.strftime("%Y-%m-%d") if d else None

# ================= STATE =================
def get_state(sender):
    ref = db.collection("registration_states").document(sender)
    snap = ref.get()
    if not snap.exists:
        return {"step": None, "data": {}, "updatedAt": None}
    return snap.to_dict()

def set_state(sender, step, data):
    db.collection("registration_states").document(sender).set({
        "step": step,
        "data": data,
        "updatedAt": firestore.SERVER_TIMESTAMP
    })

def reset_state(sender):
    db.collection("registration_states").document(sender).delete()

def is_state_expired(state):
    ts = state.get("updatedAt")
    if not ts:
        return False
    return datetime.utcnow() - ts.replace(tzinfo=None) > timedelta(minutes=STATE_TIMEOUT_MINUTES)

# ================= TRANSACTION =================
def attempt_registration_tx(data):
    slot_id = f"{data['department']}_{data['registrationDate']}_{data['registrationTime']}"
    slot_ref = db.collection("appointments").document(slot_id)
    counter_ref = db.collection("metadata").document("patient_counter")

    @firestore.transactional
    def register(txn):
        slot_snap = next(txn.get_all([slot_ref]), None)
        count = slot_snap.to_dict().get("count", 0) if slot_snap and slot_snap.exists else 0

        if count >= DEPARTMENT_SLOTS[data["department"]]["capacity"]:
            raise ValueError("Slot full")

        counter_snap = next(txn.get_all([counter_ref]), None)
        num = counter_snap.to_dict().get("count", 1000) + 1 if counter_snap and counter_snap.exists else 1001
        pid = f"P{num}"

        txn.set(counter_ref, {"count": num}, merge=True)
        txn.set(db.collection("patients").document(pid), {**data, "PatientID": pid, "createdAt": firestore.SERVER_TIMESTAMP})
        txn.set(slot_ref, {"count": count + 1}, merge=True)
        return pid

    return register(db.transaction())

# ================= NLP =================
async def nlp_support_reply(q):
    if not NLP_SUPPORT_URL:
        return "Support not available."
    async with httpx.AsyncClient() as c:
        r = await c.post(NLP_SUPPORT_URL, json={"query": q})
        return r.json().get("answer", "No response.")

# ================= CORE =================
async def process_incoming_message(sender, text, msg):
    text_raw = text.strip()
    text_l = text_raw.lower()

    # 🔴 GLOBAL MENU RESET
    if text_l in ["hi", "hello", "menu", "0", "restart", "start"]:
        reset_state(sender)
        await send_whatsapp_buttons(sender, "🏥 *NovaMed Main Menu*", [
            {"id": "opt_book", "title": "Book Appointment"},
            {"id": "opt_report", "title": "Get Report"},
            {"id": "opt_support", "title": "Support"},
        ])
        set_state(sender, "menu", {})
        return

    state = get_state(sender)
    if is_state_expired(state):
        reset_state(sender)
        await send_whatsapp_text(sender, "Session expired. Send *Hi* to restart.")
        return

    step = state.get("step")
    data = state.get("data", {})

    # ===== MENU =====
    if step == "menu":
        bid = msg.get("interactive", {}).get("button_reply", {}).get("id")
        if bid == "opt_book":
            set_state(sender, "first_name", {})
            await send_whatsapp_text(sender, "Enter First Name:")
        elif bid == "opt_report":
            set_state(sender, "report", {})
            await send_whatsapp_text(sender, "Enter Patient ID:")
        elif bid == "opt_support":
            set_state(sender, "support", {})
            await send_whatsapp_text(sender, "Ask your question:")
        return

    # ===== BOOKING FLOW =====
    if step == "first_name":
        data["firstName"] = text_raw.title()
        set_state(sender, "last_name", data)
        await send_whatsapp_text(sender, "Enter Last Name:")
        return

    if step == "last_name":
        data["lastName"] = text_raw.title()
        set_state(sender, "gender", data)
        await send_whatsapp_buttons(sender, "Select Gender:", [
            {"id": "g_male", "title": "Male"},
            {"id": "g_female", "title": "Female"},
            {"id": "g_other", "title": "Other"},
        ])
        return

    if step == "gender":
        bid = msg.get("interactive", {}).get("button_reply", {}).get("id")
        if bid:
            data["gender"] = bid.split("_")[1].title()
            set_state(sender, "phone", data)
            await send_whatsapp_text(sender, "Enter Phone Number:")
        return

    if step == "phone":
        phone = normalize_phone(text_raw)
        if not phone:
            await send_whatsapp_text(sender, "Invalid phone.")
            return
        data["phoneNumber"] = phone
        set_state(sender, "department", data)
        await send_whatsapp_text(sender, "\n".join([f"{i+1}. {d}" for i, d in enumerate(DEPARTMENT_SLOTS)]))
        return

    if step == "department":
        depts = list(DEPARTMENT_SLOTS)
        if not text_raw.isdigit():
            await send_whatsapp_text(sender, "Enter valid number.")
            return
        data["department"] = depts[int(text_raw) - 1]
        set_state(sender, "date", data)
        await send_whatsapp_text(sender, "Enter date (YYYY-MM-DD):")
        return

    if step == "date":
        data["registrationDate"] = parse_date(text_raw)
        start, end = DEPARTMENT_SLOTS[data["department"]]["times"]
        times = [f"{h:02d}:00" for h in range(int(start[:2]), int(end[:2]) + 1)]
        data["times"] = times
        set_state(sender, "time", data)
        await send_whatsapp_list(sender, "Select Time", "Choose", "Slots",
            [{"id": f"time_{i}", "title": t} for i, t in enumerate(times)])
        return

    if step == "time":
        idx = int(msg["interactive"]["list_reply"]["id"].split("_")[1])
        data["registrationTime"] = data["times"][idx]
        pid = attempt_registration_tx(data)
        await send_whatsapp_text(sender, f"✅ Appointment Booked!\nPatient ID: {pid}")
        reset_state(sender)
        return

    # ===== REPORT =====
    if step == "report":
        pid = text_raw if text_raw.startswith("P") else f"P{text_raw}"
        doc = db.collection("patients").document(pid).get()
        if not doc.exists:
            await send_whatsapp_text(sender, "Invalid Patient ID.")
        else:
            d = doc.to_dict()
            await send_whatsapp_text(sender, f"{d['FirstName']} {d['LastName']}\n{d['Department']}")
            if REPORT_PDF_URL:
                await send_whatsapp_document(sender, f"{REPORT_PDF_URL}/{pid}.pdf", f"{pid}.pdf")
        reset_state(sender)
        return

    # ===== SUPPORT =====
    if step == "support":
        reply = await nlp_support_reply(text_raw)
        await send_whatsapp_text(sender, reply)
        return

# ================= WEBHOOK =================
@router.get("/webhook")
async def verify(request: Request):
    if request.query_params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(request.query_params.get("hub.challenge"))
    raise HTTPException(403)

@router.post("/webhook")
async def receive(request: Request):
    body = await request.json()
    msg = body["entry"][0]["changes"][0]["value"]["messages"][0]
    sender = msg["from"]

    text = msg.get("text", {}).get("body", "")
    if msg.get("interactive"):
        text = msg["interactive"].get("button_reply", {}).get("title", text)

    await process_incoming_message(sender, text, msg)
    return {"status": "ok"}
