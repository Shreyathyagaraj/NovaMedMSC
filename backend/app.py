import logging
import pickle
from datetime import datetime

import pandas as pd
import numpy as np
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from webhook import router as whatsapp_router
from firebase_config import init_firebase

# ---------------- APP INIT ----------------
app = FastAPI(title="NovaMed Backend")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- FIREBASE ----------------
db = init_firebase()

# ---------------- ROUTERS ----------------
app.include_router(whatsapp_router)

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- ROOT ----------------
@app.get("/")
def home():
    return {"message": "NovaMed backend running"}

# ---------------- MODEL ----------------
MODEL_PATH = "xgb_patient_model.pkl"
model = None
try:
    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)
except:
    logger.warning("⚠️ Prediction model not loaded")

# ---------------- PREDICT ----------------
@app.post("/predict")
async def predict(request: Request):
    try:
        body = await request.json()
        target_date = body["date"]
        department = body["department"]

        dept_map = {
            "Cardiology": 1,
            "Neurology": 2,
            "Orthopedics": 3,
            "Pediatrics": 4,
            "General Medicine": 5,
            "Dermatology": 6
        }

        df = pd.DataFrame({
            "weekday": [datetime.strptime(target_date, "%Y-%m-%d").weekday()] * 24,
            "hour": range(24),
            "dept_code": [dept_map[department]] * 24
        })

        preds = model.predict(df)
        preds = np.maximum(preds, 0).round().astype(int)

        return {
            "department": department,
            "totalPatients": int(preds.sum()),
            "chartData": [{"hour": f"{h}:00", "predicted": int(p)} for h, p in zip(range(24), preds)]
        }

    except Exception as e:
        logger.exception("Prediction error")
        return JSONResponse({"error": str(e)}, status_code=500)
