// migratePatients.js
import admin from "firebase-admin";
import fs from "fs";

// Load service account key
const serviceAccount = JSON.parse(fs.readFileSync("./serviceAccountKey.json"));

// Initialize Firebase Admin
admin.initializeApp({
  credential: admin.credential.cert(serviceAccount)
});

const db = admin.firestore();

async function migratePatients() {
  const patientsRef = db.collection("patients");
  const snapshot = await patientsRef.get();

  if (snapshot.empty) {
    console.log("No patients found.");
    return;
  }

  let counter = 1;
  for (const doc of snapshot.docs) {
    const data = doc.data();
    const newId = `P${String(counter).padStart(3, "0")}`;

    // Write new doc with new ID
    await db.collection("patients").doc(newId).set(data);

    // Delete old doc
    await doc.ref.delete();

    console.log(`Migrated ${doc.id} → ${newId}`);
    counter++;
  }
  console.log("✅ Migration complete!");
}

migratePatients().catch(console.error);
