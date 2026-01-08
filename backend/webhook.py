import os, logging, json
from datetime import datetime, timedelta
import httpx
from fastapi import APIRouter, Request, HTTPException
from reportlab.pdfgen import canvas
from apscheduler.schedulers.background import BackgroundScheduler

from firebase_config import get_db

router = APIRouter()
logger = logging.getLogger("webhook")

db = get_db()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "shreyaWebhook123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WA_API = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"

scheduler = BackgroundScheduler()
scheduler.start()

# ---------------- HELPERS ----------------
async def send_text(to, text):
    async with httpx.AsyncClient() as c:
        await c.post(
            WA_API,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text}
            }
        )

def generate_pdf(patient):
    path = f"/tmp/{patient['PatientID']}.pdf"
    c = canvas.Canvas(path)
    y = 750
    for k, v in patient.items():
        c.drawString(50, y, f"{k}: {v}")
        y -= 20
    c.save()
    return path

def schedule_reminder(phone, time):
    scheduler.add_job(
        lambda: httpx.post(
            WA_API,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "text",
                "text": {"body": "⏰ Reminder: Appointment in 10 minutes"}
            }
        ),
        "date",
        run_date=time - timedelta(minutes=10)
    )

# ---------------- WEBHOOK ----------------
@router.get("/webhook")
async def verify(req: Request):
    if req.query_params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(req.query_params.get("hub.challenge"))
    raise HTTPException(403)

@router.post("/webhook")
async def receive(req: Request):
    body = await req.json()
    msg = body["entry"][0]["changes"][0]["value"].get("messages", [{}])[0]
    sender = msg.get("from")
    text = msg.get("text", {}).get("body", "").lower()

    # RESET FLOW
    if text in ["hi", "hello", "hii", "hey", "menu", "restart"]:
        await send_text(sender, "🏥 *NovaMed*\n1️⃣ Book Appointment\n2️⃣ Get Report\nReply 1 or 2")
        return {"ok": True}

    # REPORT
    if text.upper().startswith("P"):
        doc = db.collection("patients").document(text.upper()).get()
        if not doc.exists:
            await send_text(sender, "❌ Invalid Patient ID")
            return {"ok": True}

        pdf = generate_pdf(doc.to_dict())
        await send_text(sender, "📄 Report generated (PDF ready)")
        return {"ok": True}

    await send_text(sender, "Reply *HI* to start")
    return {"ok": True}
