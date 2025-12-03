# backend/webhook.py
import os
import re
import secrets
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import httpx
from fastapi import APIRouter, Request, HTTPException
from firebase_admin import credentials, firestore, initialize_app, _apps
import dateparser

router = APIRouter()
logger = logging.getLogger("webhook")
logging.basicConfig(level=logging.INFO)

# ========= Environment / config =========
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "shreyaWebhook123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")  # Bearer token
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")  # Meta phone number id
FIREBASE_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "serviceAccountKey.json")
OTP_EXPIRY_SECONDS = int(os.getenv("OTP_EXPIRY_SECONDS", "300"))  # 5 minutes
SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "30"))

if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
    logger.warning("WHATSAPP_TOKEN or PHONE_NUMBER_ID not set. Outgoing WhatsApp will fail until set.")

# ========= Firebase init =========
if not _apps:
    try:
        cred = credentials.Certificate(FIREBASE_CREDENTIALS)
        initialize_app(cred)
        logger.info("Initialized Firebase")
    except Exception as e:
        logger.exception("Firebase init failed: %s", e)

db = firestore.client()

# ========= Departments and limits =========
DEPARTMENT_SLOTS = {
    "Cardiology": {"times": ("09:00", "12:00"), "capacity": 10},
    "Neurology": {"times": ("14:00", "17:00"), "capacity": 8},
    "Orthopedics": {"times": ("10:00", "13:00"), "capacity": 6},
    "Pediatrics": {"times": ("15:00", "18:00"), "capacity": 12},
    "General Medicine": {"times": ("09:00", "12:00"), "capacity": 10},
    "Dermatology": {"times": ("09:00", "18:00"), "capacity": 15},
}

# ========= Utilities =========
async def send_whatsapp_text(to: str, text: str) -> dict:
    """
    Send a simple text message via WhatsApp Cloud API.
    to: e.g. '919876543210' or '+919876543210'
    """
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        raise RuntimeError("WhatsApp credentials not configured")

    recipient = to if to.startswith("+") else ("+" + to)
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient.lstrip("+"),
        "type": "text",
        "text": {"body": text},
    }
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, json=payload, headers=headers)
        logger.info("WhatsApp send response %s", r.text)
        return r.json()


async def send_whatsapp_buttons(to: str, body_text: str, buttons: list) -> dict:
    """
    Send interactive reply buttons.
    buttons: list of dicts [ {"id": "opt_book", "title":"Book Appointment"}, ... ]
    """
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        raise RuntimeError("WhatsApp credentials not configured")
    recipient = to if to.startswith("+") else ("+" + to)
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    interactive = {
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": [{"type": "reply", "reply": {"id": b["id"], "title": b["title"]}} for b in buttons]},
        },
    }
    payload = {"messaging_product": "whatsapp", "to": recipient.lstrip("+"), **interactive}
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, json=payload, headers=headers)
        logger.info("WhatsApp interactive response: %s", r.text)
        return r.json()


def normalize_phone(text: str) -> Optional[str]:
    if not text:
        return None
    s = re.sub(r"[^\d\+]", "", text)
    # If it starts without + and length 10, assume +91
    if s.startswith("+"):
        return s
    if len(s) == 10:
        return "+91" + s
    if len(s) >= 11:
        return "+" + s
    return None


def parse_date_time(text: str) -> Dict[str, Optional[str]]:
    """
    Try to parse date/time using dateparser
    Returns {'date': 'YYYY-MM-DD' or None, 'time': 'HH:MM' or None}
    """
    if not text:
        return {"date": None, "time": None}
    settings = {"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False}
    parsed = dateparser.parse(text, settings=settings)
    if not parsed:
        return {"date": None, "time": None}
    date_str = parsed.strftime("%Y-%m-%d")
    time_str = parsed.strftime("%H:%M")
    return {"date": date_str, "time": time_str}


def phone_to_docid(phone: str) -> str:
    # canonical doc id for state
    p = phone.lstrip("+")
    return p


# ========= Firestore state helpers =========
async def get_state(sender: str) -> dict:
    doc = db.collection("registration_states").document(phone_to_docid(sender)).get()
    if not doc.exists:
        return {"step": None, "data": {}, "updatedAt": None}
    d = doc.to_dict()
    # expiry check
    if d.get("updatedAt"):
        ts = d["updatedAt"]
        if isinstance(ts, firestore.SERVER_TIMESTAMP.__class__):
            # fallback — keep
            pass
        try:
            updated = ts.to_datetime()  # pyre-firestore timestamp -> datetime
        except Exception:
            updated = datetime.utcnow()
        if datetime.utcnow() - updated > timedelta(minutes=SESSION_TTL_MINUTES):
            # reset
            db.collection("registration_states").document(phone_to_docid(sender)).delete()
            return {"step": None, "data": {}, "updatedAt": None}
    return d


async def set_state(sender: str, state: dict):
    db.collection("registration_states").document(phone_to_docid(sender)).set({**state, "updatedAt": firestore.SERVER_TIMESTAMP})


async def reset_state(sender: str):
    db.collection("registration_states").document(phone_to_docid(sender)).delete()


# ========= Patient ID generation (transaction-safe) =========
def generate_patient_id_transaction(tx) -> str:
    counter_ref = db.collection("metadata").document("patient_counter")
    snap = tx.get(counter_ref)
    if snap.exists:
        cur = snap.to_dict().get("count", 1000) + 1
    else:
        cur = 1001
    tx.set(counter_ref, {"count": cur}, merge=True)
    return f"P{cur}"


def attempt_registration_tx(data: dict) -> str:
    """
    Performs Firestore transaction to reserve slot and create patient doc.
    Input data keys: firstName, lastName, phoneNumber (+country), email, department, registrationDate, registrationTime
    """
    slot_id = f"{data['department']}_{data['registrationDate']}_{data['registrationTime']}"
    slot_ref = db.collection("appointments").document(slot_id)
    patient_ref_template = db.collection("patients")
    def transaction_function(tx):
        slot_snap = tx.get(slot_ref)
        current_count = slot_snap.to_dict().get("count", 0) if slot_snap.exists else 0
        capacity = DEPARTMENT_SLOTS.get(data["department"], {}).get("capacity", 10)
        if current_count >= capacity:
            raise ValueError("Slot full")
        pid = generate_patient_id_transaction(tx)
        patient_ref = db.collection("patients").document(pid)
        tx.set(patient_ref, {
            "PatientID": pid,
            "FirstName": data.get("firstName", ""),
            "LastName": data.get("lastName", ""),
            "PhoneNumber": data.get("phoneNumber"),
            "Email": data.get("email", ""),
            "Department": data.get("department"),
            "RegistrationDate": data.get("registrationDate"),
            "RegistrationTime": data.get("registrationTime"),
            "createdAt": firestore.SERVER_TIMESTAMP,
        })
        new_count = current_count + 1
        new_patients = (slot_snap.to_dict().get("patients", []) if slot_snap.exists else []) + [pid]
        tx.set(slot_ref, {
            "department": data["department"],
            "date": data["registrationDate"],
            "time": data["registrationTime"],
            "capacity": capacity,
            "count": new_count,
            "patients": new_patients,
        }, merge=True)
        return pid
    pid = db.run_transaction(transaction_function)
    return pid


# ========= NLP helpers =========
def extract_name(text: str) -> Optional[str]:
    # simple heuristics
    m = re.search(r"\bmy name is\s+([A-Za-z ]{2,50})", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"^([A-Z][a-z]{1,20}(?:\s[A-Z][a-z]{1,20})?)$", text.strip())
    if m:
        return m.group(1).strip()
    return None


def extract_email(text: str) -> Optional[str]:
    m = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,})", text)
    return m.group(1) if m else None


def extract_phone_from_text(text: str) -> Optional[str]:
    return normalize_phone(re.sub(r"[^\d\+]", "", text)) if re.search(r"\d", text) else None


def is_greeting(text: str) -> bool:
    return bool(re.search(r"\b(hi|hello|hey|hii)\b", text, re.IGNORECASE))


# ========= Primary conversation processing =========
async def process_incoming_message(sender: str, text: str, wa_message: dict):
    """
    Entry point for inbound WhatsApp messages.
    sender: number in international (example: 9199xxxx)
    text: message text
    wa_message: original message payload (keeps buttons/interactive data)
    """
    logger.info("Processing message from %s : %s", sender, text)
    state = await get_state(sender)

    # If interactive button reply arrives, handle
    # For Cloud API, button replies appear as message.type == "button" or as "interactive" objects in payload
    interactive_reply_id = None
    try:
        # attempt to extract button reply id from wa_message
        interactive = wa_message.get("interactive") or wa_message.get("button")
        if interactive:
            # different shapes depending on message type
            if "button_reply" in interactive:
                interactive_reply_id = interactive["button_reply"].get("id")
            elif "type" in wa_message and wa_message["type"] == "interactive":
                # fallback
                pass
            elif "button" in wa_message:
                interactive_reply_id = wa_message["button"].get("payload") or wa_message["button"].get("text")
    except Exception:
        interactive_reply_id = None

    # New / no active session -> send menu or handle greetings
    if not state or not state.get("step"):
        if is_greeting(text):
            # send interactive menu buttons
            buttons = [
                {"id": "opt_book", "title": "Book Appointment"},
                {"id": "opt_report", "title": "Get Report"},
                {"id": "opt_support", "title": "Talk to Support"},
            ]
            await send_whatsapp_buttons(sender, "Welcome to NovaMed — choose an option:", buttons)
            await set_state(sender, {"step": "menu", "data": {}})
            return

        # user may have typed a one-line registration request
        if "register" in text.lower() or "appointment" in text.lower():
            # jump to appointment flow
            await send_whatsapp_text(sender, "Sure — let's book an appointment. What's your *Full Name*?")
            await set_state(sender, {"step": "appt_firstname", "data": {}})
            return

        # if they sent text that maps to one of the simple keywords -> show menu
        await send_whatsapp_buttons(sender, "Welcome to NovaMed — choose an option:", [
            {"id": "opt_book", "title": "Book Appointment"},
            {"id": "opt_report", "title": "Get Report"},
            {"id": "opt_support", "title": "Talk to Support"},
        ])
        await set_state(sender, {"step": "menu", "data": {}})
        return

    # If we are at menu step and they clicked a button
    if state.get("step") == "menu":
        # if button reply: interactive_reply_id will be set
        if interactive_reply_id:
            if interactive_reply_id == "opt_book":
                await send_whatsapp_text(sender, "Great — we'll book an appointment. What's your *Full Name*?")
                await set_state(sender, {"step": "appt_firstname", "data": {}})
                return
            if interactive_reply_id == "opt_report":
                await send_whatsapp_text(sender, "Please send your Patient ID to download your report.")
                await set_state(sender, {"step": "report_wait_pid", "data": {}})
                return
            if interactive_reply_id == "opt_support":
                await send_whatsapp_text(sender, "You can call our support at +91-XXXXXXXXXX or type your query here.")
                await reset_state(sender)
                return
        # otherwise user may have typed "1" or "book"
        if text.strip().isdigit():
            n = int(text.strip())
            mapping = {1: "opt_book", 2: "opt_report", 3: "opt_support"}
            choice = mapping.get(n)
            if choice == "opt_book":
                await send_whatsapp_text(sender, "Great — let's book. What's your *Full Name*?")
                await set_state(sender, {"step": "appt_firstname", "data": {}})
                return
            if choice == "opt_report":
                await send_whatsapp_text(sender, "Please send your Patient ID to download your report.")
                await set_state(sender, {"step": "report_wait_pid", "data": {}})
                return
            if choice == "opt_support":
                await send_whatsapp_text(sender, "You can call our support at +91-XXXXXXXXXX or type your query here.")
                await reset_state(sender)
                return
        # fallback: re-send menu
        await send_whatsapp_buttons(sender, "Please choose an option:", [
            {"id": "opt_book", "title": "Book Appointment"},
            {"id": "opt_report", "title": "Get Report"},
            {"id": "opt_support", "title": "Talk to Support"},
        ])
        return

    # ========== Appointment flow handlers ==========
    step = state.get("step")
    data = state.get("data", {})

    # Basic flow states:
    # appt_firstname -> appt_lastname -> appt_phone -> appt_email -> appt_department -> appt_date -> appt_time -> otp_sent -> otp_verified -> confirmation
    if step == "appt_firstname":
        name = text.strip()
        data["firstName"] = name
        await set_state(sender, {"step": "appt_lastname", "data": data})
        await send_whatsapp_text(sender, "Thanks. What's your *Last Name*? (type '-' if none)")
        return

    if step == "appt_lastname":
        data["lastName"] = "" if text.strip() == "-" else text.strip()
        await set_state(sender, {"step": "appt_phone", "data": data})
        await send_whatsapp_text(sender, "Please enter your mobile number (include country code or 10-digit).")
        return

    if step == "appt_phone":
        p = normalize_phone(text.strip())
        if not p:
            await send_whatsapp_text(sender, "Phone not recognised. Please enter a valid phone number (e.g., +919876543210 or 9876543210).")
            return
        data["phoneNumber"] = p
        await set_state(sender, {"step": "appt_email", "data": data})
        await send_whatsapp_text(sender, "Optional: enter your email (or type 'skip').")
        return

    if step == "appt_email":
        if text.strip().lower() != "skip":
            e = extract_email(text.strip())
            if not e:
                await send_whatsapp_text(sender, "Email not valid. Enter a valid email or type 'skip'.")
                return
            data["email"] = e
        else:
            data["email"] = ""
        # ask department
        dept_list = list(DEPARTMENT_SLOTS.keys())
        msg = "Which department?\n"
        for i, d in enumerate(dept_list, start=1):
            msg += f"{i}. {d}\n"
        await set_state(sender, {"step": "appt_department", "data": data})
        await send_whatsapp_text(sender, msg)
        return

    if step == "appt_department":
        # accept number or name
        dept_list = list(DEPARTMENT_SLOTS.keys())
        dept_choice = None
        if text.strip().isdigit():
            idx = int(text.strip()) - 1
            if 0 <= idx < len(dept_list):
                dept_choice = dept_list[idx]
        else:
            # try to fuzzy match
            for d in dept_list:
                if d.lower() in text.lower():
                    dept_choice = d
                    break
        if not dept_choice:
            await send_whatsapp_text(sender, "Department not recognised. Please send the number or department name.")
            return
        data["department"] = dept_choice
        await set_state(sender, {"step": "appt_date", "data": data})
        await send_whatsapp_text(sender, "Please enter the preferred date (e.g., 'tomorrow', '2025-12-10').")
        return

    if step == "appt_date":
        parsed = parse_date_time(text.strip())
        if not parsed["date"]:
            await send_whatsapp_text(sender, "Couldn't parse date. Send a date like '2025-12-10' or 'tomorrow'.")
            return
        # block past dates
        if parsed["date"] <= datetime.utcnow().strftime("%Y-%m-%d"):
            await send_whatsapp_text(sender, "Please pick a future date.")
            return
        data["registrationDate"] = parsed["date"]
        # show available time options for that department
        times = []
        dept_cfg = DEPARTMENT_SLOTS.get(data["department"])
        start_hh = int(dept_cfg["times"][0].split(":")[0])
        end_hh = int(dept_cfg["times"][1].split(":")[0])
        for hh in range(start_hh, end_hh + 1):
            times.append(f"{hh:02d}:00")
        # compute remaining for each time slot
        msg = f"Available times for {data['department']} on {data['registrationDate']}:\n"
        for i, t in enumerate(times, start=1):
            slot_id = f"{data['department']}_{data['registrationDate']}_{t}"
            slot_snap = db.collection("appointments").document(slot_id).get()
            count = slot_snap.to_dict().get("count", 0) if slot_snap.exists else 0
            capacity = DEPARTMENT_SLOTS.get(data["department"], {}).get("capacity", 10)
            remaining = capacity - count
            msg += f"{i}. {t} (Remaining: {remaining})\n"
        msg += "Reply with the number or the time (e.g., 10:00)."
        await set_state(sender, {"step": "appt_time", "data": data})
        await send_whatsapp_text(sender, msg)
        return

    if step == "appt_time":
        dept_cfg = DEPARTMENT_SLOTS.get(data["department"])
        start_hh = int(dept_cfg["times"][0].split(":")[0])
        end_hh = int(dept_cfg["times"][1].split(":")[0])
        times = [f"{hh:02d}:00" for hh in range(start_hh, end_hh + 1)]
        selected_time = None
        if text.strip().isdigit():
            idx = int(text.strip()) - 1
            if 0 <= idx < len(times):
                selected_time = times[idx]
        else:
            # parse potential hour/time
            parsed = parse_date_time(text.strip())
            if parsed["time"]:
                hhmm = parsed["time"]
                if hhmm in times:
                    selected_time = hhmm
            else:
                candidate = text.strip()
                if re.match(r"^\d{1,2}$", candidate):
                    candidate = candidate.zfill(2) + ":00"
                if candidate in times:
                    selected_time = candidate
        if not selected_time:
            await send_whatsapp_text(sender, "Couldn't recognise that time. Reply with the time or option number.")
            return
        data["registrationTime"] = selected_time
        # Before finalizing, send OTP
        otp = secrets.randbelow(900000) + 100000
        data["otp"] = str(otp)
        data["otp_created"] = datetime.utcnow().isoformat()
        await set_state(sender, {"step": "appt_otp_sent", "data": data})
        await send_whatsapp_text(sender, f"A verification OTP has been sent to {data['phoneNumber']}. Please reply with the OTP. (OTP: {otp})")
        # NOTE: For production, send OTP via SMS/WhatsApp; here we simply echo in message for demo/test
        return

    if step == "appt_otp_sent":
        candidate = text.strip()
        if candidate == data.get("otp"):
            # check expiry
            created = datetime.fromisoformat(data.get("otp_created"))
            if datetime.utcnow() - created > timedelta(seconds=OTP_EXPIRY_SECONDS):
                await send_whatsapp_text(sender, "OTP expired. We sent a new one. Reply when ready.")
                # resend OTP
                otp = secrets.randbelow(900000) + 100000
                data["otp"] = str(otp)
                data["otp_created"] = datetime.utcnow().isoformat()
                await set_state(sender, {"step": "appt_otp_sent", "data": data})
                await send_whatsapp_text(sender, f"New OTP: {otp}")
                return
            # finalize booking (transaction)
            try:
                pid = attempt_registration_tx({
                    "firstName": data["firstName"],
                    "lastName": data.get("lastName", ""),
                    "phoneNumber": data["phoneNumber"],
                    "email": data.get("email", ""),
                    "department": data["department"],
                    "registrationDate": data["registrationDate"],
                    "registrationTime": data["registrationTime"],
                })
                await send_whatsapp_text(sender, f"✅ Registration complete! Patient ID: {pid}\nDept: {data['department']}\nDate: {data['registrationDate']}\nTime: {data['registrationTime']}")
                await reset_state(sender)
                return
            except Exception as e:
                logger.exception("Registration transaction failed: %s", e)
                await send_whatsapp_text(sender, f"Failed to book the slot: {e}. Please try another time.")
                # back to time selection
                await set_state(sender, {"step": "appt_date", "data": data})
                await send_whatsapp_text(sender, "Please send a different date.")
                return
        else:
            await send_whatsapp_text(sender, "OTP did not match. Please retry.")
            return

    # ========= Report flow =========
    if step == "report_wait_pid":
        pid = text.strip()
        doc = db.collection("patients").document(pid).get()
        if not doc.exists:
            await send_whatsapp_text(sender, "Patient ID not found. Please check and send again.")
            return
        # For demo, return a placeholder link. In reality you'd produce an authenticated download link.
        await send_whatsapp_text(sender, f"Report for {pid}: https://example.com/reports/{pid}.pdf")
        await reset_state(sender)
        return

    # default fallback
    await send_whatsapp_text(sender, "Sorry, I didn't understand. Send 'menu' or 'hi' to start over.")
    await reset_state(sender)
    return


# ========= FastAPI endpoints (verification + webhook) =========
@router.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        # MUST return the challenge exactly
        return int(challenge) if challenge and str(challenge).isdigit() else challenge

    logger.warning(f"Webhook verification failed. Mode={mode}, Token={token}")
    raise HTTPException(status_code=403, detail="Verification failed")



@router.post("/webhook")
async def incoming_webhook(request: Request):
    """
    Meta will POST updates here. We extract sender & message text and pass to processor.
    """
    body = await request.json()
    logger.info("Webhook POST received: %s", body)
    # Basic protections
    entry = (body.get("entry") or [None])[0]
    changes = (entry.get("changes") or [None]) if entry else []
    if not changes:
        return {"status": "no-change"}
    value = changes[0].get("value", {})
    messages = value.get("messages") or []
    if not messages:
        return {"status": "no-messages"}
    message = messages[0]
    sender = message.get("from")
    # text payload could be in message['text']['body'] or interactive button in 'interactive'
    text = None
    if message.get("text"):
        text = message["text"].get("body", "")
    elif message.get("interactive"):
        # button replies under interactive -> button_reply or type
        ir = message["interactive"]
        if ir.get("type") == "button_reply":
            text = ir["button_reply"].get("title") or ir["button_reply"].get("id")
        elif ir.get("type") == "list_reply":
            text = ir["list_reply"].get("title") or ir["list_reply"].get("id")
        else:
            text = ir.get("body", {}).get("text", "")
    else:
        # fallback: try text in message payload
        text = str(message)
    # process in background to return 200 quickly
    asyncio.create_task(process_incoming_message(sender, text, message))
    return {"status": "processing"}

# end of webhook.py
