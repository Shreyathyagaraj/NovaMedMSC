import os
import re
import logging
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

# Your own backend services (NO Dialogflow)
NLP_SUPPORT_URL = os.getenv("NLP_SUPPORT_URL")      # e.g. https://your-api/support
REPORT_PDF_URL = os.getenv("REPORT_PDF_URL")        # e.g. https://your-api/reports

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

async def send_document(to: str, url: str, filename="report.pdf"):
    await wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {"link": url, "filename": filename},
    })

# ---------------- UTIL ----------------
def normalize_phone(p: str):
    digits = re.sub(r"\D", "", p)
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) > 10:
        return "+" + digits
    return None

def generate_slots(start: str, end: str):
    slots = []
    t = datetime.strptime(start, "%H:%M")
    e = datetime.strptime(end, "%H:%M")
    while t < e:
        slots.append(t.strftime("%H:%M"))
        t += timedelta(minutes=30)
    return slots

# ---------------- STATE ----------------
STATE_TIMEOUT_MIN = 10

def get_state(sender: str):
    ref = db.collection("registration_states").document(sender)
    snap = ref.get()
    if not snap.exists:
        return {"step": None, "data": {}, "updatedAt": None}

    state = snap.to_dict()
    ts = state.get("updatedAt")
    if ts and datetime.utcnow() - ts.replace(tzinfo=None) > timedelta(minutes=STATE_TIMEOUT_MIN):
        ref.delete()
        return {"step": None, "data": {}, "updatedAt": None}
    return state

def set_state(sender: str, step: str, data: dict):
    db.collection("registration_states").document(sender).set({
        "step": step,
        "data": data,
        "updatedAt": firestore.SERVER_TIMESTAMP
    })

def reset_state(sender: str):
    db.collection("registration_states").document(sender).delete()

# ---------------- MENU ----------------
async def show_menu(sender: str):
    await send_buttons(sender, "🏥 *Welcome to NovaMed*\nChoose an option:", [
        {"id": "book", "title": "📅 Book Appointment"},
        {"id": "report", "title": "📄 Get Report"},
        {"id": "support", "title": "💬 Support"},
    ])
    set_state(sender, "menu", {})

# ---------------- MAIN FLOW ----------------
async def process_message(sender: str, text: str, msg: dict):
    text_l = text.lower().strip()
    state = get_state(sender)
    step = state.get("step")
    data = state.get("data", {})
    now = datetime.now()

    if text_l in ["hi", "hello", "menu", "restart", "0"]:
        reset_state(sender)
        await show_menu(sender)
        return

    if not step:
        await show_menu(sender)
        return

    # -------- MENU --------
    if step == "menu":
        bid = msg.get("interactive", {}).get("button_reply", {}).get("id")
        if bid == "book":
            set_state(sender, "first", {})
            await send_text(sender, "👤 Enter *First Name*:")
        elif bid == "report":
            set_state(sender, "report", {})
            await send_text(sender, "🆔 Enter *Patient ID* (e.g. P1012):")
        elif bid == "support":
            set_state(sender, "support", {})
            await send_text(sender, "💬 Ask your question. Type *menu* to exit.")
        return

    # -------- SUPPORT --------
    if step == "support":
        if not NLP_SUPPORT_URL:
            await send_text(sender, "⚠️ Support service not configured.")
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(NLP_SUPPORT_URL, json={"query": text})
                await send_text(sender, r.json().get("answer", "Please be more specific."))
        except Exception:
            await send_text(sender, "⚠️ Support is temporarily unavailable.")
        return

    # -------- REPORT --------
    if step == "report":
        pid = text.upper()
        doc = db.collection("patients").document(pid).get()
        if not doc.exists:
            await send_text(sender, "❌ Patient ID not found. Type *menu*.")
            return
        p = doc.to_dict()
        await send_text(
            sender,
            f"👤 *{p['FirstName']} {p['LastName']}*\n"
            f"🏥 Dept: {p['Department']}\n"
            f"📅 Date: {p['RegistrationDate']}\n"
            f"⏰ Time: {p['RegistrationTime']}"
        )
        if REPORT_PDF_URL:
            await send_document(sender, f"{REPORT_PDF_URL}/{pid}", f"{pid}.pdf")
        reset_state(sender)
        return

    # -------- BOOKING --------
    if step == "first":
        data["first"] = text.title()
        set_state(sender, "last", data)
        await send_text(sender, "👤 Enter *Last Name*:")
        return

    if step == "last":
        data["last"] = text.title()
        rows = [{"id": d, "title": d} for d in DEPARTMENTS]
        set_state(sender, "department", data)
        await send_list(sender, "🏥 Select Department:", rows)
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
            await send_text(sender, "❌ No slots available for this date.")
            reset_state(sender)
            return

        buttons = [{"id": s, "title": s} for s in available[:3]]
        set_state(sender, "time", data)
        await send_buttons(sender, f"⏰ Available slots ({len(available)} left):", buttons)
        return

    if step == "time":
        time = msg["interactive"]["button_reply"]["id"]
        appt_dt = datetime.strptime(f"{data['date']} {time}", "%Y-%m-%d %H:%M")
        if appt_dt < now:
            await send_text(sender, "❌ Past time not allowed.")
            return

        pid = f"P{int(datetime.utcnow().timestamp())}"
        db.collection("patients").document(pid).set({
            "PatientID": pid,
            "FirstName": data["first"],
            "LastName": data["last"],
            "Department": data["department"],
            "RegistrationDate": data["date"],
            "RegistrationTime": time,
            "Phone": sender,
            "ReminderAt": appt_dt - timedelta(minutes=10),
        })

        await send_text(
            sender,
            f"✅ *Appointment Confirmed!*\n"
            f"🆔 Patient ID: {pid}\n"
            f"📅 {data['date']} ⏰ {time}\n"
            f"Please arrive *5 minutes early*."
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
    logger.info("Webhook payload: %s", body)

    value = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
    if "messages" not in value:
        return {"status": "ignored"}

    msg = value["messages"][0]
    sender = msg["from"]

    text = ""
    if msg.get("text"):
        text = msg["text"]["body"]
    elif msg.get("interactive"):
        it = msg["interactive"]
        text = it.get("button_reply", {}).get("title", "") or \
               it.get("list_reply", {}).get("title", "")

    await process_message(sender, text, msg)
    return {"status": "ok"}
