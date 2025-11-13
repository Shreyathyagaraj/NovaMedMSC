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
  const [submitting, setSubmitting] = useState(false);
  const [slotsLeft, setSlotsLeft] = useState(null);

  // ✅ Doctor schedule (time availability)
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

  // ✅ Doctor daily limits
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

  // ✅ Date/time helpers
  const today = new Date().toISOString().split("T")[0];
  const now = new Date();
  const currentTime = now.toISOString().slice(11, 16);

  // ✅ Check slot availability whenever date/department changes
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
  }, [formData.Department, formData.RegistrationDate, doctorLimits]); // ✅ fixed dependency array

  // ✅ Handle form changes
  const handleChange = (e) => {
    const { name, value } = e.target;
    if (name === "PhoneNumber") {
      setFormData({
        ...formData,
        [name]: value.replace(/[^\d+()-\s]/g, ""),
      });
    } else {
      setFormData({ ...formData, [name]: value });
    }
  };

  // ✅ Handle Submit
  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setSuccess(false);
    setNewPatientId(null);
    setPatientSegment(null);

    try {
      // Step 1: Validate slot availability
      if (slotsLeft !== null && slotsLeft <= 0) {
        alert(
          `❌ Appointment limit reached for ${formData.Department} on ${formData.RegistrationDate}. Please choose another date.`
        );
        setSubmitting(false);
        return;
      }

      // Step 2: Validate doctor working hours
      if (formData.Department && doctorSchedule[formData.Department]) {
        const [start, end] = doctorSchedule[formData.Department];
        if (
          formData.RegistrationTime < start ||
          formData.RegistrationTime > end
        ) {
          alert(
            `❌ Doctor in ${formData.Department} is only available between ${start} and ${end}. Please choose a valid time.`
          );
          setSubmitting(false);
          return;
        }

        if (
          formData.RegistrationDate === today &&
          formData.RegistrationTime < currentTime
        ) {
          alert("❌ You cannot book an appointment in the past.");
          setSubmitting(false);
          return;
        }
      }

      // Step 3: Segmentation API
      let segmentLabel = null;
      try {
        const res = await fetch("http://localhost:8000/segment", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            age: parseInt(formData.Age, 10),
            visits: 1,
            condition: formData.Condition || "none",
          }),
        });

        const segData = await res.json();
        if (!segData.error) {
          segmentLabel = segData.label;
          setPatientSegment(segmentLabel);
        }
      } catch (err) {
        console.error("Segmentation request failed:", err);
      }

      // Step 4: Save patient to Firestore
      const counterRef = doc(db, "counters", "patients");
      const patientId = await runTransaction(db, async (tx) => {
        const counterSnap = await tx.get(counterRef);
        let next = 1;
        if (counterSnap.exists()) {
          next = (counterSnap.data().lastId || 0) + 1;
        }

        const id = "P" + String(next).padStart(3, "0");
        const patientRef = doc(db, "patients", id);

        tx.set(counterRef, { lastId: next }, { merge: true });
        tx.set(patientRef, {
          PatientID: id,
          ...formData,
          Segment: segmentLabel || "Uncategorized",
        });

        return id;
      });

      setSuccess(true);
      setNewPatientId(patientId);

      // ✅ Step 5: Send WhatsApp confirmation via FastAPI backend
      try {
        await fetch("http://localhost:8000/register_patient", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: formData.FirstName + " " + formData.LastName,
            age: parseInt(formData.Age, 10),
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
        console.error("WhatsApp message failed:", err);
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
    } catch (error) {
      console.error("Save failed:", error);
      const fallbackId = "P" + Math.floor(Math.random() * 10000);
      await setDoc(doc(db, "patients", fallbackId), {
        PatientID: fallbackId,
        ...formData,
        Segment: patientSegment || "Uncategorized",
      });
      setSuccess(true);
      setNewPatientId(fallbackId);
      alert(
        `⚠ Auto-increment failed, but patient was saved with fallback ID: ${fallbackId}`
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="appointment-container">
      <h2>Book an Appointment - {department}</h2>
      <p>Please provide the patient details</p>

      <form onSubmit={handleSubmit} className="appointment-form">
        {/* form fields here (unchanged) */}
      </form>

      {success && (
        <p className="success-message">
          ✅ Patient registered successfully! <br />
          <strong>Patient ID:</strong> {newPatientId}
          <br />
          {patientSegment && (
            <span
              style={{
                display: "inline-block",
                marginTop: "8px",
                padding: "6px 10px",
                borderRadius: "6px",
                backgroundColor:
                  patientSegment === "Chronic illness patient"
                    ? "#ffcdd2"
                    : patientSegment === "Regular patient"
                    ? "#bbdefb"
                    : "#c8e6c9",
              }}
            >
              🏷 {patientSegment}
            </span>
          )}
        </p>
      )}
    </div>
  );
}