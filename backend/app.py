import os
import json
import logging
import pickle
from datetime import datetime

import pandas as pd
import numpy as np
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---------------- APP INIT ----------------
app = FastAPI(title="NovaMed Backend")

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

# ---------------- FIREBASE INIT ----------------
db = None
try:
    import firebase_admin
    from firebase_admin import credentials, firestore

    if not firebase_admin._apps:
        sa = os.getenv("FIREBASE_CREDENTIALS")
        if not sa:
            raise ValueError("FIREBASE_CREDENTIALS missing")

        cred = credentials.Certificate(json.loads(sa))
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    logger.info("✅ Firebase initialized")

except Exception as e:
    logger.error("❌ Firebase init failed: %s", e)

# ---------------- ROUTERS ----------------
try:
    from webhook import router as whatsapp_router
    app.include_router(whatsapp_router)
    logger.info("✅ WhatsApp webhook loaded")
except Exception as e:
    logger.warning("⚠️ WhatsApp webhook not loaded: %s", e)

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # change to frontend domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- ROOT ----------------
@app.get("/")
def home():
    return {"status": "NovaMed backend running"}

# ---------------- LOAD ML MODEL ----------------
MODEL_PATH = "xgb_patient_model.pkl"
model = None

try:
    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)
    logger.info("✅ XGBoost model loaded")
except Exception as e:
    logger.error("❌ Model load failed: %s", e)

# ---------------- DEPARTMENT MAPPING ----------------
DEPT_MAPPING = {
    "Anaesthesiology": 1,
    "Ophthalmology": 2,
    "Gynecology": 3,
    "Dentist": 4,
    "General Surgeon": 5,
    "Orthopedics": 6,
    "Pediatrics": 7,
    "ENT Specialist": 8,
    "Dermatology": 9,
    "Physician": 10,
    "Cardiology": 11,
    "Neurology": 12,
    "General Medicine": 13
}

# ---------------- PATIENT ID GENERATOR ----------------
def generate_patient_id():
    if not db:
        raise RuntimeError("Firestore unavailable")

    ref = db.collection("metadata").document("patient_counter")
    transaction = db.transaction()

    @firestore.transactional
    def txn(tx):
        snap = ref.get(transaction=tx)
        last = snap.to_dict().get("count", 1000) if snap.exists else 1000
        new = last + 1
        tx.set(ref, {"count": new})
        return f"P{new}"

    return txn(transaction)

# ---------------- WEBSITE REGISTRATION ----------------
@app.post("/register_patient")
async def register_patient(request: Request):
    if not db:
        return JSONResponse({"error": "Database unavailable"}, 503)

    try:
        payload = await request.json()
        pid = generate_patient_id()

        payload.update({
            "PatientID": pid,
            "createdAt": firestore.SERVER_TIMESTAMP
        })

        db.collection("patients").document(pid).set(payload)

        return {"status": "success", "PatientID": pid}

    except Exception as e:
        logger.exception("❌ Registration failed")
        return JSONResponse({"error": str(e)}, 500)

# ---------------- PREDICTION API (FIXED) ----------------
@app.post("/predict")
async def predict(request: Request):
    if model is None or not db:
        return JSONResponse(
            {"error": "Prediction service unavailable"},
            status_code=503
        )

    try:
        body = await request.json()
        department = body.get("department")
        date = body.get("date")

        if not department or not date:
            return JSONResponse(
                {"error": "department and date required"},
                status_code=400
            )

        if department not in DEPT_MAPPING:
            return JSONResponse(
                {"error": "Invalid department"},
                status_code=400
            )

        # Day of week
        weekday = datetime.strptime(date, "%Y-%m-%d").weekday()

        # Count existing appointments from Firestore
        booked = db.collection("patients") \
            .where("Department", "==", department) \
            .where("RegistrationDate", "==", date) \
            .stream()

        existing_count = sum(1 for _ in booked)

        # Model input (must match training)
        df = pd.DataFrame({
            "weekday": [weekday],
            "hour": [10],  # peak hour assumption
            "dept_code": [DEPT_MAPPING[department]],
            "existing_patients": [existing_count]
        })

        prediction = int(np.maximum(model.predict(df)[0], 0))

        crowd_level = (
            "LOW" if prediction < 10 else
            "MEDIUM" if prediction < 20 else
            "HIGH"
        )

        return {
            "department": department,
            "date": date,
            "alreadyBooked": existing_count,
            "predictedPatients": prediction,
            "crowdLevel": crowd_level
        }

    except Exception as e:
        logger.exception("❌ Prediction failed")
        return JSONResponse({"error": str(e)}, 500)
