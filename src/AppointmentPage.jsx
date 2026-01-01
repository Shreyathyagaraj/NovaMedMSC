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

  const [timeSlots, setTimeSlots] = useState([]);
  const [bookedSlots, setBookedSlots] = useState({});
  const [success, setSuccess] = useState(false);
  const [newPatientId, setNewPatientId] = useState(null);
  const [loading, setLoading] = useState(false);

  // ---------------- DOCTOR CONFIG ----------------
  const doctorSchedule = {
    Cardiology: ["09:00", "12:00"],
    Neurology: ["14:00", "17:00"],
    Orthopedics: ["10:00", "13:00"],
    Pediatrics: ["15:00", "18:00"],
    "General Medicine": ["09:00", "12:00"],
    Dermatology: ["09:00", "18:00"],
  };

  const doctorLimits = {
    Cardiology: 10,
    Neurology: 8,
    Orthopedics: 6,
    Pediatrics: 12,
    "General Medicine": 10,
    Dermatology: 15,
  };

  // ---------------- SLOT GENERATOR ----------------
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

  // ---------------- FETCH BOOKED SLOTS ----------------
  useEffect(() => {
    const fetchBookedSlots = async () => {
      if (!formData.Department || !formData.RegistrationDate) return;

      const q = query(
        collection(db, "patients"),
        where("Department", "==", formData.Department),
        where("RegistrationDate", "==", formData.RegistrationDate)
      );

      const snapshot = await getDocs(q);

      const slotMap = {};
      snapshot.forEach((doc) => {
        const t = doc.data().RegistrationTime;
        slotMap[t] = (slotMap[t] || 0) + 1;
      });

      setBookedSlots(slotMap);
    };

    fetchBookedSlots();
  }, [formData.Department, formData.RegistrationDate]);

  // ---------------- HANDLE INPUT ----------------
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
      alert("Booking failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="appointment-container">
      <h2>Book Appointment – {formData.Department}</h2>

      <form onSubmit={handleSubmit} className="appointment-form">

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
          required
          min={today}
          name="RegistrationDate"
          onChange={handleChange}
        />

        {/* TIME SLOTS */}
        <label>Available Time Slots</label>
        <div className="time-slot-container">
          {timeSlots.map((slot) => {
            const booked = bookedSlots[slot] || 0;
            const limit = doctorLimits[formData.Department];
            const isFull = booked >= limit;

            const isPast =
              formData.RegistrationDate === today &&
              slot <= new Date().toTimeString().slice(0, 5);

            return (
              <button
                key={slot}
                type="button"
                disabled={isFull || isPast}
                className={`time-slot 
                  ${isFull ? "full" : ""}
                  ${formData.RegistrationTime === slot ? "selected" : ""}
                `}
                onClick={() =>
                  setFormData({ ...formData, RegistrationTime: slot })
                }
              >
                {slot}
                <span className="left">
                  {isFull ? "Full" : `(${limit - booked} left)`}
                </span>
              </button>
            );
          })}
        </div>

        <label>Phone *</label>
        <input required name="PhoneNumber" onChange={handleChange} />

        <label>Email</label>
        <input name="Email" onChange={handleChange} />

        <label>Age *</label>
        <input type="number" required name="Age" onChange={handleChange} />

        <button className="submit-btn" disabled={loading}>
          {loading ? "Booking..." : "Confirm Appointment"}
        </button>
      </form>

      {success && (
        <p className="success-message">
          ✅ Appointment Confirmed <br />
          Patient ID: <b>{newPatientId}</b>
        </p>
      )}
    </div>
  );
}
