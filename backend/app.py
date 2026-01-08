import logging, pickle
from datetime import datetime
import pandas as pd
import numpy as np
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from firebase_config import get_db

# ---------------- APP ----------------
app = FastAPI(title="NovaMed Backend")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

db = get_db()
if db:
    logger.info("✅ Firebase ready")
else:
    logger.warning("⚠️ Firebase unavailable")

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- ROUTERS ----------------
from webhook import router as whatsapp_router
app.include_router(whatsapp_router)

# ---------------- ROOT ----------------
@app.get("/")
def home():
    return {"status": "NovaMed backend running"}

# ---------------- MODEL ----------------
MODEL_PATH = "xgb_patient_model.pkl"
model = None

try:
    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)
    logger.info("✅ ML model loaded")
except Exception as e:
    logger.error("❌ Model load failed: %s", e)

# ---------------- DEPTS ----------------
DEPT_MAPPING = {
    "Cardiology": 1,
    "Neurology": 2,
    "Orthopedics": 3,
    "Pediatrics": 4,
    "General Medicine": 5,
    "Dermatology": 6,
}

# ---------------- REGISTER (WEBSITE) ----------------
@app.post("/register_patient")
async def register_patient(req: Request):
    if not db:
        return JSONResponse({"error": "DB unavailable"}, 503)

    data = await req.json()
    pid = f"P{int(datetime.utcnow().timestamp())}"

    data.update({
        "PatientID": pid,
        "createdAt": datetime.utcnow().isoformat()
    })

    db.collection("patients").document(pid).set(data)
    return {"status": "success", "PatientID": pid}

# ---------------- PREDICTION ----------------
@app.post("/predict")
async def predict(req: Request):
    if not model or not db:
        return JSONResponse({"error": "Prediction unavailable"}, 503)

    body = await req.json()
    dept = body.get("department")
    date = body.get("date")

    if dept not in DEPT_MAPPING:
        return JSONResponse({"error": "Invalid department"}, 400)

    weekday = datetime.strptime(date, "%Y-%m-%d").weekday()

    booked = db.collection("patients") \
        .where("Department", "==", dept) \
        .where("RegistrationDate", "==", date) \
        .stream()

    count = sum(1 for _ in booked)

    df = pd.DataFrame({
        "weekday": [weekday],
        "hour": [10],
        "dept_code": [DEPT_MAPPING[dept]],
        "existing_patients": [count]
    })

    pred = int(np.maximum(model.predict(df)[0], 0))

    return {
        "department": dept,
        "date": date,
        "alreadyBooked": count,
        "predictedPatients": pred
    }
