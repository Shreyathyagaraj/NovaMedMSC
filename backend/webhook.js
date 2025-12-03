// backend/functions/webhook.js
const admin = require("firebase-admin");
const fetch = require("node-fetch");
const chrono = require("chrono-node");

// -------------------- Firebase init --------------------
admin.initializeApp({
  credential: admin.credential.cert({
    projectId: process.env.FIREBASE_PROJECT_ID,
    clientEmail: process.env.FIREBASE_CLIENT_EMAIL,
    privateKey: process.env.FIREBASE_PRIVATE_KEY?.replace(/\\n/g, "\n"),
  }),
});

const db = admin.firestore();

// -------------------- Department definitions --------------------
const departmentSlots = {
  Cardiology: { times: ["09:00", "12:00"], capacity: 10 },
  Neurology: { times: ["14:00", "17:00"], capacity: 8 },
  Orthopedics: { times: ["10:00", "13:00"], capacity: 6 },
  Pediatrics: { times: ["15:00", "18:00"], capacity: 12 },
  "General Medicine": { times: ["09:00", "12:00"], capacity: 10 },
  Dermatology: { times: ["09:00", "18:00"], capacity: 15 },
};

// -------------------- Helpers --------------------
async function sendWhatsAppMessage(to, text) {
  const url = `https://graph.facebook.com/v20.0/${process.env.PHONE_NUMBER_ID}/messages`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.WHATSAPPS_TOKEN}`, // or WHATSAPP_TOKEN
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      messaging_product: "whatsapp",
      to,
      text: { body: text },
    }),
  });

  const result = await res.json();
  console.log("WhatsApp API response:", result);
}


async function getState(sender) {
  const doc = await db.collection("registration_states").doc(sender).get();
  if (!doc.exists) return { step: null, data: {}, updatedAt: null };

  const data = doc.data();
  if (data.updatedAt) {
    const ageMs = Date.now() - data.updatedAt.toMillis();
    if (ageMs > 30 * 60 * 1000) {
      await resetState(sender);
      return { step: null, data: {}, updatedAt: null };
    }
  }
  return data;
}

async function setState(sender, state) {
  await db.collection("registration_states").doc(sender).set({
    ...state,
    updatedAt: admin.firestore.Timestamp.now(),
  });
}

async function resetState(sender) {
  await db.collection("registration_states").doc(sender).delete().catch(() => {});
}

async function generatePatientId(transaction) {
  const counterRef = db.collection("metadata").doc("patient_counter");
  const snap = await transaction.get(counterRef);
  let count = 1000;
  if (snap.exists) count = (snap.data().count || 1000) + 1;
  else count = 1001;
  transaction.set(counterRef, { count }, { merge: true });
  return `P${count}`;
}

// -------------------- NLP helpers --------------------
function isGreeting(text) {
  return /\b(hi|hey|hello|hii|hy)\b/i.test(text);
}
function normalizeGender(text) {
  const t = text.toLowerCase();
  if (t.includes("male") || t === "m") return "Male";
  if (t.includes("female") || t === "f") return "Female";
  if (t.includes("other") || t.includes("prefer not") || t === "o") return "Other";
  return null;
}
function validatePhone(text) {
  const normalized = text.replace(/[^\d\+]/g, "");
  if (/\+?\d{10,14}/.test(normalized)) return normalized;
  return null;
}
function validateEmail(text) {
  return /\S+@\S+\.\S+/.test(text) ? text : null;
}
function normalizeDepartment(text) {
  if (!text) return null;
  const input = text.toLowerCase();
  const list = Object.keys(departmentSlots);
  return list.find((d) => input.includes(d.toLowerCase())) || null;
}
function extractNameFromSentence(text) {
  let m = text.match(/\bmy name is ([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)/i);
  if (m) return m[1].trim();
  m = text.match(/\bi am ([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)/i);
  if (m) return m[1].trim();
  m = text.match(/\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\b/);
  return m ? m[1] : null;
}
function extractPhone(text) {
  const m = text.match(/(\+?\d[\d\-\s]{8,}\d)/);
  return m ? validatePhone(m[1]) : null;
}
function extractEmail(text) {
  const m = text.match(/([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})/);
  return m ? m[1] : null;
}
function extractDateTime(text) {
  const parsed = chrono.parse(text);
  if (!parsed || parsed.length === 0) return {};
  const p = parsed[0];
  const date = p.start ? p.start.date() : null;
  let dateStr = null;
  let timeStr = null;
  if (date) {
    dateStr = date.toISOString().split("T")[0];
    if (p.start.isOnlyDate === false) {
      const hh = date.getHours().toString().padStart(2, "0");
      const mm = date.getMinutes().toString().padStart(2, "0");
      timeStr = `${hh}:${mm}`;
    }
  }
  return { date: dateStr, time: timeStr };
}
function hoursBetween(startHHMM, endHHMM) {
  const s = parseInt(startHHMM.split(":")[0], 10);
  const e = parseInt(endHHMM.split(":")[0], 10);
  const arr = [];
  for (let h = s; h <= e; h++) {
    arr.push(h.toString().padStart(2, "0") + ":00");
  }
  return arr;
}
function parseChoice(text) {
  const m = text.match(/\b([1-9][0-9]?)\b/);
  return m ? parseInt(m[1], 10) : null;
}

// -------------------- Registration --------------------
async function attemptRegistration(data) {
  if (!data.department) throw new Error("Department missing.");
  const dept = departmentSlots[data.department];
  if (!dept) throw new Error("Invalid department.");

  // ✅ Accept any generated time between start and end
  const validTimes = hoursBetween(dept.times[0], dept.times[1]);
  if (!validTimes.includes(data.registrationTime)) {
    throw new Error("Selected time not allowed for the department.");
  }

  const slotId = `${data.department}_${data.registrationDate}_${data.registrationTime}`;
  const slotRef = db.collection("appointments").doc(slotId);
  let patientId = null;

  await db.runTransaction(async (tx) => {
    const slotSnap = await tx.get(slotRef);
    const currentCount = slotSnap.exists ? (slotSnap.data().count || 0) : 0;
    if (currentCount >= dept.capacity) throw new Error("Slot full");

    patientId = await generatePatientId(tx);

    const patientRef = db.collection("patients").doc(patientId);
    tx.set(patientRef, {
      PatientID: patientId,
      FirstName: data.firstName || "",
      LastName: data.lastName || "",
      Gender: data.gender || "",
      Address: data.address || "",
      Email: data.email || "",
      PhoneNumber: data.phoneNumber || "",
      department: data.department,
      RegistrationDate: data.registrationDate,
      RegistrationTime: data.registrationTime,
      createdAt: admin.firestore.Timestamp.now(),
    });

    const newCount = currentCount + 1;
    const newPatients = slotSnap.exists ? [...(slotSnap.data().patients || []), patientId] : [patientId];
    tx.set(slotRef, {
      department: data.department,
      date: data.registrationDate,
      time: data.registrationTime,
      capacity: dept.capacity,
      count: newCount,
      patients: newPatients,
    }, { merge: true });
  });

  return patientId;
}

// -------------------- Conversation --------------------
async function processMessage(sender, text) {
  text = (text || "").trim();

  if (isGreeting(text)) {
    await sendWhatsAppMessage(sender, "Welcome to NovaMed Multispeciality Care 👋\nSay 'patient registration' to begin, or send details in one sentence.");
    return;
  }

  let state = await getState(sender);

  // ✅ NLP bootstrap: accept partial details
  if (!state.step) {
    const phone = extractPhone(text);
    const email = extractEmail(text);
    const name = extractNameFromSentence(text);
        const dept = normalizeDepartment(text);
    const gender = normalizeGender(text);
    const dt = extractDateTime(text);

    // If user typed "patient registration" explicitly
    if (text.toLowerCase().includes("patient registration") || text.toLowerCase().includes("register me")) {
      state = { step: "firstName", data: {} };
      await setState(sender, state);
      await sendWhatsAppMessage(sender, "Welcome! Let's get you registered. What's your *First Name*?");
      return;
    }

    // ✅ NLP bootstrap: if we detect at least one field, prefill state
    if (phone || email || name || dept || dt.date || dt.time || gender) {
      state = { step: "firstName", data: {} };
      if (name) {
        state.data.firstName = name.split(" ")[0];
        state.data.lastName = name.split(" ").slice(1).join(" ");
      }
      if (phone) state.data.phoneNumber = phone;
      if (email) state.data.email = email;
      if (dept) state.data.department = dept;
      if (gender) state.data.gender = gender;
      if (dt.date) state.data.registrationDate = dt.date;
      if (dt.time) state.data.registrationTime = dt.time;
      await setState(sender, state);

      // If we have enough info, try registration directly
      if (state.data.phoneNumber && state.data.department && state.data.registrationDate && state.data.registrationTime && state.data.firstName) {
        try {
          const pid = await attemptRegistration(state.data);
          await sendWhatsAppMessage(sender, `✅ Registration complete! Patient ID: ${pid}\nDept: ${state.data.department}\nDate: ${state.data.registrationDate}\nTime: ${state.data.registrationTime}`);
          await resetState(sender);
          return;
        } catch (err) {
          await sendWhatsAppMessage(sender, `❌ ${err.message}. Let's continue step-by-step. What's your first name?`);
          state.step = "firstName";
          await setState(sender, state);
          return;
        }
      }

      // Otherwise continue interactively
      await sendWhatsAppMessage(sender, "Let's continue your registration. What's your *First Name*?");
      return;
    }

    // Not recognized
    await sendWhatsAppMessage(sender, "Say 'patient registration' to begin registration, or send your full details in one sentence.");
    return;
  }

  // There is an active conversation
  const s = state;
  const d = s.data || {};

  switch (s.step) {
    case "firstName": {
      d.firstName = text;
      s.step = "lastName";
      s.data = d;
      await setState(sender, s);
      await sendWhatsAppMessage(sender, "Thanks — last name please (or type '-' if none).");
      return;
    }

    case "lastName": {
      d.lastName = text === "-" ? "" : text;
      s.step = "gender";
      s.data = d;
      await setState(sender, s);
      await sendWhatsAppMessage(sender, "Select Gender:\n1. Male\n2. Female\n3. Other");
      return;
    }

    case "gender": {
      const choice = parseChoice(text);
      if (choice === 1) d.gender = "Male";
      else if (choice === 2) d.gender = "Female";
      else if (choice === 3) d.gender = "Other";
      else {
        const g = normalizeGender(text);
        if (g) d.gender = g;
        else {
          await sendWhatsAppMessage(sender, "Please select gender: 1 (Male), 2 (Female), 3 (Other).");
          return;
        }
      }
      s.step = "address";
      s.data = d;
      await setState(sender, s);
      await sendWhatsAppMessage(sender, "Please enter your address.");
      return;
    }

    case "address": {
      d.address = text;
      s.step = "email";
      s.data = d;
      await setState(sender, s);
      await sendWhatsAppMessage(sender, "Please enter your email (or type 'skip').");
      return;
    }

    case "email": {
      if (text.toLowerCase() === "skip") d.email = "";
      else {
        const e = validateEmail(text);
        if (!e) {
          await sendWhatsAppMessage(sender, "That doesn't look like a valid email. Please re-enter or type 'skip'.");
          return;
        }
        d.email = e;
      }
      s.step = "phoneNumber";
      s.data = d;
      await setState(sender, s);
      await sendWhatsAppMessage(sender, "Please enter your phone number (include country code).");
      return;
    }

    case "phoneNumber": {
      const p = validatePhone(text);
      if (!p) {
        await sendWhatsAppMessage(sender, "Invalid phone format. Please send a valid phone number.");
        return;
      }
      d.phoneNumber = p;
      s.step = "department";
      s.data = d;
      await setState(sender, s);

      const deptList = Object.keys(departmentSlots);
      let msg = "Select Department:\n";
      deptList.forEach((dep, i) => { msg += `${i+1}. ${dep}\n`; });
      await sendWhatsAppMessage(sender, msg);
      return;
    }

    case "department": {
      const choice = parseChoice(text);
      const deptList = Object.keys(departmentSlots);
      if (choice && choice >= 1 && choice <= deptList.length) {
        d.department = deptList[choice - 1];
      } else {
        const dept = normalizeDepartment(text);
        if (dept) d.department = dept;
        else {
          await sendWhatsAppMessage(sender, "Invalid department. Reply with the number or name.");
          return;
        }
      }
      s.step = "registrationDate";
      s.data = d;
      await setState(sender, s);
      await sendWhatsAppMessage(sender, "Enter registration date (e.g., 'tomorrow' or '2025-11-10').");
      return;
    }

    case "registrationDate": {
      const parsed = chrono.parseDate(text);
      if (!parsed) {
        await sendWhatsAppMessage(sender, "Couldn't parse a future date. Please enter again.");
        return;
      }
      const dateStr = parsed.toISOString().split("T")[0];
      const today = new Date().toISOString().split("T")[0];
      if (dateStr <= today) {
        await sendWhatsAppMessage(sender, "Please pick a future date.");
        return;
      }
      d.registrationDate = dateStr;
      s.step = "registrationTime";
      s.data = d;
      await setState(sender, s);

      // ✅ Show remaining slots
      const times = hoursBetween(...departmentSlots[d.department].times);
      let msg = `Available times for ${d.department} on ${d.registrationDate}:\n`;

      for (let idx = 0; idx < times.length; idx++) {
        const slotId = `${d.department}_${d.registrationDate}_${times[idx]}`;
        const slotSnap = await db.collection("appointments").doc(slotId).get();
        const count = slotSnap.exists ? slotSnap.data().count || 0 : 0;

    // 🔑 Use doctorLimits for capacity
        const capacity = doctorLimits[d.department] || departmentSlots[d.department].capacity;
        const remaining = capacity - count;

        msg += `${idx+1}. ${times[idx]} (Remaining: ${remaining})\n`;
      }

      msg += "Reply with the number or the time (e.g., 10:00).";
      await sendWhatsAppMessage(sender, msg);
      return;


    }

    case "registrationTime": {
      const times = hoursBetween(...departmentSlots[d.department].times);
      const choice = parseChoice(text);
      if (choice && choice >= 1 && choice <= times.length) {
        d.registrationTime = times[choice - 1];
      } else {
        let candidateTime = text.trim();
        if (/^\d{1,2}$/.test(candidateTime)) candidateTime = candidateTime.padStart(2, "0") + ":00";
        const dt = chrono.parseDate(candidateTime);
        if (dt) candidateTime = dt.getHours().toString().padStart(2, "0") + ":00";
        if (times.includes(candidateTime)) d.registrationTime = candidateTime;
        else {
          await sendWhatsAppMessage(sender, `Invalid time. Choose from the options sent.`);
          return;
        }
      }

      try {
        const pid = await attemptRegistration(d);
        await sendWhatsAppMessage(sender, `✅ Registration successful!\nPatient ID: ${pid}\nDepartment: ${d.department}\nDate: ${d.registrationDate}\nTime: ${d.registrationTime}`);
        await resetState(sender);
      } catch (err) {
        await sendWhatsAppMessage(sender, `❌ ${err.message}. Please choose a different time or date.`);
        s.step = "registrationTime";
        s.data = d;
        await setState(sender, s);
      }
      return;
    }

    default:
      await resetState(sender);
      await sendWhatsAppMessage(sender, "Session reset. Say 'patient registration' to begin again.");
      return;
  }
}

// -------------------- Fire function handler --------------------
// -------------------- Fire function handler --------------------
exports.handler = async (event) => {
  try {
    if (event.httpMethod === "GET") {
      // Verification handshake for Meta
      const VERIFY_TOKEN = process.env.VERIFY_TOKEN || "shreyaWebhook123";
      const params = event.queryStringParameters || {};
      if (params["hub.mode"] === "subscribe" && params["hub.verify_token"] === VERIFY_TOKEN) {
        return { statusCode: 200, body: params["hub.challenge"] };
      }
      return { statusCode: 403, body: "Forbidden" };
    }

    if (event.httpMethod === "POST") {
      const body = JSON.parse(event.body || "{}");
      const message = body?.entry?.[0]?.changes?.[0]?.value?.messages?.[0];
      if (!message || !message.text) {
        return { statusCode: 200, body: "No message found" };
      }

      const sender = message.from;
      const text = message.text.body.trim();
      console.log("Incoming message from", sender, ":", text);

      await processMessage(sender, text);
      return { statusCode: 200, body: "OK" };
    }

    return { statusCode: 404, body: "Not Found" };
  } catch (err) {
    console.error("Webhook error:", err);
    return { statusCode: 500, body: "Internal Server Error" };
  }
};

