import os
import json
import logging
from datetime import datetime
from typing import List, Dict

import httpx
import dateparser
from fastapi import APIRouter, Request, HTTPException

import firebase_admin
from firebase_admin import credentials, firestore

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

# ---------------- FIREBASE INIT ----------------
def get_db():
    try:
        if not firebase_admin._apps:
            sa = os.getenv("FIREBASE_CREDENTIALS")
            if not sa:
                raise ValueError("FIREBASE_CREDENTIALS env not found")

            cred = credentials.Certificate(json.loads(sa))
            firebase_admin.initialize_app(cred)

        return firestore.client()

    except Exception as e:
        logger.error("🔥 Firebase init failed: %s", e)
        return None


db = get_db()

# ---------------- ROUTER ----------------
router = APIRouter()

# ---------------- CONFIG ----------------
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "shreyaWebhook123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

WA_API = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"

# ---------------- DOCTOR SCHEDULE (BLOCK + CAPACITY) ----------------
doctorSchedule = {
    "Cardiology": {
        "09:00-10:00": 5,
        "10:00-11:00": 5,
        "11:00-12:00": 5,
    },
    "Neurology": {
        "14:00-15:00": 4,
        "15:00-16:00": 4,
        "16:00-17:00": 4,
    },
    "Orthopedics": {
        "10:00-11:00": 6,
        "11:00-12:00": 6,
        "12:00-13:00": 6,
    },
    "Pediatrics": {
        "15:00-16:00": 8,
        "16:00-17:00": 8,
        "17:00-18:00": 8,
    },
    "General Medicine": {
        "09:00-10:00": 10,
        "10:00-11:00": 10,
        "11:00-12:00": 10,
    },
    "Dermatology": {
        "09:00-12:00": 12,
        "12:00-15:00": 12,
        "15:00-18:00": 12,
    },
}

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
                "button": "Choose",
                "sections": [{"title": "Departments", "rows": rows}],
            },
        },
    })

# ---------------- FIRESTORE STATE ----------------
def get_state(sender):
    snap = db.collection("registration_states").document(sender).get()
    return snap.to_dict() if snap.exists else {"step": None, "data": {}}

def set_state(sender, step, data):
    db.collection("registration_states").document(sender).set({
        "step": step,
        "data": data,
        "updatedAt": firestore.SERVER_TIMESTAMP
    })

def reset_state(sender):
    db.collection("registration_states").document(sender).delete()

# ---------------- PATIENT ID (COUNTER) ----------------
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

# ---------------- MENU ----------------
async def show_menu(sender):
    await send_buttons(sender, "🏥 *NovaMed Multispeciality Care*\nChoose:", [
        {"id": "book", "title": "📅 Book Appointment"},
        {"id": "report", "title": "📄 Get Report"},
    ])
    set_state(sender, "menu", {})

# ---------------- MAIN FLOW ----------------
async def process_message(sender, text, msg):
    state = get_state(sender)
    step = state.get("step")
    data = state.get("data", {})

    if text.lower() in ["hi", "hello", "menu", "restart"]:
        reset_state(sender)
        await show_menu(sender)
        return

    if step == "menu":
        bid = msg["interactive"]["button_reply"]["id"]
        if bid == "book":
            set_state(sender, "first", {})
            await send_text(sender, "👤 Enter *First Name*:")
        elif bid == "report":
            set_state(sender, "get_report", {})
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

    if step == "phone":
        if not text.isdigit() or len(text) != 10:
            await send_text(sender, "❌ Invalid phone number.")
            return
        data["phone"] = text
        set_state(sender, "department", data)
        await send_list(sender, "🏥 Select Department:", [
            {"id": d, "title": d} for d in doctorSchedule.keys()
        ])
        return

    if step == "department":
        data["department"] = msg["interactive"]["list_reply"]["id"]
        set_state(sender, "date", data)
        await send_text(sender, "📅 Enter appointment date (YYYY-MM-DD):")
        return

    if step == "date":
        parsed = dateparser.parse(text)
        if not parsed or parsed.date() < datetime.now().date():
            await send_text(sender, "❌ Invalid date.")
            return

        data["date"] = parsed.strftime("%Y-%m-%d")
        blocks = doctorSchedule[data["department"]]
        available = []

        for block, limit in blocks.items():
            count = db.collection("patients") \
                .where("Department", "==", data["department"]) \
                .where("RegistrationDate", "==", data["date"]) \
                .where("TimeBlock", "==", block) \
                .stream()

            if sum(1 for _ in count) < limit:
                available.append(block)

        if not available:
            await send_text(sender, "❌ No slots available.")
            reset_state(sender)
            return

        set_state(sender, "time", data)
        await send_buttons(sender, "⏰ Select Time Slot:", [
            {"id": b, "title": b} for b in available[:3]
        ])
        return

    if step == "time":
        data["time"] = msg["interactive"]["button_reply"]["id"]
        pid = generate_patient_id()

        db.collection("patients").document(pid).set({
            "PatientID": pid,
            "FirstName": data["first"],
            "LastName": data["last"],
            "Phone": data["phone"],
            "WhatsApp": sender,
            "Department": data["department"],
            "RegistrationDate": data["date"],
            "TimeBlock": data["time"],
            "createdAt": firestore.SERVER_TIMESTAMP,
        })

        await send_text(
            sender,
            f"✅ *Appointment Confirmed*\n🆔 {pid}"
        )

        reset_state(sender)
        return

    if step == "get_report":
        pid = text.strip().upper()
        doc = db.collection("patients").document(pid).get()

        if not doc.exists:
            await send_text(sender, "❌ Patient ID not found.")
            return

        p = doc.to_dict()
        await send_text(
            sender,
            f"📄 *Patient Details*\n"
            f"Name: {p['FirstName']} {p['LastName']}\n"
            f"Dept: {p['Department']}\n"
            f"Date: {p['RegistrationDate']}\n"
            f"Time: {p['TimeBlock']}"
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

    text = msg.get("text", {}).get("body", "")
    if msg.get("interactive"):
        it = msg["interactive"]
        text = it.get("button_reply", {}).get("title") or it.get("list_reply", {}).get("title")

    await process_message(sender, text, msg)
    return {"status": "ok"}
