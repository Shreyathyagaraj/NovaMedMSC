import os, json, logging, pickle
from datetime import datetime

import pandas as pd
import numpy as np
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import firebase_admin
from firebase_admin import credentials, firestore

# ---------------- APP INIT ----------------
app = FastAPI(title="NovaMed Backend")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

# ---------------- FIREBASE INIT ----------------
db = None
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(json.loads(os.getenv("FIREBASE_CREDENTIALS")))
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    logger.info("✅ Firebase connected")
except Exception as e:
    logger.error("❌ Firebase failed: %s", e)

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- ROOT ----------------
@app.get("/")
def root():
    return {"status": "NovaMed backend running"}

# ---------------- LOAD ML MODEL ----------------
model = None
try:
    with open("xgb_patient_model.pkl", "rb") as f:
        model = pickle.load(f)
    logger.info("✅ XGBoost model loaded")
except Exception as e:
    logger.error("❌ Model load failed: %s", e)

# ---------------- DEPARTMENT MAP ----------------
DEPT_MAP = {
    "Cardiology": 1,
    "Neurology": 2,
    "Orthopedics": 3,
    "Pediatrics": 4,
    "General Medicine": 5,
    "Dermatology": 6
}

# ---------------- WEBSITE PREDICTION ----------------
@app.post("/predict")
async def predict(req: Request):
    if not model or not db:
        return JSONResponse({"error": "Service unavailable"}, 503)

    body = await req.json()
    department = body.get("department")
    date = body.get("date")

    if department not in DEPT_MAP:
        return JSONResponse({"error": "Invalid department"}, 400)

    weekday = datetime.strptime(date, "%Y-%m-%d").weekday()

    existing = db.collection("patients") \
        .where("Department", "==", department) \
        .where("RegistrationDate", "==", date) \
        .stream()

    count = sum(1 for _ in existing)

    df = pd.DataFrame({
        "weekday": [weekday],
        "hour": [10],
        "dept_code": [DEPT_MAP[department]],
        "existing_patients": [count]
    })

    prediction = int(max(model.predict(df)[0], 0))

    level = "LOW" if prediction < 10 else "MEDIUM" if prediction < 20 else "HIGH"

    return {
        "department": department,
        "date": date,
        "alreadyBooked": count,
        "predictedPatients": prediction,
        "crowdLevel": level
    }

# ---------------- LOAD WHATSAPP ROUTER ----------------
from webhook import router
app.include_router(router)
