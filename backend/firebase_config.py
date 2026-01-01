import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

def init_firebase():
    if firebase_admin._apps:
        return firestore.client()

    # 🔹 Prefer ENV variable (Render / Production)
    if "FIREBASE_SERVICE_ACCOUNT" in os.environ:
        cred_dict = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])
        cred = credentials.Certificate(cred_dict)

    else:
        # 🔹 Local fallback
        cred_path = os.path.join(os.path.dirname(__file__), "serviceAccountKey.json")
        if not os.path.exists(cred_path):
            raise ValueError(f"serviceAccountKey.json not found at {cred_path}")
        cred = credentials.Certificate(cred_path)

    firebase_admin.initialize_app(cred)
    return firestore.client()
