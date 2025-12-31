import os
from datetime import datetime, timedelta
import httpx
from firebase_admin import firestore
from firebase_config import init_firebase

db = init_firebase()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

WA_API = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"

def send_whatsapp(to, text):
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    httpx.post(WA_API, json=payload, headers=headers)

def run():
    now = datetime.utcnow()
    upcoming = now + timedelta(minutes=10)

    docs = db.collection("patients") \
        .where("ReminderAt", "<=", upcoming) \
        .where("ReminderSent", "==", False) \
        .stream()

    for d in docs:
        p = d.to_dict()
        send_whatsapp(
            p["Phone"],
            f"⏰ Reminder: Your appointment at {p['RegistrationTime']} "
            f"({p['Department']}). Please be on time."
        )
        d.reference.update({"ReminderSent": True})

if __name__ == "__main__":
    run()
