import os, re, logging
from datetime import datetime, timedelta
from typing import List, Dict

import httpx
from fastapi import APIRouter, Request, HTTPException
from firebase_admin import firestore
import dateparser

from firebase_config import init_firebase

# ---------------- INIT ----------------
db = init_firebase()
router = APIRouter()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

# ---------------- CONFIG ----------------
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "shreyaWebhook123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
NLP_SUPPORT_URL = os.getenv("NLP_SUPPORT_URL", "")

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

doctorLimits = {
    "Cardiology": 10,
    "Neurology": 8,
    "Orthopedics": 6,
    "Pediatrics": 12,
    "General Medicine": 10,
    "Dermatology": 15,
}

DEPARTMENTS = list(doctorSchedule.keys())

# ---------------- HELPERS ----------------
async def wa_post(payload):
    async with httpx.AsyncClient() as client:
        await client.post(
            WA_API,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            json=payload,
        )

async def send_text(to, text):
    await wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    })

async def send_buttons(to, body, buttons):
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
            },
        },
    })

async def send_list(to, body, rows):
    await wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": "Select",
                "sections": [{"title": "Options", "rows": rows}],
            },
        },
    })

# ---------------- SLOT LOGIC ----------------
def generate_slots(start, end):
    slots = []
    t = datetime.strptime(start, "%H:%M")
    e = datetime.strptime(end, "%H:%M")
    while t < e:
        slots.append(t.strftime("%H:%M"))
        t += timedelta(minutes=30)
    return slots

def normalize_phone(p):
    digits = re.sub(r"\D", "", p)
    return "+91" + digits if len(digits) == 10 else None

# ---------------- STATE ----------------
def get_state(sender):
    doc = db.collection("registration_states").document(sender).get()
    return doc.to_dict() if doc.exists else {"step": None, "data": {}}

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
    await send_buttons(sender, "Welcome to *NovaMed* 🏥", [
        {"id": "book", "title": "Book Appointment"},
        {"id": "support", "title": "Support"},
    ])
    set_state(sender, "menu", {})

# ---------------- MAIN FLOW ----------------
async def process_message(sender, text, msg):
    state = get_state(sender)
    step = state["step"]
    data = state["data"]
    now = datetime.now()

    if text.lower() in ["hi", "menu", "restart"]:
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
            await send_text(sender, "Enter First Name:")
        elif bid == "support":
            set_state(sender, "support", {})
            await send_text(sender, "Ask your support question:")
        return

    if step == "support":
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(NLP_SUPPORT_URL, json={"query": text})
                await send_text(sender, r.json().get("answer", "Please clarify."))
        except:
            await send_text(sender, "Support is currently unavailable.")
        return

    if step == "first":
        data["first"] = text.title()
        set_state(sender, "last", data)
        await send_text(sender, "Enter Last Name:")
        return

    if step == "last":
        data["last"] = text.title()
        rows = [{"id": d, "title": d} for d in DEPARTMENTS]
        set_state(sender, "dept", data)
        await send_list(sender, "Select Department:", rows)
        return

    if step == "dept":
        data["department"] = msg["interactive"]["list_reply"]["id"]
        set_state(sender, "date", data)
        await send_text(sender, "Enter appointment date (YYYY-MM-DD):")
        return

    if step == "date":
        date = dateparser.parse(text)
        if not date or date.date() < now.date():
            await send_text(sender, "❌ Cannot book past dates.")
            return
        data["date"] = date.strftime("%Y-%m-%d")
        dept = data["department"]

        start, end = doctorSchedule[dept]
        slots = generate_slots(start, end)

        booked = db.collection("patients") \
            .where("Department", "==", dept) \
            .where("RegistrationDate", "==", data["date"]) \
            .stream()

        used = [p.to_dict()["RegistrationTime"] for p in booked]
        available = [s for s in slots if s not in used]

        if not available:
            await send_text(sender, "❌ No slots left.")
            reset_state(sender)
            return

        buttons = [{"id": s, "title": s} for s in available[:3]]
        set_state(sender, "time", data)
        await send_buttons(
            sender,
            f"Available slots ({len(available)} left):",
            buttons
        )
        return

    if step == "time":
        time = msg["interactive"]["button_reply"]["id"]
        appt_dt = datetime.strptime(
            f"{data['date']} {time}", "%Y-%m-%d %H:%M"
        )

        if appt_dt < now:
            await send_text(sender, "❌ Past time not allowed.")
            return

        pid = f"P{str(int(datetime.utcnow().timestamp()))[-4:]}"
        reminder_at = appt_dt - timedelta(minutes=10)

        db.collection("patients").document(pid).set({
            "PatientID": pid,
            "FirstName": data["first"],
            "LastName": data["last"],
            "Department": data["department"],
            "RegistrationDate": data["date"],
            "RegistrationTime": time,
            "Phone": sender,
            "ReminderAt": reminder_at,
        })

        await send_text(
            sender,
            f"✅ Appointment Confirmed!\n"
            f"Patient ID: {pid}\n"
            f"🕒 {time}\n"
            f"Please arrive 5 minutes early."
        )
        reset_state(sender)

# ---------------- WEBHOOK ----------------
@router.get("/webhook")
async def verify(request: Request):
    if request.query_params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(request.query_params.get("hub.challenge"))
    raise HTTPException(403)

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
        text = it.get("button_reply", {}).get("title", text)

    await process_message(sender, text, msg)
    return {"status": "ok"}
