import os
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict

import httpx
import dateparser
from fastapi import APIRouter, Request, HTTPException

import firebase_admin
from firebase_admin import credentials, firestore

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

# ---------------- FIREBASE INIT (ENV BASED) ----------------
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

# ---------------- UTIL ----------------
def generate_slots(start, end):
    t = datetime.strptime(start, "%H:%M")
    e = datetime.strptime(end, "%H:%M")
    slots = []
    while t < e:
        slots.append(t.strftime("%H:%M"))
        t += timedelta(minutes=30)
    return slots

# ---------------- STATE ----------------
def get_state(sender):
    if not db:
        return {"step": None, "data": {}}

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
    now = datetime.now()

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
        return

    if step == "first":
        data["first"] = text.title()
        set_state(sender, "last", data)
        await send_text(sender, "👤 Enter *Last Name*:")
        return

    if step == "last":
        data["last"] = text.title()
        set_state(sender, "department", data)
        await send_list(sender, "🏥 Select Department:", [
            {"id": d, "title": d} for d in DEPARTMENTS
        ])
        return

    if step == "department":
        data["department"] = msg["interactive"]["list_reply"]["id"]
        set_state(sender, "date", data)
        await send_text(sender, "📅 Enter date (YYYY-MM-DD):")
        return

    if step == "date":
        parsed = dateparser.parse(text)
        if not parsed or parsed.date() < now.date():
            await send_text(sender, "❌ Invalid date.")
            return

        data["date"] = parsed.strftime("%Y-%m-%d")
        start, end = doctorSchedule[data["department"]]
        slots = generate_slots(start, end)

        buttons = [{"id": s, "title": s} for s in slots[:3]]
        set_state(sender, "time", data)
        await send_buttons(sender, "⏰ Select Time:", buttons)
        return

    if step == "time":
        time = msg["interactive"]["button_reply"]["id"]
        pid = f"P{int(datetime.utcnow().timestamp())}"

        db.collection("patients").document(pid).set({
            "PatientID": pid,
            "FirstName": data["first"],
            "LastName": data["last"],
            "Department": data["department"],
            "RegistrationDate": data["date"],
            "RegistrationTime": time,
            "Phone": sender,
        })

        await send_text(sender, f"✅ Appointment Confirmed\n🆔 {pid}")
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
