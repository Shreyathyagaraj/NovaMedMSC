import admin from "firebase-admin";
import fs from "fs";

const serviceAccount = JSON.parse(fs.readFileSync("./serviceAccountKey.json"));

admin.initializeApp({
  credential: admin.credential.cert(serviceAccount),
});

const db = admin.firestore();

async function migrateAndFixPatients() {
  const patientsRef = db.collection("patients");
  const snapshot = await patientsRef.get();

  if (snapshot.empty) {
    console.log("No patients found.");
    return;
  }

  let counter = 1;
  for (const doc of snapshot.docs) {
    let data = doc.data();

    // 🔹 Fix schema: detect "wrong" mapping
    const cleaned = {
  patient_id: `P${String(counter).padStart(3, "0")}`,
  first_name: doc.data().first_name || "",
  last_name: doc.data().last_name || "",
  gender: doc.data().gender || "",
  address: doc.data().address || "",
  contact_number: doc.data().contact_number || "",
  email: doc.data().email || "",
  registration_date: doc.data().registration_date || "",
};


    const newId = `P${String(counter).padStart(3, "0")}`;

    await db.collection("patients").doc(newId).set(cleaned);
    await doc.ref.delete();

    console.log(`Fixed & Migrated ${doc.id} → ${newId}`);
    counter++;
  }
  console.log("✅ Migration & Cleanup complete!");
}

migrateAndFixPatients().catch(console.error);
