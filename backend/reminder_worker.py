import os
import json
import asyncio
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore
import httpx

# ---------- Firebase ----------
if not firebase_admin._apps:
    cred = credentials.Certificate(json.loads(os.getenv("FIREBASE_CREDENTIALS")))
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ---------- WhatsApp ----------
WA_API = f"https://graph.facebook.com/v17.0/{os.getenv('PHONE_NUMBER_ID')}/messages"
TOKEN = os.getenv("WHATSAPP_TOKEN")

async def send_reminder(phone, text):
    async with httpx.AsyncClient() as client:
        await client.post(
            WA_API,
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "text",
                "text": {"body": text}
            }
        )

async def check_reminders():
    now = datetime.now()
    upcoming = now + timedelta(minutes=10)

    docs = db.collection("patients")\
        .where("ReminderSent", "==", False)\
        .stream()

    for doc in docs:
        p = doc.to_dict()
        appt_time = datetime.strptime(
            f"{p['RegistrationDate']} {p['RegistrationTime']}",
            "%Y-%m-%d %H:%M"
        )

        if now <= appt_time <= upcoming:
            await send_reminder(
                p["Phone"],
                f"⏰ Reminder: You have an appointment at {p['RegistrationTime']} "
                f"in {p['Department']}. Please arrive 10 minutes early."
            )

            doc.reference.update({"ReminderSent": True})

async def main():
    while True:
        await check_reminders()
        await asyncio.sleep(60)  # check every 1 minute

if __name__ == "__main__":
    asyncio.run(main())
