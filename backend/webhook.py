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

NLP_SUPPORT_URL = os.getenv("NLP_SUPPORT_URL", "")
REPORT_PDF_URL = os.getenv("REPORT_PDF_URL", "")

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
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(WA_API, json=payload, headers=headers)

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
                "sections": [{"title": "Options", "rows": rows}],
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

# ---------------- STATE HELPERS ----------------
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

# ---------------- UTIL ----------------
def normalize_phone(p: str):
    digits = re.sub(r"\D", "", p)
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) > 10:
        return "+" + digits
    return None

# ---------------- MENU ----------------
async def show_menu(sender: str):
    await send_buttons(sender, "Welcome to *NovaMed* 🏥\nChoose an option:", [
        {"id": "book", "title": "Book Appointment"},
        {"id": "report", "title": "Get Report"},
        {"id": "support", "title": "Support"},
    ])
    set_state(sender, "menu", {})

# ---------------- MAIN LOGIC ----------------
async def process_message(sender: str, text: str, msg: dict):
    text_l = text.lower().strip()
    state = get_state(sender)
    step = state.get("step")
    data = state.get("data", {})

    # GLOBAL RETURN TO MENU
    if text_l in ["hi", "hello", "menu", "0", "restart"]:
        reset_state(sender)
        await show_menu(sender)
        return

    # START
    if not step:
        await show_menu(sender)
        return

    # MENU
    if step == "menu":
        bid = msg.get("interactive", {}).get("button_reply", {}).get("id")
        if bid == "book":
            await send_text(sender, "Enter First Name:")
            set_state(sender, "first_name", {})
        elif bid == "report":
            await send_text(sender, "Enter Patient ID (e.g. P1001):")
            set_state(sender, "report", {})
        elif bid == "support":
            await send_text(sender, "Support mode. Ask your question.\nType *menu* to exit.")
            set_state(sender, "support", {})
        return

    # SUPPORT
    if step == "support":
        if not NLP_SUPPORT_URL:
            await send_text(sender, "Support service not configured.")
            return
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(NLP_SUPPORT_URL, json={"query": text})
            await send_text(sender, r.json().get("answer", "Please be specific."))
        return

    # REPORT
    if step == "report":
        pid = text.upper()
        doc = db.collection("patients").document(pid).get()
        if not doc.exists:
            await send_text(sender, "Patient not found. Type *menu*.")
            return
        p = doc.to_dict()
        await send_text(sender,
            f"Patient: {p.get('FirstName')} {p.get('LastName')}\n"
            f"Dept: {p.get('Department')}\n"
            f"Date: {p.get('RegistrationDate')}\n"
            f"Time: {p.get('RegistrationTime')}"
        )
        if REPORT_PDF_URL:
            await send_document(sender, f"{REPORT_PDF_URL}/reports/{pid}", f"{pid}.pdf")
        reset_state(sender)
        return

    # BOOKING FLOW
    if step == "first_name":
        data["first"] = text.title()
        set_state(sender, "last_name", data)
        await send_text(sender, "Enter Last Name:")
        return

    if step == "last_name":
        data["last"] = text.title()
        set_state(sender, "gender", data)
        await send_buttons(sender, "Select Gender:", [
            {"id": "Male", "title": "Male"},
            {"id": "Female", "title": "Female"},
            {"id": "Other", "title": "Other"},
        ])
        return

    if step == "gender":
        data["gender"] = msg["interactive"]["button_reply"]["id"]
        set_state(sender, "phone", data)
        await send_text(sender, "Enter Phone Number:")
        return

    if step == "phone":
        phone = normalize_phone(text)
        if not phone:
            await send_text(sender, "Invalid phone number.")
            return
        data["phone"] = phone
        rows = [{"id": d, "title": d} for d in DEPARTMENTS]
        await send_list(sender, "Select Department:", rows)
        set_state(sender, "department", data)
        return

    if step == "department":
        data["department"] = msg["interactive"]["list_reply"]["id"]
        await send_text(sender, "Enter appointment date (YYYY-MM-DD):")
        set_state(sender, "date", data)
        return

    if step == "date":
        parsed = dateparser.parse(text)
        if not parsed:
            await send_text(sender, "Invalid date.")
            return
        data["date"] = parsed.strftime("%Y-%m-%d")
        await send_text(sender, "Enter appointment time (HH:MM):")
        set_state(sender, "time", data)
        return

    if step == "time":
        data["time"] = text
        await send_text(sender, "✅ Appointment booked successfully!")
        reset_state(sender)
        return

# ---------------- WEBHOOK ----------------
@router.get("/webhook")
async def verify(request: Request):
    if request.query_params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(request.query_params.get("hub.challenge"))
    raise HTTPException(status_code=403)

@router.post("/webhook")
async def receive(request: Request):
    body = await request.json()
    logger.info("Webhook: %s", body)

    value = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})

    # ✅ CRITICAL FIX
    if "messages" not in value:
        return {"status": "ignored"}

    msg = value["messages"][0]
    sender = msg["from"]

    text = ""
    if msg.get("text"):
        text = msg["text"]["body"]
    elif msg.get("interactive"):
        it = msg["interactive"]
        if it["type"] == "button_reply":
            text = it["button_reply"]["title"]
        elif it["type"] == "list_reply":
            text = it["list_reply"]["title"]

    await process_message(sender, text, msg)
    return {"status": "ok"}
