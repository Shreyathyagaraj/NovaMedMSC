import React, { useState, useEffect } from "react";
import "./AppointmentPage.css";
import { db } from "./firebase";
import {
  doc,
  runTransaction,
  collection,
  query,
  where,
  getDocs,
} from "firebase/firestore";
import { BACKEND_URL } from "./config";

export default function AppointmentPage({ department }) {
  const today = new Date().toISOString().split("T")[0];
  const nowTime = new Date().toTimeString().slice(0, 5);

  const [formData, setFormData] = useState({
    FirstName: "",
    LastName: "",
    Gender: "",
    Address: "",
    RegistrationDate: "",
    RegistrationTime: "",
    PhoneNumber: "",
    Email: "",
    Department: department || "",
    Age: "",
  });

  const [slotsLeft, setSlotsLeft] = useState(null);
  const [timeSlots, setTimeSlots] = useState([]);
  const [success, setSuccess] = useState(false);
  const [newPatientId, setNewPatientId] = useState(null);
  const [loading, setLoading] = useState(false);

  // ---------------- DOCTOR CONFIG ----------------
  const doctorSchedule = {
    "General surgeon": ["12:00", "16:00"],
    Orthopedics: ["10:00", "13:00"],
    Ophthalmology: ["09:00", "12:00"],
    Gynecology: ["10:00", "12:00"],
    "ENT Specialist": ["14:00", "17:00"],
    Anaesthesiology: ["10:00", "13:00"],
    Pediatrics: ["15:00", "18:00"],
    Physician: ["09:00", "12:00"],
    Dermatology: ["09:00", "18:00"],
    Dentist: ["09:00", "12:00"],
  };

  const doctorLimits = {
    "General surgeon": 3,
    Orthopedics: 9,
    Ophthalmology: 10,
    Gynecology: 2,
    "ENT Specialist": 8,
    Anaesthesiology: 6,
    Pediatrics: 12,
    Physician: 10,
    Dermatology: 15,
    Dentist: 12,
  };

  // ---------------- SLOT GENERATION ----------------
  const generateSlots = (start, end) => {
    const slots = [];
    let [h, m] = start.split(":").map(Number);
    const [eh, em] = end.split(":").map(Number);

    while (h < eh || (h === eh && m < em)) {
      slots.push(`${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`);
      m += 30;
      if (m >= 60) {
        h++;
        m = 0;
      }
    }
    return slots;
  };

  // ---------------- LOAD TIME SLOTS ----------------
  useEffect(() => {
    if (!formData.Department) return;
    const schedule = doctorSchedule[formData.Department];
    if (!schedule) return;
    setTimeSlots(generateSlots(schedule[0], schedule[1]));
  }, [formData.Department]);

  // ---------------- FETCH SLOT COUNT ----------------
  useEffect(() => {
    const fetchSlots = async () => {
      if (!formData.Department || !formData.RegistrationDate) return;

      const q = query(
        collection(db, "patients"),
        where("Department", "==", formData.Department),
        where("RegistrationDate", "==", formData.RegistrationDate)
      );

      const snap = await getDocs(q);
      const max = doctorLimits[formData.Department] || 0;
      setSlotsLeft(max - snap.size);
    };

    fetchSlots();
  }, [formData.Department, formData.RegistrationDate]);

  // ---------------- HANDLE CHANGE ----------------
  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData({ ...formData, [name]: value });
  };

  // ---------------- SUBMIT ----------------
  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!formData.RegistrationTime) {
      alert("Please select a time slot");
      return;
    }

    if (slotsLeft <= 0) {
      alert("No slots available for this date");
      return;
    }

    setLoading(true);

    try {
      const counterRef = doc(db, "counters", "patients");

      const patientId = await runTransaction(db, async (tx) => {
        const snap = await tx.get(counterRef);
        const next = snap.exists() ? (snap.data().lastId || 0) + 1 : 1;
        const pid = "P" + String(next).padStart(3, "0");

        tx.set(counterRef, { lastId: next }, { merge: true });
        tx.set(doc(db, "patients", pid), {
          PatientID: pid,
          ...formData,
        });

        return pid;
      });

      setNewPatientId(patientId);
      setSuccess(true);

      await fetch(`${BACKEND_URL}/register_patient`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formData),
      });

    } catch (err) {
      console.error(err);
      alert("Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="appointment-page">
      <div className="appointment-card">
        <h2>Book Appointment</h2>
        <p className="subtitle">{formData.Department}</p>

        <form onSubmit={handleSubmit}>
          <label>First Name *</label>
          <input required name="FirstName" onChange={handleChange} />

          <label>Last Name *</label>
          <input required name="LastName" onChange={handleChange} />

          <label>Gender *</label>
          <select required name="Gender" onChange={handleChange}>
            <option value="">Select</option>
            <option>Male</option>
            <option>Female</option>
            <option>Other</option>
          </select>

          <label>Address *</label>
          <textarea required name="Address" onChange={handleChange} />

          <label>Date *</label>
          <input
            type="date"
            min={today}
            required
            name="RegistrationDate"
            onChange={handleChange}
          />

          <label>Available Time Slots</label>
          <div className="slots-grid">
            {timeSlots.map((slot) => {
              const isPast =
                formData.RegistrationDate === today && slot <= nowTime;

              return (
                <button
                  key={slot}
                  type="button"
                  disabled={isPast || slotsLeft <= 0}
                  className={`slot ${
                    formData.RegistrationTime === slot ? "active" : ""
                  }`}
                  onClick={() =>
                    setFormData({ ...formData, RegistrationTime: slot })
                  }
                >
                  {slot}
                </button>
              );
            })}
          </div>

          {slotsLeft !== null && (
            <span className="left">Only {slotsLeft} slots left</span>
          )}

          <label>Phone *</label>
          <input required name="PhoneNumber" onChange={handleChange} />

          <label>Email</label>
          <input name="Email" onChange={handleChange} />

          <label>Age *</label>
          <input type="number" required name="Age" onChange={handleChange} />

          <button className="confirm-btn" disabled={loading}>
            {loading ? "Booking..." : "Confirm Appointment"}
          </button>
        </form>

        {success && (
          <div className="success">
            ✅ Appointment Confirmed <br />
            <strong>Patient ID: {newPatientId}</strong>
          </div>
        )}
      </div>
    </div>
  );
}
