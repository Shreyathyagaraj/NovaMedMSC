import React, { useState } from "react";
import { BACKEND_URL } from "./config";

export default function PredictionPage() {
  const [selectedDate, setSelectedDate] = useState("");
  const [selectedDepartment, setSelectedDepartment] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handlePredict = async () => {
    setError("");
    setResult(null);

    if (!selectedDate || !selectedDepartment) {
      setError("Please select both date and department.");
      return;
    }

    setLoading(true);

    try {
      const res = await fetch(`${BACKEND_URL}/predict`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          date: selectedDate,
          department: selectedDepartment,
        }),
      });

      if (!res.ok) {
        throw new Error("Prediction API failed");
      }

      const data = await res.json();
      setResult(data);
    } catch (err) {
      setError(err.message || "Failed to fetch prediction");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: "40px" }}>
      <h2>🩺 Patient Load Prediction</h2>

      <div>
        <label>Date:</label>
        <input
          type="date"
          value={selectedDate}
          onChange={(e) => setSelectedDate(e.target.value)}
        />
      </div>

      <div>
        <label>Department:</label>
        <select
          value={selectedDepartment}
          onChange={(e) => setSelectedDepartment(e.target.value)}
        >
          <option value="">-- Select --</option>
          <option value="Cardiology">Cardiology</option>
          <option value="Neurology">Neurology</option>
          <option value="Orthopedics">Orthopedics</option>
          <option value="Pediatrics">Pediatrics</option>
          <option value="General Medicine">General Medicine</option>
          <option value="Dermatology">Dermatology</option>
        </select>
      </div>

      <button onClick={handlePredict} disabled={loading}>
        {loading ? "Predicting..." : "Predict"}
      </button>

      {error && <p style={{ color: "red" }}>{error}</p>}

      {result && (
        <div style={{ marginTop: "20px" }}>
          <p><strong>Department:</strong> {result.department}</p>
          <p><strong>Date:</strong> {result.date}</p>
          <p><strong>Already Booked:</strong> {result.alreadyBooked}</p>
          <p><strong>Predicted Patients:</strong> {result.predictedPatients}</p>
          <p><strong>Crowd Level:</strong> {result.crowdLevel}</p>
        </div>
      )}
    </div>
  );
}
