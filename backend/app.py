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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

# ---------------- FIREBASE INIT (ONCE) ----------------
db = None
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    import os, json

    if not firebase_admin._apps:
        sa = os.getenv("FIREBASE_CREDENTIALS")
        if not sa:
            raise ValueError("FIREBASE_CREDENTIALS missing")

        cred = credentials.Certificate(json.loads(sa))
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    logger.info("✅ Firebase initialized")

except Exception as e:
    logger.warning("⚠️ Firebase disabled: %s", e)

# ---------------- ROUTERS (SAFE) ----------------
try:
    from webhook import router as whatsapp_router
    app.include_router(whatsapp_router)
    logger.info("✅ WhatsApp webhook loaded")
except Exception as e:
    logger.warning("⚠️ WhatsApp webhook disabled: %s", e)

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- ROOT ----------------
@app.get("/")
def home():
    return {"status": "NovaMed backend running"}

# ---------------- LOAD MODEL ----------------
MODEL_PATH = "xgb_patient_model.pkl"
model = None

try:
    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)
    logger.info("✅ Prediction model loaded")
except Exception as e:
    logger.warning("⚠️ Model not loaded: %s", e)

# ---------------- PATIENT ID (FIRESTORE) ----------------
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

# ---------------- REGISTER PATIENT ----------------
@app.post("/register_patient")
async def register_patient(request: Request):
    if not db:
        return JSONResponse(
            {"error": "Database unavailable"},
            status_code=503
        )

    try:
        payload = await request.json()
        pid = generate_patient_id()

        payload.update({
            "PatientID": pid,
            "created_at": datetime.utcnow().isoformat()
        })

        db.collection("patients").document(pid).set(payload)

        return {"status": "success", "PatientID": pid}

    except Exception as e:
        logger.exception("❌ register_patient failed")
        return JSONResponse({"error": str(e)}, status_code=500)

# ---------------- PREDICTION API ----------------
@app.post("/predict")
async def predict(request: Request):
    if model is None:
        return JSONResponse(
            {"error": "Prediction model unavailable"},
            status_code=500
        )

    try:
        body = await request.json()
        date = body.get("date")
        department = body.get("department")

        if not date or not department:
            return JSONResponse(
                {"error": "date and department required"},
                status_code=400
            )

        dept_mapping = {
            "Cardiology": 1,
            "Neurology": 2,
            "Orthopedics": 3,
            "Pediatrics": 4,
            "General Medicine": 5,
            "Dermatology": 6
        }

        if department not in dept_mapping:
            return JSONResponse(
                {"error": "Invalid department"},
                status_code=400
            )

        weekday = datetime.strptime(date, "%Y-%m-%d").weekday()

        df = pd.DataFrame({
            "weekday": [weekday] * 24,
            "hour": list(range(24)),
            "dept_code": [dept_mapping[department]] * 24
        })

        preds = model.predict(df)
        preds = np.maximum(preds, 0).astype(int)

        return {
            "department": department,
            "totalPatients": int(preds.sum()),
            "chartData": [
                {"hour": f"{h}:00", "predicted": int(p)}
                for h, p in zip(range(24), preds)
            ]
        }

    except Exception as e:
        logger.exception("❌ Prediction failed")
        return JSONResponse({"error": str(e)}, status_code=500)
