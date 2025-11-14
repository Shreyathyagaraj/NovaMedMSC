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
  await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.WHATSAPP_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      messaging_product: "whatsapp",
      to,
      text: { body: text },
    }),
  });
}

async function getState(sender) {
  const doc = await db.collection("registration_states").doc(sender).get();
  if (!doc.exists) return { step: null, data: {}, updatedAt: null };

  const data = doc.data();
  // Auto-reset if older than 30 minutes
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

// generate sequential Patient ID P1001, P1002...
async function generatePatientId(transaction) {
  const counterRef = db.collection("metadata").doc("patient_counter");
  const snap = await transaction.get(counterRef);
  let count = 1000;
  if (snap.exists) count = (snap.data().count || 1000) + 1;
  else count = 1001;
  transaction.set(counterRef, { count }, { merge: true });
  return `P${count}`;
}

// -------------------- Small NLP helpers --------------------
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
  // heuristic: look for "my name is X" or "I am X" or capitalized words
  let m = text.match(/\bmy name is ([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)/i);
  if (m) return m[1].trim();
  m = text.match(/\bi am ([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)/i);
  if (m) return m[1].trim();
  // fallback: take first capitalized word chunk
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
  // chrono will parse date/time
  const parsed = chrono.parse(text);
  if (!parsed || parsed.length === 0) return {};
  const p = parsed[0];
  const date = p.start ? p.start.date() : null;
  let dateStr = null;
  let timeStr = null;
  if (date) {
    dateStr = date.toISOString().split("T")[0];
    if (p.start.isOnlyDate === false) {
      // if there is a time part
      const hh = date.getHours().toString().padStart(2, "0");
      const mm = date.getMinutes().toString().padStart(2, "0");
      timeStr = `${hh}:${mm}`;
    }
  }
  return { date: dateStr, time: timeStr };
}

// get hour options between start and end inclusive, step 1 hour
function hoursBetween(startHHMM, endHHMM) {
  const s = parseInt(startHHMM.split(":")[0], 10);
  const e = parseInt(endHHMM.split(":")[0], 10);
  const arr = [];
  for (let h = s; h <= e; h++) {
    arr.push(h.toString().padStart(2, "0") + ":00");
  }
  return arr;
}

// parse if user sends numeric choice "1" or "2"
function parseChoice(text) {
  const m = text.match(/\b([1-9][0-9]?)\b/);
  return m ? parseInt(m[1], 10) : null;
}

// -------------------- Attempt registration (transactional) --------------------
async function attemptRegistration(data) {
  // data expected to contain: firstName, lastName, gender, address, email, phoneNumber, department, registrationDate, registrationTime
  if (!data.department) throw new Error("Department missing.");
  const dept = departmentSlots[data.department];
  if (!dept) throw new Error("Invalid department.");
  if (!dept.times.includes(data.registrationTime)) throw new Error("Selected time not allowed for the department.");

  const slotId = `${data.department}_${data.registrationDate}_${data.registrationTime}`;
  const slotRef = db.collection("appointments").doc(slotId);

  // Firestore transaction: allocate slot & insert patient doc with sequential P-id
  const patientDocRef = db.collection("patients").doc(); // will set id inside transaction
  let patientId = null;

  await db.runTransaction(async (tx) => {
    const slotSnap = await tx.get(slotRef);
    const currentCount = slotSnap.exists ? (slotSnap.data().count || 0) : 0;
    if (currentCount >= dept.capacity) throw new Error("Slot full");

    // generate sequential patient id
    patientId = await generatePatientId(tx);

    // create patient document with patientId as doc id (docRef using patientId)
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

    // update slot doc
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

// -------------------- Main conversation processor --------------------
async function processMessage(sender, text) {
  // Quick normalization
  text = (text || "").trim();

  // Greeting - respond with a friendly welcome
  if (isGreeting(text)) {
    await sendWhatsAppMessage(sender, "Welcome to NovaMed Multispeciality Care 👋\nSay 'patient registration' to begin, or send details in one sentence (e.g., 'I am Priya, phone +919876543210, cardiology tomorrow 10am').");
    return;
  }

  // Get state (auto-reset handled)
  let state = await getState(sender);

  // If no ongoing conversation, check if user sent single-sentence registration
  if (!state.step) {
    // Attempt to parse everything from the sentence
    const phone = extractPhone(text);
    const email = extractEmail(text);
    const name = extractNameFromSentence(text);
    const dept = normalizeDepartment(text);
    const gender = normalizeGender(text);
    const dt = extractDateTime(text);
    // if we have at least phone + department + date/time -> attempt full register
    if (phone && dept && dt.date && dt.time && name) {
      const payload = {
        firstName: name.split(" ")[0],
        lastName: name.split(" ").slice(1).join(" "),
        gender: gender || "Other",
        address: "",
        email: email || "",
        phoneNumber: phone,
        department: dept,
        registrationDate: dt.date,
        registrationTime: dt.time,
      };
      try {
        const pid = await attemptRegistration(payload);
        await sendWhatsAppMessage(sender, `✅ Registration complete! Patient ID: ${pid}\nDept: ${payload.department}\nDate: ${payload.registrationDate}\nTime: ${payload.registrationTime}\nThanks for registering at NovaMed.`);
        return;
      } catch (err) {
        // If attempt failed (slot full etc), fall back to starting interactive flow
        await sendWhatsAppMessage(sender, `I couldn't finish automatic registration: ${err.message}. Let's do this step-by-step. What's your first name?`);
        state = { step: "firstName", data: {} };
        await setState(sender, state);
        return;
      }
    }

    // If user typed "patient registration" phrase -> start flow
    if (text.toLowerCase().includes("patient registration") || text.toLowerCase().includes("register me") || text.toLowerCase().includes("i want to register")) {
      state = { step: "firstName", data: {} };
      await setState(sender, state);
      await sendWhatsAppMessage(sender, "Welcome! Let's get you registered. What's your *First Name*?");
      return;
    }

    // Not recognized: give helpful prompt
    await sendWhatsAppMessage(sender, "Say 'patient registration' to begin registration, or send your full details in one sentence (name, dept, date/time, phone).");
    return;
  }

  // There is an active conversation
  const s = state;
  const d = s.data || {};

  // Step handlers
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
      // Provide numbered options for gender (user can reply with 1/2/3 or text)
      await sendWhatsAppMessage(sender, "Select Gender:\n1. Male\n2. Female\n3. Other\n(Reply with the number or type the gender.)");
      return;
    }

    case "gender": {
      // Accept numeric choice
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
      await sendWhatsAppMessage(sender, "Please enter your address (city or full address).");
      return;
    }

    case "address": {
      d.address = text;
      s.step = "email";
      s.data = d;
      await setState(sender, s);
      await sendWhatsAppMessage(sender, "Please enter your email address (or type 'skip').");
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
      await sendWhatsAppMessage(sender, "Please enter your phone number (include country code or start with 0, e.g., +919876543210).");
      return;
    }

    case "phoneNumber": {
      const p = validatePhone(text);
      if (!p) {
        await sendWhatsAppMessage(sender, "Invalid phone format. Please send a valid phone number (digits, optional +).");
        return;
      }
      d.phoneNumber = p;
      s.step = "department";
      s.data = d;
      await setState(sender, s);

      // Send department choices numbered
      const deptList = Object.keys(departmentSlots);
      let msg = "Select Department (reply with number or name):\n";
      deptList.forEach((dep, i) => { msg += `${i+1}. ${dep}\n`; });
      await sendWhatsAppMessage(sender, msg);
      return;
    }

    case "department": {
      // handle numeric choice
      const choice = parseChoice(text);
      const deptList = Object.keys(departmentSlots);
      if (choice && choice >= 1 && choice <= deptList.length) {
        d.department = deptList[choice - 1];
      } else {
        const dept = normalizeDepartment(text);
        if (dept) d.department = dept;
        else {
          await sendWhatsAppMessage(sender, "Invalid department. Reply with the number or type the department name.");
          return;
        }
      }
      s.step = "registrationDate";
      s.data = d;
      await setState(sender, s);
      await sendWhatsAppMessage(sender, `Enter registration date (e.g., 'tomorrow' or '2025-11-10').`);
      return;
    }

    case "registrationDate": {
      // parse date using chrono
      const parsed = chrono.parseDate(text);
      if (!parsed) {
        await sendWhatsAppMessage(sender, "Couldn't parse a future date. Please enter a future date like 'tomorrow' or '2025-11-10'.");
        return;
      }
      // ensure future
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

      // Offer hour choices within department's schedule
      const times = departmentSlots[d.department].times;
      const hours = hoursBetween(times[0], times[1]); // e.g., ["09:00","10:00","11:00","12:00"]
      let msg = `Available times for ${d.department} on ${d.registrationDate}:\n`;
      hours.forEach((h, idx) => { msg += `${idx + 1}. ${h}\n`; });
      msg += "Reply with the number or the time (e.g., 10:00).";
      await sendWhatsAppMessage(sender, msg);
      return;
    }

    case "registrationTime": {
      const times = hoursBetween(...departmentSlots[d.department].times); // ensure we compute again
      // accept numeric choice
      const choice = parseChoice(text);
      if (choice && choice >= 1 && choice <= times.length) {
        d.registrationTime = times[choice - 1];
      } else {
        // try to normalize times like "10", "10:00", "10 am"
        const candidate = text.trim();
        // allow "10" -> "10:00"
        let candidateTime = candidate;
        if (/^\d{1,2}$/.test(candidate)) candidateTime = candidate.padStart(2, "0") + ":00";
        // normalize "10 am" via chrono
        const dt = chrono.parseDate(candidate);
        if (dt) candidateTime = dt.getHours().toString().padStart(2, "0") + ":00";
        if (times.includes(candidateTime)) d.registrationTime = candidateTime;
        else {
          await sendWhatsAppMessage(sender, `Invalid time. Choose from the options sent (1-${times.length}) or a valid time like 10:00.`);
          return;
        }
      }

      // final attempt to register
      s.step = "confirming";
      s.data = d;
      await setState(sender, s);

      try {
        const pid = await attemptRegistration(d);
        await sendWhatsAppMessage(sender, `✅ Registration successful!\nPatient ID: ${pid}\nDepartment: ${d.department}\nDate: ${d.registrationDate}\nTime: ${d.registrationTime}\nThank you for registering at NovaMed.`);
        await resetState(sender);
      } catch (err) {
        await sendWhatsAppMessage(sender, `❌ ${err.message}. Please choose a different time or date.`);
        // keep state at registrationTime to allow next choice
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
exports.handler = async (event) => {
  try {
    if (event.httpMethod === "GET") {
      const VERIFY_TOKEN = "shreyaWebhook123";
      const params = event.queryStringParameters || {};
      if (params["hub.mode"] === "subscribe" && params["hub.verify_token"] === VERIFY_TOKEN) {
        return { statusCode: 200, body: params["hub.challenge"] };
      }
      return { statusCode: 403, body: "Forbidden" };
    }

    if (event.httpMethod === "POST") {
      const body = JSON.parse(event.body || "{}");
      const message = body?.entry?.[0]?.changes?.[0]?.value?.messages?.[0];
      if (!message || !message.text) return { statusCode: 200, body: "No message found" };

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
