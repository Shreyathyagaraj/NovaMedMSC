import os
import json
import logging
import firebase_admin
from firebase_admin import credentials, firestore

logger = logging.getLogger("app")

def init_firebase():
    if firebase_admin._apps:
        logger.info("🔥 Firebase already initialized — skipping re-init")
        return firestore.client()

    firebase_json = os.getenv("FIREBASE_CREDENTIALS")

    if firebase_json:
        logger.info("🔥 FIREBASE_CREDENTIALS FOUND in environment")

        try:
            cred_dict = json.loads(firebase_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            logger.info("✅ Firebase initialized successfully")
            return firestore.client()

        except Exception as e:
            logger.error(f"❌ Firebase init failed from ENV: {e}")
            raise

    # ❗ DO NOT load from file — prevent fallback
    logger.error("❌ FIREBASE_CREDENTIALS missing. Refusing to load from file.")
    raise ValueError("FIREBASE_CREDENTIALS missing")
