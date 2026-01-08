import os, json, logging
import firebase_admin
from firebase_admin import credentials, firestore

logger = logging.getLogger("firebase")

def get_db():
    try:
        if not firebase_admin._apps:
            sa = os.getenv("FIREBASE_CREDENTIALS")
            if not sa:
                raise ValueError("FIREBASE_CREDENTIALS missing")

            cred = credentials.Certificate(json.loads(sa))
            firebase_admin.initialize_app(cred)

        return firestore.client()

    except Exception as e:
        logger.error("🔥 Firebase init failed: %s", e)
        return None
