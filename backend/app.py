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
        cred = credentials.Certificate(
            json.loads(os.getenv("FIREBASE_CREDENTIALS"))
        )
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    logger.info("✅ Firebase connected")

except Exception as e:
    logger.error("❌ Firebase failed: %s", e)

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Netlify + localhost
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
    "Dermatology": 6,
}

# ---------------- WEBSITE PREDICTION ----------------
@app.post("/predict")
async def predict(req: Request):
    if not model or not db:
        return JSONResponse({"error": "Service unavailable"}, status_code=503)

    body = await req.json()
    department = body.get("department")
    date = body.get("date")

    if not department or not date:
        return JSONResponse({"error": "Missing inputs"}, status_code=400)

    if department not in DEPT_MAP:
        return JSONResponse({"error": "Invalid department"}, status_code=400)

    try:
        weekday = datetime.strptime(date, "%Y-%m-%d").weekday()
    except Exception:
        return JSONResponse({"error": "Invalid date format"}, status_code=400)

    # 🔹 FIXED FIELD NAME (matches WhatsApp booking)
    existing = (
        db.collection("patients")
        .where("Department", "==", department)
        .where("Date", "==", date)
        .stream()
    )

    existing_count = sum(1 for _ in existing)

    chart_data = []
    total_predicted = 0

    # 🔹 Hourly prediction (10 AM – 4 PM)
    for hour in range(10, 16):
        df = pd.DataFrame({
            "weekday": [weekday],
            "hour": [hour],
            "dept_code": [DEPT_MAP[department]],
            "existing_patients": [existing_count],
        })

        prediction = int(max(model.predict(df)[0], 0))
        total_predicted += prediction

        chart_data.append({
            "hour": f"{hour}:00",
            "predicted": prediction
        })

    return {
        "chartData": chart_data,
        "totalPatients": total_predicted,
        "alreadyBooked": existing_count
    }

# ---------------- LOAD WHATSAPP ROUTER ----------------
# ⚠️ DO NOT TOUCH – WhatsApp logic stays same
from webhook import router
app.include_router(router)
