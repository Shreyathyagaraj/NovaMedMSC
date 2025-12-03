import pandas as pd
import time
import firebase_admin
from firebase_admin import credentials, firestore

# -------------------------
# Initialize Firebase
# -------------------------
cred = credentials.Certificate("serviceAccountKey.json")  # path to your Firebase service account key
firebase_admin.initialize_app(cred)
db = firestore.client()

# -------------------------
# Load and clean CSV
# -------------------------
csv_file = "patients.csv"   # path to your dataset
df = pd.read_csv(csv_file)

# Remove spaces or hidden chars from column names
df.columns = df.columns.str.strip()

print("Columns found in CSV:", df.columns.tolist())  # Debug check

# -------------------------
# Upload to Firestore with Patient IDs (slow mode)
# -------------------------
for idx, row in df.iterrows():
    patient_data = row.to_dict()

    # Create patient ID like P001, P002, ...
    patient_id = f"P{str(idx+1).zfill(3)}"

    # Upload with custom document ID
    db.collection("patients").document(patient_id).set(patient_data)

    print(f"✅ Uploaded {patient_id}")

    # Sleep to avoid quota exceeded (Spark plan allows ~1 write/sec)
    time.sleep(1.2)

print("🎉 Upload completed successfully! All patients stored with IDs like P001, P002...")
