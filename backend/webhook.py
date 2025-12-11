# backend/webhook.py

import os
import re
import logging
from datetime import datetime
from typing import Dict, Any, List

import httpx
from fastapi import APIRouter, Request, HTTPException
from firebase_admin import firestore
import dateparser

# FIREBASE init (firebase_config must expose init_firebase())
from firebase_config import init_firebase

# ---------- initialize ----------
db = init_firebase()

router = APIRouter()
logger = logging.getLogger("webhook")
logging.basicConfig(level=logging.INFO)

# ---------- ENV / CONFIG ----------
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "shreyaWebhook123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

NLP_SUPPORT_URL = os.getenv("NLP_SUPPORT_URL", "")
REPORT_PDF_URL = os.getenv("REPORT_PDF_URL", "")

if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
    logger.warning("⚠️ WHATSAPP_TOKEN or PHONE_NUMBER_ID missing. Outgoing messages will fail.")
if not REPORT_PDF_URL:
    logger.warning("⚠️ REPORT_PDF_URL not set. Report streaming will fail unless configured.")

# ---------- schedules & limits ----------
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

# ---------- WhatsApp helpers ----------
WA_API = "https://graph.facebook.com/v17.0/{phone_id}/messages".format(phone_id=PHONE_NUMBER_ID)

async def wa_post(payload: dict):
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        logger.error("WhatsApp credentials missing.")
        return None
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(WA_API, json=payload, headers=headers)
        try:
            return r.json()
        except Exception:
            return {"status_code": r.status_code, "text": r.text}

async def send_whatsapp_text(to: str, text: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to.lstrip("+"),
        "type": "text",
        "text": {"body": text},
    }
    await wa_post(payload)

async def send_whatsapp_buttons(to: str, body_text: str, buttons: List[Dict[str,str]]):
    """
    buttons: list of {"id": "...", "title": "..."}
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to.lstrip("+"),
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": [{"type":"reply","reply":{"id":b["id"], "title":b["title"]}} for b in buttons]}
        }
    }
    await wa_post(payload)

async def send_whatsapp_list(to: str, body_text: str, button_text: str, section_title: str, rows: List[Dict[str,str]]):
    """
    rows: list of {"id": "row_id", "title": "Display title", "description": "optional"}
    This constructs a single-section list with up to 10 rows (WhatsApp list messages).
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to.lstrip("+"),
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body_text},
            "action": {
                "button": button_text,
                "sections": [
                    {
                        "title": section_title,
                        "rows": rows
                    }
                ]
            }
        }
    }
    await wa_post(payload)

async def send_whatsapp_document(to: str, document_url: str, filename: str = "report.pdf"):
    if not document_url:
        logger.error("Document URL missing.")
        return
    payload = {
        "messaging_product": "whatsapp",
        "to": to.lstrip("+"),
        "type": "document",
        "document": {"link": document_url, "filename": filename}
    }
    await wa_post(payload)

# ---------- utilities ----------
def normalize_phone(user_input: str):
    """
    Accepts digits, optionally with +.
    - If user enters 10 digits, assume India and prepend +91
    - If user enters digits >10 and does not start with +, prepend +
    - If already starts with +, return as is
    """
    s = re.sub(r"[^\d+]", "", user_input.strip())
    if not s:
        return None
    if s.startswith("+"):
        return s
    digits = re.sub(r"\D", "", s)
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) > 10:
        return "+" + digits
    return None

def parse_date_time(text: str):
    parsed = dateparser.parse(text)
    if not parsed:
        return {"date": None, "time": None}
    return {"date": parsed.strftime("%Y-%m-%d"), "time": parsed.strftime("%H:%M")}

# ---------- state helpers ----------
def get_state(sender: str):
    ref = db.collection("registration_states").document(sender)
    snap = ref.get()
    return snap.to_dict() if snap.exists else {"step": None, "data": {}}

def set_state(sender: str, state: dict):
    db.collection("registration_states").document(sender).set({**state, "updatedAt": firestore.SERVER_TIMESTAMP})

def reset_state(sender: str):
    db.collection("registration_states").document(sender).delete()

def attempt_registration_tx(data: dict):

    slot_id = f"{data['department']}_{data['registrationDate']}_{data['registrationTime']}"
    slot_ref = db.collection("appointments").document(slot_id)
    counter_ref = db.collection("metadata").document("patient_counter")

    def register(tx):

        # ---- FIX 1: slot get ----
        slot_gen = tx.get(slot_ref)
        slot_snap = next(slot_gen, None)

        current_count = slot_snap.to_dict().get("count", 0) if slot_snap and slot_snap.exists else 0

        cap = DEPARTMENT_SLOTS.get(data["department"], {}).get("capacity", 5)
        if current_count >= cap:
            raise ValueError("Slot is full.")

        # ---- FIX 2: counter get ----
        counter_gen = tx.get(counter_ref)
        counter_snap = next(counter_gen, None)

        if counter_snap and counter_snap.exists:
            new_id_num = counter_snap.to_dict().get("count", 1000) + 1
        else:
            new_id_num = 1001

        tx.set(counter_ref, {"count": new_id_num}, merge=True)

        pid = f"P{new_id_num}"

        # patient record
        patient_ref = db.collection("patients").document(pid)
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
            "createdAt": firestore.SERVER_TIMESTAMP
        })

        # slot update
        tx.set(slot_ref, {
            "department": data["department"],
            "date": data["registrationDate"],
            "time": data["registrationTime"],
            "count": current_count + 1
        }, merge=True)

        return pid

    # ---- FINAL FIX ----
    tx = db.transaction()
    result = register(tx)   # run the function
    tx.commit()             # commit the transaction

    return result



# ---------- NLP support ----------
async def nlp_support_reply(query: str) -> str:
    if not NLP_SUPPORT_URL:
        return "Support service not configured."
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(NLP_SUPPORT_URL, json={"query": query})
            if res.status_code == 200:
                j = res.json()
                if isinstance(j, dict):
                    return j.get("answer") or j.get("reply") or str(j)
                return res.text
            return "Support is temporarily unavailable."
    except Exception as e:
        logger.exception("NLP call failed")
        return "Unable to contact support right now."

# ---------- message processing (state machine) ----------
async def process_incoming_message(sender: str, text: str, wa_message: dict):
    text_raw = (text or "").strip()
    text = text_raw.lower()

    state = get_state(sender)
    step = state.get("step")
    data = state.get("data", {})

    # START: show main menu
    if not step:
        if text in ["hi", "hello", "hey"]:
            await send_whatsapp_buttons(
                sender,
                "Welcome to NovaMed! Choose an option:",
                [
                    {"id": "opt_book", "title": "Book Appointment"},
                    {"id": "opt_report", "title": "Get Report"},
                    {"id": "opt_support", "title": "Support"},
                ]
            )
            set_state(sender, {"step": "menu", "data": {}})
            return
        await send_whatsapp_text(sender, "Send *Hi* to start.")
        return

    # MENU
    if step == "menu":
        # check button reply
        button_id = None
        try:
            button_id = wa_message["interactive"]["button_reply"]["id"]
        except:
            pass

        if button_id == "opt_book" or text in ["book", "book appointment", "appointment"]:
            await send_whatsapp_text(sender, "Enter First Name:")
            set_state(sender, {"step": "first_name", "data": {}})
            return

        if button_id == "opt_report" or text in ["report", "get report"]:
            await send_whatsapp_text(sender, "Please enter your Patient ID (e.g. P1001):")
            set_state(sender, {"step": "report_waiting_for_id", "data": {}})
            return

        if button_id == "opt_support" or text in ["support", "help"]:
            await send_whatsapp_text(sender, "Support mode: ask your question and I'll forward to our specialists.")
            set_state(sender, {"step": "support", "data": {}})
            return

        # fallback
        await send_whatsapp_buttons(
            sender,
            "Choose an option:",
            [
                {"id": "opt_book", "title": "Book Appointment"},
                {"id": "opt_report", "title": "Get Report"},
                {"id": "opt_support", "title": "Support"},
            ]
        )
        return

    # BOOKING FLOW
    if step == "first_name":
        data["firstName"] = text_raw.title()
        set_state(sender, {"step": "last_name", "data": data})
        await send_whatsapp_text(sender, "Enter Last Name:")
        return

    if step == "last_name":
        data["lastName"] = text_raw.title()
        set_state(sender, {"step": "gender", "data": data})
        # gender buttons
        await send_whatsapp_buttons(sender, "Select Gender:", [
            {"id": "g_male", "title": "Male"},
            {"id": "g_female", "title": "Female"},
            {"id": "g_other", "title": "Other"},
        ])
        return

    if step == "gender":
        # accept button reply or text
        try:
            bid = wa_message["interactive"]["button_reply"]["id"]
            if bid.startswith("g_"):
                data["gender"] = bid.split("_", 1)[1].title()
        except:
            if text in ["male", "female", "other"]:
                data["gender"] = text.title()
            else:
                await send_whatsapp_buttons(sender, "Select Gender:", [
                    {"id": "g_male", "title": "Male"},
                    {"id": "g_female", "title": "Female"},
                    {"id": "g_other", "title": "Other"},
                ])
                return

        set_state(sender, {"step": "address", "data": data})
        await send_whatsapp_text(sender, "Enter Address (short):")
        return

    if step == "address":
        data["address"] = text_raw
        set_state(sender, {"step": "email", "data": data})
        await send_whatsapp_text(sender, "Enter Email (or type 'skip'):")
        return

    if step == "email":
        if text != "skip":
            if not re.match(r".+@.+\..+", text):
                await send_whatsapp_text(sender, "Invalid email format. Enter a valid email or type 'skip'.")
                return
            data["email"] = text
        else:
            data["email"] = ""
        set_state(sender, {"step": "phone", "data": data})
        await send_whatsapp_text(sender, "Enter Phone Number (10 digits only — +91 will be added automatically):")
        return

    if step == "phone":
        phone_norm = normalize_phone(text_raw)
        if not phone_norm:
            await send_whatsapp_text(sender, "Invalid phone. Enter 10 digits (e.g. 919876543210 or 9876543210).")
            return
        data["phoneNumber"] = phone_norm
        # department selection as buttons
        dept_buttons = []
        for i, d in enumerate(DEPARTMENT_SLOTS.keys(), start=1):
            dept_buttons.append({"id": f"dept_{i}", "title": d})
            if len(dept_buttons) == 3:
                # WhatsApp button interactive supports up to 3 buttons in one message; we will send in a single message.
                pass
        # Send department choices as buttons — we will send them in one message with up to 3 buttons. For >3, fallback to text list.
        # Because WhatsApp button interactive supports max 3 buttons, we will send a numbered text if >3.
        dept_list = list(DEPARTMENT_SLOTS.keys())
        if len(dept_list) <= 3:
            await send_whatsapp_buttons(sender, "Choose Department:", [{"id": f"dept_{i+1}", "title": name} for i, name in enumerate(dept_list)])
        else:
            # send numbered list (user can type number or name) — but we prefer buttons for the first three for convenience
            msg = "Choose Department:\n"
            for i, d in enumerate(dept_list, start=1):
                msg += f"{i}. {d}\n"
            await send_whatsapp_text(sender, msg)
        set_state(sender, {"step": "department", "data": data})
        return

    if step == "department":
        dept_list = list(DEPARTMENT_SLOTS.keys())
        chosen = None
        # check button ID first
        try:
            bid = wa_message["interactive"]["button_reply"]["id"]
            if bid.startswith("dept_"):
                idx = int(bid.split("_")[1]) - 1
                if 0 <= idx < len(dept_list):
                    chosen = dept_list[idx]
        except:
            pass

        if not chosen:
            # check numeric choice
            if text.isdigit() and 1 <= int(text) <= len(dept_list):
                chosen = dept_list[int(text) - 1]
            else:
                # check exact match
                for d in dept_list:
                    if d.lower() == text:
                        chosen = d
                        break

        if not chosen:
            # resend options
            msg = "Choose Department:\n"
            for i, d in enumerate(dept_list, start=1):
                msg += f"{i}. {d}\n"
            await send_whatsapp_text(sender, msg)
            return

        data["department"] = chosen
        set_state(sender, {"step": "date", "data": data})
        await send_whatsapp_text(sender, "Enter preferred date (YYYY-MM-DD) or natural language like 'tomorrow':")
        return

    if step == "date":
        parsed = parse_date_time(text_raw)
        if not parsed["date"]:
            await send_whatsapp_text(sender, "Invalid date. Please enter YYYY-MM-DD or 'tomorrow'.")
            return
        data["registrationDate"] = parsed["date"]

        # build time slots based on schedule (hourly)
        dept_cfg = DEPARTMENT_SLOTS.get(data["department"])
        if not dept_cfg:
            await send_whatsapp_text(sender, "Configuration error: department not found. Restart with 'hi'.")
            reset_state(sender)
            return

        start_h = int(dept_cfg["times"][0][:2])
        end_h = int(dept_cfg["times"][1][:2])
        times = [f"{h:02d}:00" for h in range(start_h, end_h + 1)]

        # build list rows (max 10 items per WhatsApp list)
        rows = []
        for i, t in enumerate(times, start=1):
            rows.append({"id": f"time_{i}", "title": t, "description": ""})
            if len(rows) >= 10:
                break

        # Ask user to pick time via WhatsApp LIST interactive
        await send_whatsapp_list(
            sender,
            f"Available time slots for {data['department']} on {data['registrationDate']}:",
            "Choose time",
            "Available times",
            rows
        )
        # store list of times temporarily in DB state (not saved to patient)
        data["time_list"] = times  # will be removed before storing patient
        set_state(sender, {"step": "time", "data": data})
        return

    if step == "time":
        # Handle list reply (interactive -> list_reply)
        chosen_time = None
        try:
            # list reply: wa_message["interactive"]["list_reply"]["id"]
            if wa_message.get("interactive") and wa_message["interactive"].get("type") == "list_reply":
                row_id = wa_message["interactive"]["list_reply"].get("id")
                if row_id and row_id.startswith("time_"):
                    idx = int(row_id.split("_")[1]) - 1
                    times = data.get("time_list", [])
                    if 0 <= idx < len(times):
                        chosen_time = times[idx]
        except Exception:
            logger.debug("No list reply detected")

        # fallback: user typed time or number
        if not chosen_time:
            times = data.get("time_list", [])
            if text.isdigit() and 1 <= int(text) <= len(times):
                chosen_time = times[int(text) - 1]
            elif re.match(r"^\d{1,2}:\d{2}$", text_raw):
                chosen_time = text_raw
            else:
                await send_whatsapp_text(sender, "Invalid time selection. Please pick from the list.")
                return

        data["registrationTime"] = chosen_time

        # prepare payload for transaction (strip time_list before sending)
        tx_data = {
            "firstName": data.get("firstName", ""),
            "lastName": data.get("lastName", ""),
            "gender": data.get("gender", ""),
            "address": data.get("address", ""),
            "phoneNumber": data.get("phoneNumber", ""),
            "email": data.get("email", ""),
            "department": data.get("department", ""),
            "registrationDate": data.get("registrationDate", ""),
            "registrationTime": data.get("registrationTime", "")
        }

        try:
            pid = attempt_registration_tx(tx_data)
            await send_whatsapp_text(sender, f"🎉 Appointment booked!\nPatient ID: {pid}\nDept: {tx_data['department']}\nDate: {tx_data['registrationDate']}\nTime: {tx_data['registrationTime']}")
        except Exception as e:
            logger.exception("Registration failed")
            if "Slot is full" in str(e):
                await send_whatsapp_text(sender, "❌ Sorry, the selected slot is full. Try a different time or date.")
            else:
                await send_whatsapp_text(sender, "❌ Registration failed. Try later.")
        finally:
            # remove transient fields and reset
            data.pop("time_list", None)
            reset_state(sender)
        return

    # REPORT FLOW
    if step == "report_waiting_for_id":
        pid = text_raw.strip()
        if re.match(r"^\d+$", pid):
            pid = "P" + pid
        doc = db.collection("patients").document(pid).get()
        if not doc.exists:
            await send_whatsapp_text(sender, f"No patient found with ID {pid}.")
            reset_state(sender)
            return
        pdata = doc.to_dict()
        summary = (
            f"Report for {pdata.get('FirstName','')} {pdata.get('LastName','')}\n"
            f"Patient ID: {pdata.get('PatientID')}\n"
            f"Department: {pdata.get('Department')}\n"
            f"Date: {pdata.get('RegistrationDate')}\n"
            f"Time: {pdata.get('RegistrationTime')}\n"
        )
        await send_whatsapp_text(sender, summary)
        if REPORT_PDF_URL:
            pdf_url = f"{REPORT_PDF_URL}/reports/{pid}"
            await send_whatsapp_document(sender, pdf_url, filename=f"{pid}_report.pdf")
        else:
            await send_whatsapp_text(sender, "Report service not configured.")
        reset_state(sender)
        return

    # SUPPORT
    if step == "support":
        reply = await nlp_support_reply(text_raw)
        await send_whatsapp_text(sender, reply)
        if text in ["exit", "quit", "bye", "close"]:
            reset_state(sender)
            await send_whatsapp_text(sender, "Support ended. Send 'hi' to return to menu.")
        else:
            set_state(sender, {"step": "support", "data": {}})
        return

    # fallback
    await send_whatsapp_text(sender, "Send 'hi' to start.")
    reset_state(sender)
    return

# ---------- webhook endpoints ----------
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
    logger.info("Incoming webhook: %s", body)

    try:
        entry = body["entry"][0]["changes"][0]["value"]
        messages = entry.get("messages", [])
        if not messages:
            return {"status": "ignored"}

        msg = messages[0]
        sender = msg["from"]

        # extract text robustly (text / button_reply / list_reply)
        text = ""
        if msg.get("text"):
            text = msg["text"].get("body", "")
        elif msg.get("button"):
            text = msg["button"].get("text", "")
        elif msg.get("interactive"):
            itype = msg["interactive"].get("type")
            if itype == "button_reply":
                text = msg["interactive"]["button_reply"].get("title", "")
            elif itype == "list_reply":
                text = msg["interactive"]["list_reply"].get("title", "")
            else:
                text = ""
        else:
            text = ""

        await process_incoming_message(sender, text, msg)
        return {"status": "ok"}

    except Exception as e:
        logger.exception("Error handling webhook: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
