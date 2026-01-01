import logging
import pickle
from datetime import datetime

import pandas as pd
import numpy as np
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from webhook import router as whatsapp_router
from support_and_reports import router as support_router
from firebase_config import init_firebase

# ----------------- APP INIT -----------------
app = FastAPI(title="NovaMed Backend")

# ----------------- LOGGING -----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------- FIREBASE INIT -----------------
db = init_firebase()
logger.info("✅ Firebase initialized")

# ----------------- ROUTERS -----------------
app.include_router(whatsapp_router)
app.include_router(support_router)

# ----------------- CORS -----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- ROOT -----------------
@app.get("/")
def home():
    return {"message": "NovaMed backend running"}

# ----------------- LOAD MODEL -----------------
MODEL_PATH = "xgb_patient_model.pkl"
model = None

try:
    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)
    logger.info("✅ XGBoost model loaded successfully.")
except Exception as e:
    logger.warning("⚠️ Model not loaded (optional): %s", e)

# ----------------- HELPER FUNCTIONS -----------------
def generate_patient_id():
    if db is None:
        raise RuntimeError("Firestore not initialized")

    ref = db.collection("metadata").document("patient_counter")
    snap = ref.get()

    count = snap.to_dict().get("count", 1000) + 1 if snap.exists else 1001
    ref.set({"count": count})

    return f"P{count}"

def store_patient(payload: dict):
    patient_id = generate_patient_id()

    payload.update({
        "PatientID": patient_id,
        "created_at": datetime.utcnow().isoformat()
    })

    db.collection("patients").document(patient_id).set(payload)
    logger.info("✅ Patient stored: %s", patient_id)

    return patient_id

# ----------------- REGISTER PATIENT -----------------
@app.post("/register_patient")
async def register_patient(request: Request):
    try:
        payload = await request.json()
        logger.info("📥 Registration received: %s", payload)

        pid = store_patient(payload)

        return {
            "status": "success",
            "PatientID": pid
        }

    except Exception as e:
        logger.exception("❌ register_patient failed")
        return JSONResponse({"error": str(e)}, status_code=500)

# ----------------- PREDICTION API -----------------
@app.post("/predict")
async def predict(request: Request):
    try:
        if model is None:
            return JSONResponse({"error": "Model not loaded"}, status_code=500)

        body = await request.json()
        target_date = body.get("date")
        department = body.get("department")

        if not target_date or not department:
            return JSONResponse({"error": "Missing parameters"}, status_code=400)

        dept_mapping = {
            "Cardiology": 1,
            "Neurology": 2,
            "Orthopedics": 3,
            "Pediatrics": 4,
            "General Medicine": 5,
            "Dermatology": 6
        }

        if department not in dept_mapping:
            return JSONResponse({"error": "Invalid department"}, status_code=400)

        dept_code = dept_mapping[department]
        weekday = datetime.strptime(target_date, "%Y-%m-%d").weekday()

        df = pd.DataFrame({
            "weekday": [weekday] * 24,
            "hour": list(range(24)),
            "dept_code": [dept_code] * 24
        })

        preds = model.predict(df)
        preds = np.maximum(preds, 0).round().astype(int)

        chart_data = [
            {"hour": f"{h}:00", "predicted": int(p)}
            for h, p in zip(range(24), preds)
        ]

        return {
            "department": department,
            "totalPatients": int(preds.sum()),
            "chartData": chart_data
        }

    except Exception as e:
        logger.exception("❌ Prediction failed")
        return JSONResponse({"error": str(e)}, status_code=500)
