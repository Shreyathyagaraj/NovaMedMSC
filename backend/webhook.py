import os, json, logging
from datetime import datetime, timedelta
from typing import List, Dict

import httpx, dateparser
from fastapi import APIRouter, Request, HTTPException

import firebase_admin
from firebase_admin import credentials, firestore

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

# ---------------- FIREBASE INIT ----------------
if not firebase_admin._apps:
    cred = credentials.Certificate(json.loads(os.getenv("FIREBASE_CREDENTIALS")))
    firebase_admin.initialize_app(cred)

db = firestore.client()
router = APIRouter()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WA_API = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"

# ---------------- DATA ----------------
DEPARTMENTS = [
    "Cardiology", "Neurology", "Orthopedics",
    "Pediatrics", "General Medicine", "Dermatology"
]

# ---------------- WHATSAPP HELPERS ----------------
async def wa_send(payload):
    async with httpx.AsyncClient() as c:
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
                    for b in buttons
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
                    "title": "Options",
                    "rows": [{"id": r, "title": r} for r in rows]
                }]
            }
        }
    })

# ---------------- STATE ----------------
def get_state(user):
    doc = db.collection("states").document(user).get()
    return doc.to_dict() if doc.exists else {}

def set_state(user, step, data):
    db.collection("states").document(user).set({
        "step": step,
        "data": data,
        "time": datetime.utcnow()
    })

def reset_state(user):
    db.collection("states").document(user).delete()

# ---------------- MENU ----------------
async def menu(user):
    await send_buttons(user, "🏥 *NovaMed*\nChoose:", ["Book Appointment", "Get Report"])
    set_state(user, "menu", {})

# ---------------- MAIN FLOW ----------------
async def process(user, text, msg):
    if text.lower() in ["hi", "hello", "menu", "restart"]:
        reset_state(user)
        await menu(user)
        return

    state = get_state(user)
    step = state.get("step")
    data = state.get("data", {})

    if step == "menu":
        if text == "Book Appointment":
            set_state(user, "name", {})
            await send_text(user, "👤 Enter patient name:")
        elif text == "Get Report":
            set_state(user, "report", {})
            await send_text(user, "🆔 Enter Patient ID:")
        return

    if step == "name":
        data["name"] = text
        set_state(user, "phone", data)
        await send_text(user, "📞 Enter phone number:")
        return

    if step == "phone":
        data["phone"] = text
        set_state(user, "department", data)
        await send_list(user, "🏥 Select Department:", DEPARTMENTS)
        return

    if step == "department":
        data["department"] = text
        set_state(user, "date", data)
        await send_text(user, "📅 Enter date (YYYY-MM-DD):")
        return

    if step == "date":
        data["date"] = text
        pid = f"P{int(datetime.utcnow().timestamp())}"

        db.collection("patients").document(pid).set({
            "PatientID": pid,
            "Name": data["name"],
            "Phone": data["phone"],
            "Department": data["department"],
            "RegistrationDate": data["date"]
        })

        await send_text(user, f"✅ Appointment Confirmed\n🆔 {pid}")
        await menu(user)
        reset_state(user)
        return

    if step == "report":
        doc = db.collection("patients").document(text).get()
        if not doc.exists:
            await send_text(user, "❌ Invalid Patient ID")
        else:
            p = doc.to_dict()
            await send_text(user,
                f"📄 *Report*\n"
                f"Name: {p['Name']}\n"
                f"Dept: {p['Department']}\n"
                f"Date: {p['RegistrationDate']}"
            )
        await menu(user)
        reset_state(user)

# ---------------- WEBHOOK ----------------
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

    text = msg.get("text", {}).get("body", "")
    if msg.get("interactive"):
        text = msg["interactive"]["button_reply"]["title"]

    await process(user, text, msg)
    return {"ok": True}
