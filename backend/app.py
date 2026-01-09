import os, json, logging, pickle
from datetime import datetime

import pandas as pd
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
        fb_env = os.getenv("FIREBASE_CREDENTIALS")
        if fb_env:
            cred = credentials.Certificate(json.loads(fb_env))
        else:
            cred = credentials.Certificate("serviceAccountKey.json")
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    logger.info("✅ Firebase connected")
except Exception as e:
    logger.error("❌ Firebase failed: %s", e)
    db = None

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

# ---------------- LOAD MODEL ----------------
model = None
try:
    with open("xgb_patient_model.pkl", "rb") as f:
        model = pickle.load(f)
    logger.info("✅ XGBoost model loaded")
except Exception as e:
    logger.error("❌ Model load failed: %s", e)
    model = None

# ---------------- DEPARTMENT MAP (UPDATED) ----------------
DEPT_MAP = {
    "Cardiology": 0,
    "Pediatrics": 1,
    "Dermatology": 2,
    "Dentist": 3,
    "ENT": 4,
    "Gynecology": 5,
    "Anesthesiology": 6,
    "General Surgeon": 7,
    "Physician": 8,
    "Ophthalmology": 9,
}

# ---------------- PREDICT ----------------
@app.post("/predict")
async def predict(req: Request):
    if not model or not db:
        return JSONResponse({"error": "Service unavailable"}, 503)

    body = await req.json()
    department = body.get("department")
    date = body.get("date")

    if department not in DEPT_MAP:
        return JSONResponse({"error": "Invalid department"}, 400)

    try:
        weekday = datetime.strptime(date, "%Y-%m-%d").weekday()
    except Exception:
        return JSONResponse({"error": "Invalid date"}, 400)

    # already booked
    existing = (
        db.collection("patients")
        .where("Department", "==", department)
        .where("Date", "==", date)
        .stream()
    )
    already_booked = sum(1 for _ in existing)

    chart_data = []
    total_predicted = 0

    # OPD HOURS: 9 AM – 6 PM
    for hour in range(9, 19):
        df = pd.DataFrame({
            "weekday": [weekday],
            "hour": [hour],
            "dept_code": [DEPT_MAP[department]],
        })

        pred = int(max(model.predict(df)[0], 0))
        total_predicted += pred

        chart_data.append({
            "hour": f"{hour}:00",
            "predicted": pred
        })

    hourly_avg = round(total_predicted / len(chart_data), 1)

    est_min = int(total_predicted * 2.5)
    est_max = int(total_predicted * 3.5)

    crowd = (
        "LOW" if total_predicted < 30
        else "MEDIUM" if total_predicted < 60
        else "HIGH"
    )

    return {
        "alreadyBooked": already_booked,
        "hourlyAvg": hourly_avg,
        "estimatedRange": f"{est_min}–{est_max}",
        "crowdLevel": crowd,
        "chartData": chart_data
    }

# ---------------- WHATSAPP ROUTER ----------------
from webhook import router
app.include_router(router)
