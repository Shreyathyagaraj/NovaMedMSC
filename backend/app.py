import os
import logging
import pickle
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from firebase_admin import credentials, firestore, initialize_app
import pandas as pd
import numpy as np
from webhook import router as whatsapp_router




app = FastAPI()
app.include_router(whatsapp_router)
# ----------------- Logging -----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------- Firebase Init -----------------
try:
    cred = credentials.Certificate("serviceAccountKey.json")
    initialize_app(cred)
    db = firestore.client()
    logger.info("✅ Firebase initialized successfully.")
except Exception as e:
    logger.error("❌ Firebase init failed: %s", e)
    db = None

# ----------------- Load Model -----------------
MODEL_PATH = "xgb_patient_model.pkl"
model = None
try:
    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)
    logger.info("✅ XGBoost model loaded successfully.")
except Exception as e:
    logger.warning("⚠️ Model not loaded (optional): %s", e)

# ----------------- CORS -----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Doctor Schedules -----------------
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

# ----------------- Helper Functions -----------------
def generate_patient_id():
    if db is None:
        raise RuntimeError("Firestore not initialized")
    doc_ref = db.collection("metadata").document("patient_counter")
    doc = doc_ref.get()
    count = doc.to_dict().get("count", 1000) + 1 if doc.exists else 1001
    doc_ref.set({"count": count})
    return f"P{count}"

def store_patient(p: dict):
    if db is None:
        raise RuntimeError("Firestore not initialized")
    patient_id = generate_patient_id()
    p.update({
        "PatientID": patient_id,
        "RegistrationDate": datetime.now().strftime("%Y-%m-%d"),
        "RegistrationTime": datetime.now().strftime("%H:%M:%S"),
        "created_at": datetime.utcnow().isoformat()
    })
    db.collection("patients").document(patient_id).set(p)
    logger.info("✅ Patient stored: %s", patient_id)
    return patient_id

# ----------------- API ENDPOINTS -----------------

@app.post("/register_patient")
async def register_patient(request: Request):
    try:
        # 1️⃣ Get data from frontend
        patient_payload = await request.json()
        logger.info(f"📥 Received registration: {patient_payload}")

        # 2️⃣ Store in Firestore
        pid = store_patient(patient_payload)
        logger.info(f"✅ Stored patient: {pid}")

        # 3️⃣ Create message
        msg = (
            f"Hello {patient_payload.get('FirstName', '')}, your appointment at NovaMed is confirmed.\n"
            f"🆔 Patient ID: {pid}\n"
            f"📅 Date: {datetime.now().strftime('%Y-%m-%d')}\n"
            f"⏰ Time: {datetime.now().strftime('%H:%M')}"
        )

        # 4️⃣ Format number and send WhatsApp
        phone = patient_payload.get('PhoneNumber', '')
        if not phone:
            raise ValueError("Missing phone number in registration form")

        # Ensure correct format (+91)
        phone_e164 = "+91" + phone.strip() if not phone.startswith("+") else phone

        logger.info(f"📞 Sending WhatsApp message to {phone_e164}...")

        

        # 5️⃣ Return success
        return {"PatientID": pid, "status": "success", "whatsapp": "sent"}

    except Exception as e:
        logger.exception("❌ register_patient failed")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/predict")
async def predict(request: Request):
    try:
        if model is None:
            return JSONResponse({"error": "Model not loaded"})

        body = await request.json()
        target_date = body.get("date")
        department = body.get("department")

        if not target_date or not department:
            return JSONResponse({"error": "Missing required parameters"})

        dept_mapping = {
            "Cardiology": 1,
            "Neurology": 2,
            "Orthopedics": 3,
            "Pediatrics": 4,
            "General Medicine": 5,
            "Dermatology": 6
        }

        if department not in dept_mapping:
            return JSONResponse({"error": f"Invalid department '{department}'"})

        dept_code = dept_mapping[department]
        hours = list(range(24))
        df = pd.DataFrame({
            "weekday": [datetime.strptime(target_date, "%Y-%m-%d").weekday()] * 24,
            "hour": hours,
            "dept_code": [dept_code] * 24
        })

        preds = model.predict(df)
        preds = np.maximum(preds, 0).round().astype(int)
        chart_data = [{"hour": f"{h}:00", "predicted": int(p)} for h, p in zip(hours, preds)]
        total = int(np.sum(preds))

        return {"chartData": chart_data, "totalPatients": total, "department": department}

    except Exception as e:
        logger.exception("Prediction failed")
        return JSONResponse({"error": str(e)}, status_code=500)
    
