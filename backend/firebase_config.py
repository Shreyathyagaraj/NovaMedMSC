import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

def init_firebase():
    if not firebase_admin._apps:

        firebase_json = os.getenv("FIREBASE_CREDENTIALS")

        if not firebase_json:
            raise Exception("❌ FIREBASE_CREDENTIALS env variable missing")

        try:
            cred_dict = json.loads(firebase_json)
            cred = credentials.Certificate(cred_dict)
        except Exception as e:
            raise Exception("❌ Invalid FIREBASE_CREDENTIALS JSON. Fix env variable.") from e

        firebase_admin.initialize_app(cred)

    return firestore.client()
