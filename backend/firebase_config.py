import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

def init_firebase():
    if not firebase_admin._apps:
        firebase_json = os.getenv("FIREBASE_CREDENTIALS")

        if firebase_json:
            print("🔥 FIREBASE_CREDENTIALS FOUND in environment")
            try:
                cred_dict = json.loads(firebase_json)
                cred = credentials.Certificate(cred_dict)
            except Exception as e:
                print("❌ ERROR parsing Firebase JSON:", e)
                raise
        else:
            print("❌ FIREBASE_CREDENTIALS NOT FOUND in environment!")
            raise Exception("FIREBASE_CREDENTIALS missing")

        firebase_admin.initialize_app(cred)
        print("✅ Firebase initialized successfully")

    return firestore.client()
