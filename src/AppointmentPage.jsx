import React, { useState, useEffect } from "react";
import "./AppointmentPage.css";
import { db } from "./firebase";
import {
  doc,
  runTransaction,
  setDoc,
  collection,
  query,
  where,
  getDocs,
} from "firebase/firestore";
import { BACKEND_URL } from "./config";

export default function AppointmentPage({ department }) {
  const [formData, setFormData] = useState({
    FirstName: "",
    LastName: "",
    Gender: "",
    Address: "",
    RegistrationDate: "",
    RegistrationTime: "",
    Email: "",
    PhoneNumber: "",
    Department: department || "",   // <-- pre-filled from props
    Age: "",
  });

  const [slotsLeft, setSlotsLeft] = useState(null);
  const [timeSlots, setTimeSlots] = useState([]);
  const [success, setSuccess] = useState(false);
  const [newPatientId, setNewPatientId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [patientSegment, setPatientSegment] = useState("");

  // -----------------------
  // Doctor Schedules
  // -----------------------
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

  const today = new Date().toISOString().split("T")[0];

  // ----------------------------------------------------
  // Generate Time Slots for Department
  // ----------------------------------------------------
  const generateTimeSlots = (start, end) => {
    const slots = [];
    let [h1, m1] = start.split(":").map(Number);
    let [h2, m2] = end.split(":").map(Number);

    while (h1 < h2 || (h1 === h2 && m1 <= m2)) {
      const hh = String(h1).padStart(2, "0");
      const mm = String(m1).padStart(2, "0");
      slots.push(`${hh}:${mm}`);

      m1 += 30;
      if (m1 >= 60) {
        m1 = 0;
        h1++;
      }
    }
    return slots;
  };

  // ----------------------------------------------------
  // Update time slots when department changes
  // ----------------------------------------------------
  useEffect(() => {
    if (formData.Department && doctorSchedule[formData.Department]) {
      const [start, end] = doctorSchedule[formData.Department];
      setTimeSlots(generateTimeSlots(start, end));
    }
  }, [formData.Department]);

  // ----------------------------------------------------
  // Load number of slots left
  // ----------------------------------------------------
  useEffect(() => {
    const loadSlots = async () => {
      if (!formData.Department || !formData.RegistrationDate) return;

      const ref = collection(db, "patients");
      const q = query(
        ref,
        where("Department", "==", formData.Department),
        where("RegistrationDate", "==", formData.RegistrationDate)
      );

      const snap = await getDocs(q);
      const booked = snap.size;
      const max = doctorLimits[formData.Department] || 5;

      setSlotsLeft(max - booked);
    };

    loadSlots();
  }, [formData.Department, formData.RegistrationDate]);

  // ----------------------------------------------------
  // Input Handler
  // ----------------------------------------------------
  const handleChange = (e) => {
    const { name, value } = e.target;

    if (name === "PhoneNumber") {
      return setFormData({
        ...formData,
        PhoneNumber: value.replace(/[^\d+()-\s]/g, ""),
      });
    }

    setFormData({ ...formData, [name]: value });
  };

  // ----------------------------------------------------
  // Submit Form
  // ----------------------------------------------------
  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setSuccess(false);

    if (slotsLeft <= 0) {
      alert("❌ No slots available for this date.");
      setLoading(false);
      return;
    }

    let segmentLabel = "Uncategorized";
    try {
      const segRes = await fetch(`${BACKEND_URL}/segment`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          age: parseInt(formData.Age, 10),
          visits: 1,
          condition: "none",
        }),
      });

      const segData = await segRes.json();
      if (segData.label) {
        segmentLabel = segData.label;
        setPatientSegment(segData.label);
      }
    } catch (err) {
      console.error("Segmentation failed:", err);
    }

    try {
      const counterRef = doc(db, "counters", "patients");

      const patientId = await runTransaction(db, async (tx) => {
        const snap = await tx.get(counterRef);
        const next = snap.exists() ? (snap.data().lastId || 0) + 1 : 1;

        const id = "P" + String(next).padStart(3, "0");
        const patientRef = doc(db, "patients", id);

        tx.set(counterRef, { lastId: next }, { merge: true });
        tx.set(patientRef, { PatientID: id, ...formData, Segment: segmentLabel });

        return id;
      });

      setNewPatientId(patientId);
      setSuccess(true);
    } catch (err) {
      console.error("Save failed:", err);
      alert("Something went wrong.");
    }

    setLoading(false);
  };

  return (
    <div className="appointment-wrapper">
      <div className="appointment-card">
        <h2>Book Appointment – {department}</h2>
        <p>Please fill in the details</p>

        {/* SLOT DISPLAY */}
        {slotsLeft !== null && (
          <div className="slots-box">
            {slotsLeft > 0 ? (
              <span>🟢 {slotsLeft} slots left today</span>
            ) : (
              <span className="no-slots">🔴 No slots available today</span>
            )}
          </div>
        )}

        <form onSubmit={handleSubmit} className="appointment-form">
          {/* FIRST NAME */}
          <div className="form-row">
            <label>First Name *</label>
            <input
              name="FirstName"
              value={formData.FirstName}
              required
              onChange={handleChange}
            />
          </div>

          {/* LAST NAME */}
          <div className="form-row">
            <label>Last Name *</label>
            <input
              name="LastName"
              value={formData.LastName}
              required
              onChange={handleChange}
            />
          </div>

          {/* GENDER */}
          <div className="form-row">
            <label>Gender *</label>
            <select
              name="Gender"
              value={formData.Gender}
              required
              onChange={handleChange}
            >
              <option value="">Select</option>
              <option>Male</option>
              <option>Female</option>
              <option>Other</option>
            </select>
          </div>

          {/* AGE */}
          <div className="form-row">
            <label>Age *</label>
            <input
              type="number"
              name="Age"
              required
              value={formData.Age}
              onChange={handleChange}
            />
          </div>

          {/* ADDRESS */}
          <div className="form-row">
            <label>Address *</label>
            <textarea
              name="Address"
              required
              value={formData.Address}
              onChange={handleChange}
            />
          </div>

          {/* AUTO-SELECED DEPARTMENT */}
          <div className="form-row">
            <label>Department *</label>
            <input
              value={formData.Department}
              name="Department"
              readOnly
              className="readonly-input"
            />
          </div>

          {/* DATE */}
          <div className="form-row">
            <label>Date *</label>
            <input
              type="date"
              name="RegistrationDate"
              min={today}
              required
              value={formData.RegistrationDate}
              onChange={handleChange}
            />
          </div>

          {/* TIME SLOT (dynamic) */}
          <div className="form-row">
            <label>Time *</label>
            <select
              name="RegistrationTime"
              required
              value={formData.RegistrationTime}
              onChange={handleChange}
            >
              <option value="">Select Time</option>
              {timeSlots.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </div>

          {/* PHONE */}
          <div className="form-row">
            <label>Phone Number *</label>
            <input
              name="PhoneNumber"
              required
              value={formData.PhoneNumber}
              onChange={handleChange}
            />
          </div>

          {/* EMAIL OPTIONAL */}
          <div className="form-row">
            <label>Email (Optional)</label>
            <input
              name="Email"
              type="email"
              value={formData.Email}
              onChange={handleChange}
            />
          </div>

          <button disabled={loading}>
            {loading ? "Saving..." : "Book Appointment"}
          </button>
        </form>

        {success && (
          <div className="success-box">
            <p>✅ Appointment booked successfully!</p>
            <p><strong>Patient ID:</strong> {newPatientId}</p>
            <p><strong>Segment:</strong> {patientSegment}</p>
          </div>
        )}
      </div>
    </div>
  );
}
