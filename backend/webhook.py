# backend/webhook.py

import os
import re
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import httpx
from fastapi import APIRouter, Request, HTTPException
from firebase_admin import firestore
import dateparser

# ================= FIREBASE CONFIG ====================
from firebase_config import init_firebase
db = init_firebase()

router = APIRouter()
logger = logging.getLogger("webhook")
logging.basicConfig(level=logging.INFO)

# ================= ENV CONFIG ========================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "shreyaWebhook123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

NLP_SUPPORT_URL = os.getenv("NLP_SUPPORT_URL", "http://localhost:8000/nlp_support")
REPORT_PDF_URL = os.getenv("REPORT_PDF_URL", "")
REPORT_BASE_URL = os.getenv("REPORT_BASE_URL", "")

if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
    logger.warning("⚠️ WHATSAPP_TOKEN or PHONE_NUMBER_ID missing. Outgoing messages will fail.")
if not REPORT_PDF_URL:
    logger.warning("⚠️ REPORT_PDF_URL is not set. PDF sending might fail.")

# ================= DOCTOR SCHEDULES & LIMITS =================
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
    dept: {"times": (times[0], times[1]), "capacity": doctorLimits.get(dept, 5)}
    for dept, times in doctorSchedule.items()
}

# ================= WHATSAPP SEND FUNCTIONS ==================

async def send_whatsapp_text(to: str, text: str):
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        logger.error("WhatsApp credentials missing.")
        return

    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to.lstrip("+"),
        "type": "text",
        "text": {"body": text},
    }
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(url, json=payload, headers=headers)

async def send_whatsapp_buttons(to, body, buttons):
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to.lstrip("+"),
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
    }
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(url, json=payload, headers=headers)

async def send_whatsapp_document(to, document_url, filename="report.pdf"):
    if not document_url:
        return

    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to.lstrip("+"),
        "type": "document",
        "document": {"link": document_url, "filename": filename},
    }
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(url, json=payload, headers=headers)

# ================= HELPERS =================

def normalize_phone(text: str):
    s = re.sub(r"[^\d+]", "", text)
    if s.startswith("+"):
        return s
    if len(s) == 10:
        return "+91" + s
    if len(s) > 10:
        return "+" + s
    return None

def parse_date_time(text: str):
    parsed = dateparser.parse(text)
    if not parsed:
        return {"date": None, "time": None}
    return {"date": parsed.strftime("%Y-%m-%d"), "time": parsed.strftime("%H:%M")}

# ================= STATE MANAGEMENT =================

async def get_state(sender):
    doc = db.collection("registration_states").document(sender).get()
    return doc.to_dict() if doc.exists else {"step": None, "data": {}}

async def set_state(sender, state):
    db.collection("registration_states").document(sender).set(
        {**state, "updatedAt": firestore.SERVER_TIMESTAMP}
    )

async def reset_state(sender):
    db.collection("registration_states").document(sender).delete()

# ================= FIRESTORE TRANSACTION FIXED =================

def attempt_registration_tx(data: dict):
    slot_id = f"{data['department']}_{data['registrationDate']}_{data['registrationTime']}"
    slot_ref = db.collection("appointments").document(slot_id)
    counter_ref = db.collection("metadata").document("patient_counter")

    @firestore.transactional
    def register(tx):
        # Slot count
        slot_snap = tx.get(slot_ref)
        current_count = slot_snap.to_dict().get("count", 0) if slot_snap.exists else 0

        capacity = DEPARTMENT_SLOTS[data["department"]]["capacity"]
        if current_count >= capacity:
            raise ValueError("Slot is full.")

        # Patient ID
        counter_snap = tx.get(counter_ref)
        new_id = counter_snap.to_dict().get("count", 1000) + 1 if counter_snap.exists else 1001
        tx.set(counter_ref, {"count": new_id})

        pid = f"P{new_id}"

        # Write patient
        patient_ref = db.collection("patients").document(pid)
        tx.set(patient_ref, {
            "PatientID": pid,
            "FirstName": data["firstName"],
            "LastName": data["lastName"],
            "Gender": data["gender"],
            "Address": data["address"],
            "PhoneNumber": data["phoneNumber"],
            "Email": data["email"],
            "Department": data["department"],
            "RegistrationDate": data["registrationDate"],
            "RegistrationTime": data["registrationTime"],
            "createdAt": firestore.SERVER_TIMESTAMP,
        })

        # Update slot
        tx.set(slot_ref, {
            "count": current_count + 1,
            "department": data["department"],
            "date": data["registrationDate"],
            "time": data["registrationTime"],
        }, merge=True)

        return pid

    return register(db.transaction())

# ================= NLP SUPPORT =================

async def nlp_support_reply(query: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(NLP_SUPPORT_URL, json={"query": query})
            if res.status_code == 200:
                body = res.json()
                return body.get("answer") or body.get("reply") or res.text
            return "Support system unavailable now."
    except:
        return "Unable to contact support."

# ================= MAIN CHAT FLOW =================

async def process_incoming_message(sender: str, text: str, wa_message: dict):
    text_raw = text.strip()
    text = text_raw.lower()

    state = await get_state(sender)
    step, data = state.get("step"), state.get("data", {})

    # START
    if not step:
        if text in ["hi", "hello", "hey"]:
            await send_whatsapp_buttons(
                sender,
                "Welcome to NovaMed! Choose an option:",
                [
                    {"id": "opt_book", "title": "Book Appointment"},
                    {"id": "opt_report", "title": "Get Report"},
                    {"id": "opt_support", "title": "Support"},
                ],
            )
            await set_state(sender, {"step": "menu", "data": {}})
            return

        await send_whatsapp_text(sender, "Send *Hi* to start.")
        return

    # MENU
    if step == "menu":
        try:
            btn = wa_message["interactive"]["button_reply"]["id"]
        except:
            btn = None

        if btn == "opt_book" or text in ["book", "appointment"]:
            await send_whatsapp_text(sender, "Enter First Name:")
            await set_state(sender, {"step": "first_name", "data": {}})
            return

        if btn == "opt_report":
            await send_whatsapp_text(sender, "Enter your Patient ID:")
            await set_state(sender, {"step": "report_id", "data": {}})
            return

        if btn == "opt_support":
            await send_whatsapp_text(sender, "Support activated. Ask your question:")
            await set_state(sender, {"step": "support", "data": {}})
            return

        return

    # BOOKING FLOW
    if step == "first_name":
        data["firstName"] = text_raw.title()
        await set_state(sender, {"step": "last_name", "data": data})
        await send_whatsapp_text(sender, "Enter Last Name:")
        return

    if step == "last_name":
        data["lastName"] = text_raw.title()
        await set_state(sender, {"step": "gender", "data": data})
        await send_whatsapp_text(sender, "Enter Gender:")
        return

    if step == "gender":
        data["gender"] = text_raw.title()
        await set_state(sender, {"step": "address", "data": data})
        await send_whatsapp_text(sender, "Enter Address:")
        return

    if step == "address":
        data["address"] = text_raw
        await set_state(sender, {"step": "email", "data": data})
        await send_whatsapp_text(sender, "Enter Email (or type skip):")
        return

    if step == "email":
        if text != "skip":
            if re.match(r".+@.+\..+", text):
                data["email"] = text_raw
            else:
                await send_whatsapp_text(sender, "Invalid email. Try again:")
                return
        else:
            data["email"] = ""

        await set_state(sender, {"step": "phone", "data": data})
        await send_whatsapp_text(sender, "Enter Phone Number:")
        return

    if step == "phone":
        phone = normalize_phone(text_raw)
        if not phone:
            await send_whatsapp_text(sender, "Invalid phone. Try again:")
            return
        data["phoneNumber"] = phone

        msg = "Choose Department:\n"
        for i, d in enumerate(DEPARTMENT_SLOTS.keys(), start=1):
            msg += f"{i}. {d}\n"

        await set_state(sender, {"step": "department", "data": data})
        await send_whatsapp_text(sender, msg)
        return

    if step == "department":
        dept_list = list(DEPARTMENT_SLOTS.keys())
        if text.isdigit() and 1 <= int(text) <= len(dept_list):
            data["department"] = dept_list[int(text) - 1]
        else:
            await send_whatsapp_text(sender, "Invalid choice. Try again:")
            return

        await set_state(sender, {"step": "date", "data": data})
        await send_whatsapp_text(sender, "Enter preferred date (YYYY-MM-DD):")
        return

    if step == "date":
        parsed = parse_date_time(text_raw)
        if not parsed["date"]:
            await send_whatsapp_text(sender, "Invalid date. Try again:")
            return

        data["registrationDate"] = parsed["date"]

        start_h = int(DEPARTMENT_SLOTS[data["department"]]["times"][0][:2])
        end_h = int(DEPARTMENT_SLOTS[data["department"]]["times"][1][:2])

        times = [f"{h:02d}:00" for h in range(start_h, end_h + 1)]
        data["time_list"] = times

        msg = "Available time slots:\n"
        for i, t in enumerate(times, start=1):
            msg += f"{i}. {t}\n"

        await set_state(sender, {"step": "time", "data": data})
        await send_whatsapp_text(sender, msg)
        return

    if step == "time":
        times = data["time_list"]
        if not text.isdigit() or not (1 <= int(text) <= len(times)):
            await send_whatsapp_text(sender, "Invalid slot. Try again:")
            return

        data["registrationTime"] = times[int(text) - 1]

        try:
            pid = attempt_registration_tx(data)
            await send_whatsapp_text(
                sender,
                f"🎉 Appointment Confirmed!\nPatient ID: {pid}\nDepartment: {data['department']}\nDate: {data['registrationDate']}\nTime: {data['registrationTime']}",
            )
        except Exception as e:
            if "Slot is full" in str(e):
                await send_whatsapp_text(sender, "❌ Slot is full. Try another time.")
            else:
                await send_whatsapp_text(sender, "❌ Registration failed. Try later.")
        finally:
            await reset_state(sender)
        return

    # REPORT FLOW
    if step == "report_id":
        pid = text_raw.strip()
        if pid.isdigit():
            pid = "P" + pid

        doc = db.collection("patients").document(pid).get()
        if not doc.exists:
            await send_whatsapp_text(sender, "Invalid Patient ID.")
            await reset_state(sender)
            return

        p = doc.to_dict()
        summary = (
            f"Patient Report\n"
            f"Name: {p['FirstName']} {p['LastName']}\n"
            f"ID: {pid}\n"
            f"Department: {p['Department']}\n"
            f"Date: {p['RegistrationDate']}\n"
            f"Time: {p['RegistrationTime']}"
        )

        await send_whatsapp_text(sender, summary)

        if REPORT_BASE_URL:
            pdf_url = f"{REPORT_BASE_URL}/reports/{pid}"
            await send_whatsapp_document(sender, pdf_url, f"{pid}_report.pdf")
        else:
            await send_whatsapp_text(sender, "Report service not configured.")

        await reset_state(sender)
        return

    # SUPPORT FLOW
    if step == "support":
        reply = await nlp_support_reply(text_raw)
        await send_whatsapp_text(sender, reply)

        if text in ["exit", "bye", "quit"]:
            await reset_state(sender)
            await send_whatsapp_text(sender, "Support session ended.")
        else:
            await set_state(sender, {"step": "support", "data": {}})
        return

    # FALLBACK
    await send_whatsapp_text(sender, "Send 'hi' to start.")
    await reset_state(sender)

# ================= WEBHOOK ROUTES =================

@router.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return int(challenge)

    raise HTTPException(status_code=403, detail="Verification failed")

@router.post("/webhook")
async def receive_webhook(request: Request):
    body = await request.json()
    logger.info(f"Incoming webhook: {body}")

    try:
        entry = body["entry"][0]["changes"][0]["value"]
        messages = entry.get("messages", [])
        if not messages:
            return {"status": "ignored"}

        msg = messages[0]
        sender = msg["from"]

        text = ""
        if msg.get("text"):
            text = msg["text"]["body"]
        elif msg.get("interactive") and msg["interactive"].get("type") == "button_reply":
            text = msg["interactive"]["button_reply"]["title"]

        await process_incoming_message(sender, text, msg)
        return {"status": "ok"}

    except Exception as e:
        logger.exception("Error handling webhook: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
