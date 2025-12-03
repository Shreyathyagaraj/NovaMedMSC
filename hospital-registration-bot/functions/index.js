const functions = require("firebase-functions");
const admin = require("firebase-admin");
const chrono = require("chrono-node");

// Initialize Firebase Admin once
if (!admin.apps.length) {
  const cfg = functions.config();
  admin.initializeApp({
    credential: admin.credential.cert({
      projectId: cfg.firebase.project_id,
      clientEmail: cfg.firebase.client_email,
      privateKey: cfg.firebase.private_key?.replace(/\\n/g, "\n"),
    }),
  });
}

const db = admin.firestore();

// Department slot ranges and capacity
const departmentSlots = {
  Cardiology: { range: ["09:00", "12:00"], capacity: 10 },
  Neurology: { range: ["14:00", "17:00"], capacity: 8 },
  Orthopedics: { range: ["10:00", "13:00"], capacity: 6 },
  Pediatrics: { range: ["15:00", "18:00"], capacity: 12 },
  "General Medicine": { range: ["09:00", "12:00"], capacity: 10 },
  Dermatology: { range: ["09:00", "18:00"], capacity: 15 },
};

// Generate hourly slots between start and end inclusive
function generateTimeSlots(start, end) {
  const slots = [];
  let current = new Date(`1970-01-01T${start}:00`);
  const endTime = new Date(`1970-01-01T${end}:00`);
  while (current <= endTime) {
    slots.push(current.toTimeString().slice(0, 5));
    current.setHours(current.getHours() + 1);
  }
  return slots;
}

// Helpers: state management with 30-min auto reset
async function getState(sender) {
  const doc = await db.collection("registration_states").doc(sender).get();
  if (!doc.exists) return { step: null, data: {}, lastActive: null };

  const state = doc.data();
  if (state.lastActive) {
    const now = Date.now();
    const diffMinutes = (now - state.lastActive.toMillis()) / (1000 * 60);
    if (diffMinutes > 30) {
      await resetState(sender);
      return { step: null, data: {}, lastActive: null };
    }
  }
  return state;
}

async function setState(sender, state) {
  await db.collection("registration_states").doc(sender).set({
    ...state,
    lastActive: admin.firestore.Timestamp.now(),
  });
}

async function resetState(sender) {
  await db.collection("registration_states").doc(sender).delete().catch(() => {});
}

// NLP helpers
function parseFutureDate(text) {
  const parsed = chrono.parseDate(text);
  if (!parsed) return null;
  const ymd = new Date(parsed).toISOString().split("T")[0];
  const today = new Date().toISOString().split("T")[0];
  return ymd > today ? ymd : null;
}

function normalizeDepartment(text) {
  const input = text.toLowerCase();
  const list = Object.keys(departmentSlots);
  return list.find((d) => input.includes(d.toLowerCase())) || null;
}

function normalizeTimeForDepartment(department, text) {
  const times = generateTimeSlots(...departmentSlots[department].range);
  const key = text.trim().toLowerCase();
  // accept "10", "10 am", "10:00"
  const alias = {
    "9": "09:00", "9 am": "09:00", "09:00": "09:00",
    "10": "10:00", "10 am": "10:00", "10:00": "10:00",
    "11": "11:00", "11 am": "11:00", "11:00": "11:00",
    "12": "12:00", "12 pm": "12:00", "12:00": "12:00",
    "1": "13:00", "1 pm": "13:00", "13:00": "13:00",
    "2": "14:00", "2 pm": "14:00", "14:00": "14:00",
    "3": "15:00", "3 pm": "15:00", "15:00": "15:00",
    "5": "17:00", "5 pm": "17:00", "17:00": "17:00",
    "6": "18:00", "6 pm": "18:00", "18:00": "18:00",
  };
  const normalized = alias[key] || key;
  return times.includes(normalized) ? normalized : null;
}

// NLP shortcut parser: one-sentence booking
function parseFullSentence(text) {
  const lower = text.toLowerCase();
  const department = normalizeDepartment(text);
  const date = parseFutureDate(text);

  let time = null;
  const chronoDate = chrono.parseDate(text);
  if (chronoDate) {
    time = chronoDate.toTimeString().slice(0, 5);
  }
  if (!time && department) {
    const match = lower.match(/\b([0-2]?\d:[0-5]\d|\d{1,2}\s?(am|pm))\b/);
    if (match) {
      time = normalizeTimeForDepartment(department, match[0]);
    }
  }

  let gender = null;
  if (lower.includes("male")) gender = "Male";
  else if (lower.includes("female")) gender = "Female";
  else if (lower.includes("other")) gender = "Other";

  return { department, date, time, gender };
}

// WhatsApp senders
async function sendWhatsAppText(to, text) {
  const cfg = functions.config();
  const url = `https://graph.facebook.com/v20.0/${cfg.whatsapp.phone_number_id}/messages`;
  await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${cfg.whatsapp.token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      messaging_product: "whatsapp",
      to,
      text: { body: text },
    }),
  });
}

async function sendButtons(to, bodyText, options) {
  const cfg = functions.config();
  const url = `https://graph.facebook.com/v20.0/${cfg.whatsapp.phone_number_id}/messages`;
  await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${cfg.whatsapp.token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      messaging_product: "whatsapp",
      to,
      type: "interactive",
      interactive: {
        type: "button",
        body: { text: bodyText },
        action: {
          buttons: options.map((opt) => ({
            type: "reply",
            reply: { id: opt, title: opt },
          })),
        },
      },
    }),
  });
}

// Sequential Patient ID generator: P1000, P1001, ...
async function generatePatientId() {
  const counterRef = db.collection("counters").doc("patients");
  let newId;
  await db.runTransaction(async (tx) => {
    const snap = await tx.get(counterRef);
    let current = snap.exists ? snap.data().count : 1000;
    newId = `P${current}`;
    tx.set(counterRef, { count: current + 1 });
  });
  return newId;
}

// Registration attempt
async function attemptRegistration(data) {
  const { department, registrationDate, registrationTime } = data;
  const dept = departmentSlots[department];
  if (!dept) throw new Error("Invalid department.");

  const slotId = `${department}_${registrationDate}_${registrationTime}`;
  const slotRef = db.collection("appointments").doc(slotId);
  const patientId = await generatePatientId();

  await db.runTransaction(async (tx) => {
    const slotSnap = await tx.get(slotRef);
    const currentCount = slotSnap.exists ? (slotSnap.data().count || 0) : 0;

    if (currentCount >= dept.capacity) {
      throw new Error(`Slot full for ${department} at ${registrationTime} on ${registrationDate}.`);
    }

    const patientRef = db.collection("patients").doc(patientId);
    tx.set(patientRef, {
      patientId,
      firstName: data.firstName,
      lastName: data.lastName,
      gender: data.gender,
      address: data.address,
      email: data.email,
      phoneNumber: data.phoneNumber,
      department,
      registrationDate,
      registrationTime,
      createdAt: new Date(),
    });

    const newCount = currentCount + 1;
    const newPatients = slotSnap.exists
      ? [...(slotSnap.data().patients || []), patientId]
      : [patientId];

    tx.set(
      slotRef,
      {
        department,
        date: registrationDate,
        time: registrationTime,
        capacity: dept.capacity,
        count: newCount,
        patients: newPatients,
      },
      { merge: true }
    );
  });

  return patientId;
}

// Main HTTP function for WhatsApp webhook
exports.webhook = functions.https.onRequest(async (req, res) => {
  const cfg = functions.config();

  try {
    if (req.method === "GET") {
      const mode = req.query["hub.mode"];
      const token = req.query["hub.verify_token"];
      const challenge = req.query["hub.challenge"];
      if (mode === "subscribe" && token === cfg.verify.token) {
        return res.status(200).send(challenge);
      }
      return res.status(403).send("Forbidden");
    }

    if (req.method === "POST") {
      const message = req.body?.entry?.[0]?.changes?.[0]?.value?.messages?.[0];
      if (!message) return res.status(200).send("No message");

      const sender = message.from;
      const text =
        (message.text?.body || message.button?.text || "").trim().toLowerCase();

      // Greetings
      if (text === "hi" || text === "hello") {
        await sendWhatsAppText(sender, "Welcome to Novamed Multispeciality Care");
        return res.status(200).send("OK");
      }

      // NLP shortcut
      let state = await getState(sender);
      if (!state.step) {
        const parsed = parseFullSentence(text);
        if (parsed.department && parsed.date && parsed.time) {
          const patientId = await attemptRegistration({
            firstName: "Unknown",
            lastName: "Unknown",
            gender: parsed.gender || "Other",
            address: "Unknown",
            email: "Unknown",
            phoneNumber: sender,
            department: parsed.department,
            registrationDate: parsed.date,
            registrationTime: parsed.time,
          });
          await sendWhatsAppText(
            sender,
            `✅ Quick booking successful!\nPatient ID: ${patientId}\nDepartment: ${parsed.department}\nDate: ${parsed.date}\nTime: ${parsed.time}`
          );
          return res.status(200).send("OK");
        }
      }

      // Step-by-step flow
      if (!state.step) {
        if (text.includes("patient registration")) {
          state = { step: "firstName", data: {} };
          await setState(sender, state);
          await sendWhatsAppText(sender, "Welcome! Please enter your First Name.");
          return res.status(200).send("OK");
        } else {
          await sendWhatsAppText(sender, "Say 'patient registration' to begin.");
          return res.status(200).send("OK");
        }
      }

      switch (state.step) {
        case "firstName":
          state.data.firstName = message.text?.body || "";
          state.step = "lastName";
          await setState(sender, state);
          await sendWhatsAppText(sender, "Thanks! Please enter your Last Name.");
          break;

        case "lastName":
          state.data.lastName = message.text?.body || "";
          state.step = "gender";
          await setState(sender, state);
          await sendButtons(sender, "Select Gender:", ["Male", "Female", "Other"]);
          break;

        case "gender":
          state.data.gender = (message.text?.body || message.button?.text || "Other").trim();
          state.step = "address";
          await setState(sender, state);
          await sendWhatsAppText(sender, "Please enter your Address.");
          break;

        case "address":
          state.data.address = message.text?.body || "";
          state.step = "email";
          await setState(sender, state);
          await sendWhatsAppText(sender, "Please enter your Email.");
          break;

        case "email":
          {
            const raw = message.text?.body || "";
            if (!/\S+@\S+\.\S+/.test(raw)) {
              await sendWhatsAppText(sender, "Invalid email. Please re-enter your Email.");
              break;
            }
            state.data.email = raw;
            state.step = "phoneNumber";
            await setState(sender, state);
            await sendWhatsAppText(sender, "Please enter your Phone Number.");
          }
          break;

        case "phoneNumber":
          {
            const raw = (message.text?.body || "").replace(/\s+/g, "");
            if (!/\+?\d{10,}/.test(raw)) {
              await sendWhatsAppText(sender, "Invalid phone. Please re-enter your Phone Number.");
              break;
            }
            state.data.phoneNumber = raw;
            state.step = "department";
            await setState(sender, state);
            await sendButtons(sender, "Select Department:", Object.keys(departmentSlots));
          }
          break;

        case "department":
          {
            const dept = normalizeDepartment(message.text?.body || message.button?.text || "");
            if (!dept) {
              await sendWhatsAppText(sender, "Invalid department. Please choose again.");
              break;
            }
            state.data.department = dept;
            state.step = "registrationDate";
            await setState(sender, state);
            await sendWhatsAppText(sender, "Enter Registration Date (e.g., 'tomorrow' or '2025-11-10').");
          }
          break;

        case "registrationDate":
          {
            const raw = message.text?.body || "";
            const date = parseFutureDate(raw);
            if (!date) {
              await sendWhatsAppText(sender, "Invalid date. Please enter a future date.");
              break;
            }
            state.data.registrationDate = date;
            state.step = "registrationTime";
            const slots = generateTimeSlots(...departmentSlots[state.data.department].range);
            await setState(sender, state);
            await sendButtons(sender, `Available times for ${state.data.department}:`, slots);
          }
          break;

        case "registrationTime":
          {
            const raw = message.text?.body || message.button?.text || "";
            const normalized = normalizeTimeForDepartment(state.data.department, raw);
            if (!normalized) {
              const slots = generateTimeSlots(...departmentSlots[state.data.department].range);
              await sendWhatsAppText(sender, `Invalid time. Available times: ${slots.join(", ")}`);
              break;
            }
            state.data.registrationTime = normalized;

            try {
              const patientId = await attemptRegistration(state.data);
              await sendWhatsAppText(
                sender,
                `✅ Registration successful!\nPatient ID: ${patientId}\nDepartment: ${state.data.department}\nDate: ${state.data.registrationDate}\nTime: ${state.data.registrationTime}`
              );
              await resetState(sender);
            } catch (err) {
              await sendWhatsAppText(sender, `❌ ${err.message}\nPlease choose another time.`);
            }
          }
          break;

        default:
          await resetState(sender);
          await sendWhatsAppText(sender, "Session reset. Say 'patient registration' to begin again.");
      }

      return res.status(200).send("OK");
    }

    return res.status(404).send("Not Found");
  } catch (err) {
    console.error("Webhook error:", err);
    return res.status(500).send("Internal Server Error");
  }
});
