import os
from firebase_admin import credentials, firestore, initialize_app, _apps

def init_firebase():
    if _apps:
        return firestore.client()

    # Absolute path (works in Windows + VS Code + Uvicorn)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cred_path = os.path.join(base_dir, "serviceAccountKey.json")

    if not os.path.exists(cred_path):
        raise ValueError(f"serviceAccountKey.json not found at {cred_path}")

    cred = credentials.Certificate(cred_path)
    initialize_app(cred)

    return firestore.client()
