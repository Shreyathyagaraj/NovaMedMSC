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
    Department: department || "",
    Age: "",
    Condition: "",
  });

  const [success, setSuccess] = useState(false);
  const [newPatientId, setNewPatientId] = useState(null);
  const [patientSegment, setPatientSegment] = useState(null);
  const [slotsLeft, setSlotsLeft] = useState(null);
  const [loading, setLoading] = useState(false);

  // -----------------------------
  // Doctor Schedules & Limits
  // -----------------------------
  const doctorSchedule = {
    Cardiology: ["09:00", "12:00"],
    Neurology: ["14:00", "17:00"],
    Orthopedics: ["10:00", "13:00"],
    Pediatrics: ["15:00", "18:00"],
    "General Surgeon": ["09:00", "12:00"],
    ENT_specialist: ["11:00", "16:00"],
    Dermatology: ["09:00", "18:00"],
    Physician: ["09:00", "12:00"],
    Anaesthesiology: ["14:00", "18:00"],
    Opthalmology: ["09:00", "11:00"],
    Gynecology: ["14:00", "21:00"],
    Dentist: ["12:00", "18:00"],
  };

  const doctorLimits = {
    Cardiology: 10,
    Neurology: 8,
    Orthopedics: 6,
    Pediatrics: 12,
    "General Surgeon": 5,
    ENT_specialist: 7,
    Dermatology: 15,
    Physician: 10,
    Anaesthesiology: 4,
    Opthalmology: 6,
    Gynecology: 8,
    Dentist: 10,
  };

  const today = new Date().toISOString().split("T")[0];
  const currentTime = new Date().toISOString().slice(11, 16);

  // --------------------------------------------------
  // Fetch Slot Availability
  // --------------------------------------------------
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

  // --------------------------------------------------
  // Handle Input Change
  // --------------------------------------------------
  const handleChange = (e) => {
    const { name, value } = e.target;

    // Clean phone input
    if (name === "PhoneNumber") {
      return setFormData({
        ...formData,
        PhoneNumber: value.replace(/[^\d+()-\s]/g, ""),
      });
    }

    setFormData({ ...formData, [name]: value });
  };

  // --------------------------------------------------
  // Submit Appointment
  // --------------------------------------------------
  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setSuccess(false);
    setNewPatientId(null);

    try {
      // Slot Check
      if (slotsLeft <= 0) {
        alert("❌ No slots available for selected date.");
        return;
      }

      // Doctor Working Hours Check
      const [start, end] = doctorSchedule[formData.Department] || [];
      if (
        start &&
        (formData.RegistrationTime < start ||
          formData.RegistrationTime > end)
      ) {
        alert(
          `❌ Doctor available only between ${start} - ${end}. Choose a valid time.`
        );
        return;
      }

      // No past time today
      if (
        formData.RegistrationDate === today &&
        formData.RegistrationTime < currentTime
      ) {
        alert("❌ Cannot book in the past.");
        return;
      }

      // --------------------------------------------------
      // FETCH SEGMENT LABEL FROM FASTAPI
      // --------------------------------------------------
      let segmentLabel = "Uncategorized";

      try {
        const segRes = await fetch(`${BACKEND_URL}/segment`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            age: parseInt(formData.Age, 10),
            visits: 1,
            condition: formData.Condition || "none",
          }),
        });

        const segData = await segRes.json();
        if (segData.label) {
          segmentLabel = segData.label;
          setPatientSegment(segData.label);
        }
      } catch (err) {
        console.error("Segmentation error:", err);
      }

      // --------------------------------------------------
      // SAVE PATIENT IN FIREBASE WITH AUTO-ID
      // --------------------------------------------------
      const counterRef = doc(db, "counters", "patients");

      const patientId = await runTransaction(db, async (tx) => {
        const snap = await tx.get(counterRef);

        const next = snap.exists()
          ? (snap.data().lastId || 0) + 1
          : 1;

        const id = "P" + String(next).padStart(3, "0");
        const patientRef = doc(db, "patients", id);

        tx.set(counterRef, { lastId: next }, { merge: true });
        tx.set(patientRef, {
          PatientID: id,
          ...formData,
          Segment: segmentLabel,
        });

        return id;
      });

      setNewPatientId(patientId);
      setSuccess(true);

      // --------------------------------------------------
      // SEND WHATSAPP CONFIRMATION
      // --------------------------------------------------
      try {
        await fetch(`${BACKEND_URL}/register_patient`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: `${formData.FirstName} ${formData.LastName}`,
            age: formData.Age,
            gender: formData.Gender,
            phone: formData.PhoneNumber,
            email: formData.Email,
            address: formData.Address,
            appointment_date: formData.RegistrationDate,
            department: formData.Department,
            doctor: "Dr. Assigned",
          }),
        });
      } catch (err) {
        console.error("WhatsApp sending failed:", err);
      }

      // Reset form
      setFormData({
        FirstName: "",
        LastName: "",
        Gender: "",
        Address: "",
        RegistrationDate: "",
        RegistrationTime: "",
        Email: "",
        PhoneNumber: "",
        Department: department || "",
        Age: "",
        Condition: "",
      });
    } catch (err) {
      console.error("Save error:", err);
      alert("Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  // --------------------------------------------------
  // UI
  // --------------------------------------------------
  return (
    <div className="appointment-container">
      <h2>Book an Appointment - {department}</h2>
      <p>Please provide the patient details</p>

      <form onSubmit={handleSubmit} className="appointment-form">
        <div className="form-row">
  <label>First Name</label>
  <input
    type="text"
    name="FirstName"
    value={formData.FirstName}
    onChange={handleChange}
    required
  />
</div>

<div className="form-row">
  <label>Last Name</label>
  <input
    type="text"
    name="LastName"
    value={formData.LastName}
    onChange={handleChange}
    required
  />
</div>

<div className="form-row">
  <label>Gender</label>
  <select name="Gender" value={formData.Gender} onChange={handleChange} required>
    <option value="">Select</option>
    <option value="Male">Male</option>
    <option value="Female">Female</option>
    <option value="Other">Other</option>
  </select>
</div>

<div className="form-row">
  <label>Address</label>
  <textarea
    name="Address"
    value={formData.Address}
    onChange={handleChange}
    required
  ></textarea>
</div>

<div className="form-row">
  <label>Date</label>
  <input
    type="date"
    name="RegistrationDate"
    value={formData.RegistrationDate}
    onChange={handleChange}
    required
  />
</div>

<div className="form-row">
  <label>Time</label>
  <input
    type="time"
    name="RegistrationTime"
    value={formData.RegistrationTime}
    onChange={handleChange}
    required
  />
</div>

<div className="form-row">
  <label>Email</label>
  <input
    type="email"
    name="Email"
    value={formData.Email}
    onChange={handleChange}
  />
</div>

<div className="form-row">
  <label>Phone Number</label>
  <input
    type="text"
    name="PhoneNumber"
    value={formData.PhoneNumber}
    onChange={handleChange}
    required
  />
</div>

<div className="form-row">
  <label>Age</label>
  <input
    type="number"
    name="Age"
    value={formData.Age}
    onChange={handleChange}
    required
  />
</div>

<div className="form-row">
  <label>Condition</label>
  <input
    type="text"
    name="Condition"
    value={formData.Condition}
    onChange={handleChange}
  />
</div>

<button type="submit" disabled={loading}>
  {loading ? "Booking..." : "Book Appointment"}
</button>

      </form>

      {success && (
        <p className="success-message">
          ✅ Registered Successfully!
          <br />
          <strong>Patient ID: {newPatientId}</strong>
          {patientSegment && (
            <div className="segment-badge">🏷 {patientSegment}</div>
          )}
        </p>
      )}
    </div>
  );
}
