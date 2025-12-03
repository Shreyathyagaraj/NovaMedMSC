# backend/webhook.py

import os
import re
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import httpx
from fastapi import APIRouter, Request, HTTPException
from firebase_admin import credentials, firestore, initialize_app, _apps
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
FIREBASE_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "serviceAccountKey.json")
OTP_EXPIRY_SECONDS = int(os.getenv("OTP_EXPIRY_SECONDS", "300"))
SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "30"))

if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
    logger.warning("⚠️ WHATSAPP_TOKEN or PHONE_NUMBER_ID missing. Outgoing messages will fail.")

# ================= FIREBASE INIT ======================
if not _apps:
    try:
        cred = credentials.Certificate(FIREBASE_CREDENTIALS)
        initialize_app(cred)
        logger.info("Firebase initialized.")
    except Exception as e:
        logger.exception("Firebase init failed: %s", e)

db = firestore.client()

# ================= DEPARTMENTS ========================
DEPARTMENT_SLOTS = {
    "Cardiology": {"times": ("09:00", "12:00"), "capacity": 10},
    "Neurology": {"times": ("14:00", "17:00"), "capacity": 8},
    "Orthopedics": {"times": ("10:00", "13:00"), "capacity": 6},
    "Pediatrics": {"times": ("15:00", "18:00"), "capacity": 12},
    "General Medicine": {"times": ("09:00", "12:00"), "capacity": 10},
    "Dermatology": {"times": ("09:00", "18:00"), "capacity": 15},
}

# ================= UTILITIES ==========================
async def send_whatsapp_text(to: str, text: str):
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        raise RuntimeError("WhatsApp credentials missing.")

    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to.lstrip("+"),
        "type": "text",
        "text": {"body": text},
    }
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, json=payload, headers=headers)
        return r.json()


async def send_whatsapp_buttons(to: str, body: str, buttons: list):
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to.lstrip("+"),
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                for b in buttons
            ]}
        },
    }
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, json=payload, headers=headers)
        return r.json()


def normalize_phone(text: str):
    s = re.sub(r"[^\d+]", "", text)
    if s.startswith("+"):
        return s
    if len(s) == 10:
        return "+91" + s
    if len(s) >= 11:
        return "+" + s
    return None


def parse_date_time(text: str):
    parsed = dateparser.parse(text)
    if not parsed:
        return {"date": None, "time": None}

    return {
        "date": parsed.strftime("%Y-%m-%d"),
        "time": parsed.strftime("%H:%M")
    }


# ========== STATE HELPERS ============
async def get_state(sender: str):
    ref = db.collection("registration_states").document(sender)
    doc = ref.get()
    if not doc.exists:
        return {"step": None, "data": {}}
    return doc.to_dict()


async def set_state(sender: str, state: dict):
    db.collection("registration_states").document(sender).set(
        {**state, "updatedAt": firestore.SERVER_TIMESTAMP}
    )


async def reset_state(sender: str):
    db.collection("registration_states").document(sender).delete()


# ========== APPOINTMENT REGISTRATION ==============
def generate_patient_id_tx(tx):
    ref = db.collection("metadata").document("patient_counter")
    snap = tx.get(ref)

    if snap.exists:
        new = snap.to_dict().get("count", 1000) + 1
    else:
        new = 1001

    tx.set(ref, {"count": new}, merge=True)
    return f"P{new}"


def attempt_registration_tx(data: dict):
    slot_id = f"{data['department']}_{data['registrationDate']}_{data['registrationTime']}"
    slot_ref = db.collection("appointments").document(slot_id)

    def fn(tx):
        snap = tx.get(slot_ref)
        counted = snap.to_dict().get("count", 0) if snap.exists else 0

        capacity = DEPARTMENT_SLOTS[data["department"]]["capacity"]
        if counted >= capacity:
            raise ValueError("Slot is full.")

        pid = generate_patient_id_tx(tx)
        patient_ref = db.collection("patients").document(pid)

        tx.set(patient_ref, {
            "PatientID": pid,
            "FirstName": data["firstName"],
            "LastName": data["lastName"],
            "PhoneNumber": data["phoneNumber"],
            "Email": data["email"],
            "Department": data["department"],
            "RegistrationDate": data["registrationDate"],
            "RegistrationTime": data["registrationTime"],
            "createdAt": firestore.SERVER_TIMESTAMP,
        })

        tx.set(slot_ref, {
            "department": data["department"],
            "date": data["registrationDate"],
            "time": data["registrationTime"],
            "count": counted + 1,
        }, merge=True)

        return pid

    return db.run_transaction(fn)


# ================= MESSAGE PROCESSOR ====================
async def process_incoming_message(sender: str, text: str, wa_message: dict):
    text = text.strip().lower()

    state = await get_state(sender)
    step = state.get("step")
    data = state.get("data", {})

    # ==== NEW SESSION ====
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

    # ==== MENU ====
    if step == "menu":
        button_id = None
        try:
            button_id = wa_message["interactive"]["button_reply"]["id"]
        except:
            pass

        if button_id == "opt_book":
            await send_whatsapp_text(sender, "Enter your Full Name:")
            await set_state(sender, {"step": "first_name", "data": {}})
            return

        await send_whatsapp_buttons(sender, "Choose:", [
            {"id": "opt_book", "title": "Book Appointment"},
        ])
        return

    # ==== FIRST NAME ====
    if step == "first_name":
        data["firstName"] = text.title()
        await set_state(sender, {"step": "last_name", "data": data})
        await send_whatsapp_text(sender, "Enter Last Name:")
        return

    # ==== LAST NAME ====
    if step == "last_name":
        data["lastName"] = text.title()
        await set_state(sender, {"step": "phone", "data": data})
        await send_whatsapp_text(sender, "Enter Phone Number:")
        return

    # ==== PHONE ====
    if step == "phone":
        phone = normalize_phone(text)
        if not phone:
            await send_whatsapp_text(sender, "Invalid phone. Try again.")
            return
        data["phoneNumber"] = phone
        await set_state(sender, {"step": "email", "data": data})
        await send_whatsapp_text(sender, "Enter Email (or type skip):")
        return

    # ==== EMAIL ====
    if step == "email":
        if text != "skip":
            if not re.match(r".+@.+\..+", text):
                await send_whatsapp_text(sender, "Invalid email.")
                return
            data["email"] = text
        else:
            data["email"] = ""

        # Ask department
        msg = "Choose Department:\n"
        for i, d in enumerate(DEPARTMENT_SLOTS.keys(), start=1):
            msg += f"{i}. {d}\n"

        await set_state(sender, {"step": "department", "data": data})
        await send_whatsapp_text(sender, msg)
        return

    # ==== DEPARTMENT ====
    if step == "department":
        dept_list = list(DEPARTMENT_SLOTS.keys())

        if text.isdigit() and 1 <= int(text) <= len(dept_list):
            data["department"] = dept_list[int(text)-1]
        else:
            await send_whatsapp_text(sender, "Invalid choice. Send number only.")
            return

        await set_state(sender, {"step": "date", "data": data})
        await send_whatsapp_text(sender, "Enter preferred date (e.g., 2025-12-10):")
        return

    # ==== DATE ====
    if step == "date":
        parsed = parse_date_time(text)
        if not parsed["date"]:
            await send_whatsapp_text(sender, "Invalid date.")
            return

        data["registrationDate"] = parsed["date"]

        dept_cfg = DEPARTMENT_SLOTS[data["department"]]
        start_h = int(dept_cfg["times"][0][:2])
        end_h = int(dept_cfg["times"][1][:2])

        msg = "Available time slots:\n"
        times = []
        for h in range(start_h, end_h + 1):
            t = f"{h:02d}:00"
            times.append(t)
            msg += f"{len(times)}. {t}\n"

        data["time_list"] = times
        await set_state(sender, {"step": "time", "data": data})
        await send_whatsapp_text(sender, msg)
        return

    # ==== TIME ====
    if step == "time":
        times = data["time_list"]
        if text.isdigit() and 1 <= int(text) <= len(times):
            selected = times[int(text)-1]
        else:
            return await send_whatsapp_text(sender, "Send a number from the list.")

        data["registrationTime"] = selected

        otp = secrets.randbelow(900000) + 100000
        data["otp"] = str(otp)
        data["otp_created"] = datetime.utcnow().isoformat()

        await set_state(sender, {"step": "otp", "data": data})
        await send_whatsapp_text(sender, f"Your OTP is: *{otp}*")
        return

    # ==== OTP ====
    if step == "otp":
        if text == data["otp"]:
            pid = attempt_registration_tx({
                "firstName": data["firstName"],
                "lastName": data["lastName"],
                "phoneNumber": data["phoneNumber"],
                "email": data["email"],
                "department": data["department"],
                "registrationDate": data["registrationDate"],
                "registrationTime": data["registrationTime"],
            })

            await send_whatsapp_text(sender, f"🎉 Appointment booked!\nPatient ID: {pid}")
            await reset_state(sender)
            return

        return await send_whatsapp_text(sender, "Wrong OTP. Try again.")

    # ==== DEFAULT ====
    await send_whatsapp_text(sender, "Send 'hi' to start.")
    await reset_state(sender)
    return


# ================== FASTAPI WEBHOOK ENDPOINTS =========================

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
        text = msg["text"]["body"] if msg.get("text") else ""

        await process_incoming_message(sender, text, msg)

        return {"status": "ok"}

    except Exception as e:
        logger.exception("Error handling webhook: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
