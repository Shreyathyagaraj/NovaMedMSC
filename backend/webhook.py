# backend/webhook.py

import os
import re
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

# NLP/support endpoint to forward user queries (set this to your ML service)
NLP_SUPPORT_URL = os.getenv("NLP_SUPPORT_URL", "http://localhost:8000/nlp_support")
# Public PDF URL to send as dummy report (must be publicly accessible)
REPORT_PDF_URL = os.getenv("REPORT_PDF_URL", "")

if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
    logger.warning("⚠️ WHATSAPP_TOKEN or PHONE_NUMBER_ID missing. Outgoing messages will fail.")
if not REPORT_PDF_URL:
    logger.warning("⚠️ REPORT_PDF_URL is not set. Report PDF sending will fail unless you provide a public URL.")

# ================= DOCTOR SCHEDULES & LIMITS (as requested) =================
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

# Utility: build department slots dict used by registration logic
DEPARTMENT_SLOTS = {
    dept: {"times": (times[0], times[1]), "capacity": doctorLimits.get(dept, 5)}
    for dept, times in doctorSchedule.items()
}

# ================= UTILITIES ==========================
async def send_whatsapp_text(to: str, text: str):
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        logger.error("WhatsApp credentials missing.")
        return {"error": "whatsapp credentials missing"}

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
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        logger.error("WhatsApp credentials missing.")
        return {"error": "whatsapp credentials missing"}

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


async def send_whatsapp_document(to: str, document_url: str, filename: str = "report.pdf"):
    """
    Sends a document (PDF) via WhatsApp using a public URL.
    """
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        logger.error("WhatsApp credentials missing.")
        return {"error": "whatsapp credentials missing"}
    if not document_url:
        logger.error("Document URL missing.")
        return {"error": "document url missing"}

    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to.lstrip("+"),
        "type": "document",
        "document": {
            "link": document_url,
            "filename": filename
        }
    }
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

    async with httpx.AsyncClient(timeout=20) as client:
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


# ========== STATE HELPERS ================
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


# ========== APPOINTMENT REGISTRATION (transactional) ==============
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
    """
    data should contain keys:
    firstName, lastName, gender, address, phoneNumber, email, department, registrationDate, registrationTime
    """
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

        # Store with the requested field names/capitalization
        tx.set(patient_ref, {
            "PatientID": pid,
            "FirstName": data.get("firstName", ""),
            "LastName": data.get("lastName", ""),
            "Gender": data.get("gender", ""),
            "Address": data.get("address", ""),
            "PhoneNumber": data.get("phoneNumber", ""),
            "Email": data.get("email", ""),
            "Department": data.get("department", ""),
            "RegistrationDate": data.get("registrationDate", ""),
            "RegistrationTime": data.get("registrationTime", ""),
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


# ========== SUPPORT (NLP) ==========
async def nlp_support_reply(query: str) -> str:
    # Forward query to configured NLP endpoint
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(NLP_SUPPORT_URL, json={"query": query})
            if res.status_code == 200:
                j = res.json()
                # expected { "answer": "..." } or simply text
                if isinstance(j, dict) and "answer" in j:
                    return j["answer"]
                if isinstance(j, dict) and "reply" in j:
                    return j["reply"]
                # fallback to JSON -> text
                return res.text
            else:
                logger.warning("NLP endpoint returned status %s", res.status_code)
                return "Sorry, support is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.exception("NLP support call failed: %s", e)
        return "Sorry, I couldn't contact the support system right now."


# ================= MESSAGE PROCESSOR ====================
async def process_incoming_message(sender: str, text: str, wa_message: dict):
    text_raw = text.strip()
    text = text_raw.lower()

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

        if button_id == "opt_book" or text in ["book", "book appointment", "appointment"]:
            await send_whatsapp_text(sender, "Enter First Name:")
            await set_state(sender, {"step": "first_name", "data": {}})
            return

        if button_id == "opt_report" or text in ["report", "get report"]:
            await send_whatsapp_text(sender, "Please enter your Patient ID to retrieve report:")
            await set_state(sender, {"step": "report_waiting_for_id", "data": {}})
            return

        if button_id == "opt_support" or text in ["support", "help"]:
            await send_whatsapp_text(sender, "You're in Support mode. Ask your question and I'll forward it to our specialist system.")
            await set_state(sender, {"step": "support", "data": {}})
            return

        # fallback
        await send_whatsapp_buttons(
            sender,
            "Choose an option:",
            [
                {"id": "opt_book", "title": "Book Appointment"},
                {"id": "opt_report", "title": "Get Report"},
                {"id": "opt_support", "title": "Support"},
            ],
        )
        return

    # ==== BOOKING FLOW ====
    if step == "first_name":
        data["firstName"] = text_raw.title()
        await set_state(sender, {"step": "last_name", "data": data})
        await send_whatsapp_text(sender, "Enter Last Name:")
        return

    if step == "last_name":
        data["lastName"] = text_raw.title()
        await set_state(sender, {"step": "gender", "data": data})
        await send_whatsapp_text(sender, "Enter Gender (Male/Female/Other):")
        return

    if step == "gender":
        data["gender"] = text_raw.title()
        await set_state(sender, {"step": "address", "data": data})
        await send_whatsapp_text(sender, "Enter Address (give a short address):")
        return

    if step == "address":
        data["address"] = text_raw
        await set_state(sender, {"step": "email", "data": data})
        await send_whatsapp_text(sender, "Enter Email (or type skip):")
        return

    if step == "email":
        if text != "skip":
            if not re.match(r".+@.+\..+", text):
                await send_whatsapp_text(sender, "Invalid email format. Please enter a valid email or type 'skip'.")
                return
            data["email"] = text
        else:
            data["email"] = ""

        await set_state(sender, {"step": "phone", "data": data})
        await send_whatsapp_text(sender, "Enter Phone Number (10 digits or include country code):")
        return

    if step == "phone":
        phone = normalize_phone(text_raw)
        if not phone:
            await send_whatsapp_text(sender, "Invalid phone. Try again (10 digits or include country code).")
            return
        data["phoneNumber"] = phone

        # Ask department choices
        msg = "Choose Department:\n"
        dept_list = list(DEPARTMENT_SLOTS.keys())
        for i, d in enumerate(dept_list, start=1):
            msg += f"{i}. {d}\n"

        await set_state(sender, {"step": "department", "data": data})
        await send_whatsapp_text(sender, msg)
        return

    if step == "department":
        dept_list = list(DEPARTMENT_SLOTS.keys())
        if text.isdigit() and 1 <= int(text) <= len(dept_list):
            chosen = dept_list[int(text) - 1]
            data["department"] = chosen
        else:
            # accept exact department name too
            matches = [d for d in dept_list if d.lower() == text]
            if matches:
                data["department"] = matches[0]
            else:
                await send_whatsapp_text(sender, "Invalid choice. Send the number from the list.")
                return

        # ask date
        await set_state(sender, {"step": "date", "data": data})
        await send_whatsapp_text(sender, "Enter preferred date (e.g., 2025-12-10):")
        return

    if step == "date":
        parsed = parse_date_time(text_raw)
        if not parsed["date"]:
            await send_whatsapp_text(sender, "Invalid date. Try again (YYYY-MM-DD or natural language).")
            return

        data["registrationDate"] = parsed["date"]

        # Build available hourly slots from department times
        dept_cfg = DEPARTMENT_SLOTS.get(data["department"])
        if not dept_cfg:
            await send_whatsapp_text(sender, "Configuration error: department not found.")
            await reset_state(sender)
            return

        start_h = int(dept_cfg["times"][0][:2])
        end_h = int(dept_cfg["times"][1][:2])

        # generate hourly slots in range [start_h, end_h - 1] as common practice, but include end if desired
        times = []
        for h in range(start_h, end_h + 1):
            t = f"{h:02d}:00"
            times.append(t)

        data["time_list"] = times
        await set_state(sender, {"step": "time", "data": data})

        msg = "Available time slots:\n"
        for i, t in enumerate(times, start=1):
            msg += f"{i}. {t}\n"
        await send_whatsapp_text(sender, msg)
        return

    if step == "time":
        times = data.get("time_list", [])
        if not times:
            await send_whatsapp_text(sender, "No time slots available. Please restart by saying 'hi'.")
            await reset_state(sender)
            return

        if text.isdigit() and 1 <= int(text) <= len(times):
            selected = times[int(text) - 1]
        else:
            await send_whatsapp_text(sender, "Send the number corresponding to the desired time slot.")
            return

        data["registrationTime"] = selected

        # Validate capacity and register immediately (no OTP)
        try:
            pid = attempt_registration_tx({
                "firstName": data.get("firstName", ""),
                "lastName": data.get("lastName", ""),
                "gender": data.get("gender", ""),
                "address": data.get("address", ""),
                "phoneNumber": data.get("phoneNumber", ""),
                "email": data.get("email", ""),
                "department": data.get("department", ""),
                "registrationDate": data.get("registrationDate", ""),
                "registrationTime": data.get("registrationTime", ""),
            })

            # attempt_registration_tx returns a transaction (callable) result (synchronous in this context)
            # If the tx returns a future-like Firestore result, ensure we handle it. In firebase-admin python run_transaction returns value.
            if isinstance(pid, str) and pid.startswith("P"):
                await send_whatsapp_text(sender, f"🎉 Appointment booked!\nPatient ID: {pid}\nDepartment: {data.get('department')}\nDate: {data.get('registrationDate')}\nTime: {data.get('registrationTime')}")
            else:
                # If pid is a future-like (unlikely here), convert to str
                await send_whatsapp_text(sender, f"🎉 Appointment booked!\nPatient ID: {str(pid)}")
        except Exception as e:
            logger.exception("Registration failed: %s", e)
            # If it's capacity issue or other error, inform user
            err_msg = str(e)
            if "Slot is full" in err_msg:
                await send_whatsapp_text(sender, f"❌ Sorry, the selected slot is full for {data.get('department')} on {data.get('registrationDate')}. Please pick another date or department. Send 'hi' to restart.")
            else:
                await send_whatsapp_text(sender, f"❌ Registration failed: {err_msg}. Please try again later or contact support.")
        finally:
            await reset_state(sender)
        return

    # ==== REPORT FLOW ====
    if step == "report_waiting_for_id":
        pid = text_raw.strip()
        # Basic normalization: if they forgot prefix, try to add 'P' if missing numeric
        if re.match(r"^\d+$", pid):
            pid = "P" + pid
        # direct doc lookup
        doc_ref = db.collection("patients").document(pid)
        doc_snap = doc_ref.get()
        if not doc_snap.exists:
            await send_whatsapp_text(sender, f"No patient found with ID {pid}. Please check and try again.")
            await reset_state(sender)
            return

        pdata = doc_snap.to_dict()
        # Build summary text
        summary = (
            f"Patient Report for {pdata.get('FirstName','')} {pdata.get('LastName','')}\n"
            f"Patient ID: {pdata.get('PatientID')}\n"
            f"Department: {pdata.get('Department')}\n"
            f"Date: {pdata.get('RegistrationDate')}\n"
            f"Time: {pdata.get('RegistrationTime')}\n"
            f"Phone: {pdata.get('PhoneNumber')}\n"
            f"Email: {pdata.get('Email')}\n"
            f"Address: {pdata.get('Address')}\n"
            f"Gender: {pdata.get('Gender')}\n"
        )

        await send_whatsapp_text(sender, summary)

        # Send PDF document (requires REPORT_PDF_URL to be publicly reachable)
        REPORT_BASE_URL = os.getenv("REPORT_BASE_URL", "")
        if REPORT_BASE_URL:
            pdf_url = f"{REPORT_BASE_URL}/reports/{pid}"
            
            await send_whatsapp_document(sender, pdf_url, filename=f"{pid}_report.pdf")
        else:
            await send_whatsapp_text(sender, "Report service not configured. Ask admin to set REPORT_BASE_URL.")


        await reset_state(sender)
        return

    # ==== SUPPORT MODE ====
    if step == "support":
        # forward the message to NLP and return the response
        reply = await nlp_support_reply(text_raw)
        await send_whatsapp_text(sender, reply)
        # keep support session active so user can ask follow-up queries, or end with 'exit'
        # If user types 'exit' we reset
        if text in ["exit", "quit", "bye", "close"]:
            await send_whatsapp_text(sender, "Support session ended. Send 'hi' to return to main menu.")
            await reset_state(sender)
        else:
            # remain in support
            await set_state(sender, {"step": "support", "data": {}})
        return

    # ==== FALLBACK ====
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
        # extract text body robustly
        text = ""
        if msg.get("text"):
            text = msg["text"]["body"]
        elif msg.get("button"):
            text = msg["button"].get("text", "")
        elif msg.get("interactive") and msg["interactive"].get("type") == "button_reply":
            text = msg["interactive"]["button_reply"].get("title", "") or msg["interactive"]["button_reply"].get("id", "")
        else:
            # other types ignored for now (media etc.)
            text = ""

        await process_incoming_message(sender, text, msg)

        return {"status": "ok"}

    except Exception as e:
        logger.exception("Error handling webhook: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
