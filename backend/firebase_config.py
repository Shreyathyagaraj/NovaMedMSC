import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

def init_firebase():
    if not firebase_admin._apps:
        # If running on Render, use env variable
        firebase_json = os.getenv("FIREBASE_CREDENTIALS")

        if firebase_json:
            cred_dict = json.loads(firebase_json)
            cred = credentials.Certificate(cred_dict)
        else:
            # Local development fallback
            cred = credentials.Certificate("firebase_key.json")

        firebase_admin.initialize_app(cred)

    return firestore.client()
