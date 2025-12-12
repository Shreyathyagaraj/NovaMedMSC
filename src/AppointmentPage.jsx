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
    PhoneNumber: "",
    Email: "",
    Department: department || "",
    Age: "",
  });

  const [slotsLeft, setSlotsLeft] = useState(null);
  const [success, setSuccess] = useState(false);
  const [newPatientId, setNewPatientId] = useState(null);
  const [timeSlots, setTimeSlots] = useState([]);
  const [loading, setLoading] = useState(false);
  const today = new Date().toISOString().split("T")[0];

  // ---------------------------
  // Doctor Schedules
  // ---------------------------
  const doctorSchedule = {
    "General Surgeon": ["09:00", "12:00"],
    Orthopedics: ["10:00", "13:00"],
    Pediatrics: ["15:00", "18:00"],
    "ENT Specialist": ["11:00", "16:00"],
    Dermatology: ["09:00", "18:00"],
    Physician: ["09:00", "12:00"],
  };

  const doctorLimits = {
    "General Surgeon": 5,
    Orthopedics: 6,
    Pediatrics: 12,
    "ENT Specialist": 7,
    Dermatology: 15,
    Physician: 10,
  };

  // ----------------------------------------------------------
  // Generate timeslot buttons (every 30 min)
  // ----------------------------------------------------------
  const generateSlots = (start, end) => {
    const slots = [];
    let [h, m] = start.split(":").map(Number);
    const [endH, endM] = end.split(":").map(Number);

    while (h < endH || (h === endH && m <= endM)) {
      const hh = h.toString().padStart(2, "0");
      const mm = m.toString().padStart(2, "0");
      slots.push(`${hh}:${mm}`);
      m += 30;
      if (m >= 60) {
        h++;
        m -= 60;
      }
    }

    return slots;
  };

  // ----------------------------------------------------------
  // Load Timeslots When Department is Selected
  // ----------------------------------------------------------
  useEffect(() => {
    if (!formData.Department) return;

    const schedule = doctorSchedule[formData.Department];
    if (!schedule) {
      setTimeSlots([]);
      return;
    }

    const [start, end] = schedule;
    setTimeSlots(generateSlots(start, end));
  }, [formData.Department]);

  // ----------------------------------------------------------
  // Load slot availability per date
  // ----------------------------------------------------------
  useEffect(() => {
    const fetchSlots = async () => {
      if (!formData.Department || !formData.RegistrationDate) return;

      const appointmentsRef = collection(db, "patients");
      const q = query(
        appointmentsRef,
        where("Department", "==", formData.Department),
        where("RegistrationDate", "==", formData.RegistrationDate)
      );

      const snapshot = await getDocs(q);
      const bookedCount = snapshot.size;
      const maxLimit = doctorLimits[formData.Department] || 5;
      setSlotsLeft(maxLimit - bookedCount);
    };

    fetchSlots();
  }, [formData.Department, formData.RegistrationDate]);

  // ----------------------------------------------------------
  // Handle change
  // ----------------------------------------------------------
  const handleChange = (e) => {
    const { name, value } = e.target;

    // Clean phone input
    if (name === "PhoneNumber") {
      setFormData({
        ...formData,
        PhoneNumber: value.replace(/[^\d+()-\s]/g, ""),
      });
      return;
    }

    setFormData({ ...formData, [name]: value });
  };

  // ----------------------------------------------------------
  // Submit Appointment
  // ----------------------------------------------------------
  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);

    try {
      if (!formData.RegistrationTime) {
        alert("Please select a time slot");
        setLoading(false);
        return;
      }

      if (slotsLeft <= 0) {
        alert("No slots available for selected date");
        setLoading(false);
        return;
      }

      // SAVE PATIENT IN FIREBASE
      const counterRef = doc(db, "counters", "patients");

      const patientId = await runTransaction(db, async (tx) => {
        const snap = await tx.get(counterRef);
        const next = snap.exists() ? (snap.data().lastId || 0) + 1 : 1;

        const id = "P" + String(next).padStart(3, "0");
        const patientRef = doc(db, "patients", id);

        tx.set(counterRef, { lastId: next }, { merge: true });
        tx.set(patientRef, {
          PatientID: id,
          ...formData,
        });

        return id;
      });

      setNewPatientId(patientId);
      setSuccess(true);

      // SEND WHATSAPP CONFIRMATION
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

      // RESET FORM
      setFormData({
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
    } catch (err) {
      console.error(err);
      alert("Something went wrong!");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="appointment-container">
      <h2>Book an Appointment - {formData.Department}</h2>
      <p>Please provide the patient details</p>

      <form onSubmit={handleSubmit} className="appointment-form">
        
        {/* FIRST NAME */}
        <label>First Name *</label>
        <input
          name="FirstName"
          value={formData.FirstName}
          onChange={handleChange}
          required
        />

        {/* LAST NAME */}
        <label>Last Name *</label>
        <input
          name="LastName"
          value={formData.LastName}
          onChange={handleChange}
          required
        />

        {/* GENDER */}
        <label>Gender *</label>
        <select name="Gender" required value={formData.Gender} onChange={handleChange}>
          <option value="">Select</option>
          <option>Male</option>
          <option>Female</option>
          <option>Other</option>
        </select>

        {/* ADDRESS */}
        <label>Address *</label>
        <textarea
          name="Address"
          required
          value={formData.Address}
          onChange={handleChange}
        />

        {/* DATE */}
        <label>Date *</label>
        <input
          type="date"
          required
          name="RegistrationDate"
          value={formData.RegistrationDate}
          min={today}
          onChange={handleChange}
        />

        {/* TIME SLOTS */}
        <label>Time *</label>
        <div className="time-slot-container">
          {timeSlots.map((slot) => {
            const isPast =
              formData.RegistrationDate === today &&
              slot < new Date().toISOString().slice(11, 16);

            return (
              <button
                type="button"
                key={slot}
                className={`time-slot ${
                  formData.RegistrationTime === slot ? "selected" : ""
                } ${isPast ? "disabled" : ""}`}
                disabled={isPast}
                onClick={() =>
                  setFormData({ ...formData, RegistrationTime: slot })
                }
              >
                {slot}
              </button>
            );
          })}
        </div>

        {/* PHONE */}
        <label>Phone Number *</label>
        <input
          name="PhoneNumber"
          required
          value={formData.PhoneNumber}
          onChange={handleChange}
        />

        {/* EMAIL */}
        <label>Email (Optional)</label>
        <input
          name="Email"
          value={formData.Email}
          onChange={handleChange}
        />

        {/* AGE */}
        <label>Age *</label>
        <input
          type="number"
          name="Age"
          required
          value={formData.Age}
          onChange={handleChange}
        />

        <button disabled={loading} className="submit-btn">
          {loading ? "Submitting..." : "Book Appointment"}
        </button>
      </form>

      {success && (
        <p className="success-message">
          ✅ Registered Successfully! <br />
          <strong>Patient ID: {newPatientId}</strong>
        </p>
      )}
    </div>
  );
}
