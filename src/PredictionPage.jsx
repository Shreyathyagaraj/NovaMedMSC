import React, { useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ResponsiveContainer,
} from "recharts";
import { BACKEND_URL } from "./config";

export default function PredictionPage() {
  const [selectedDate, setSelectedDate] = useState("");
  const [selectedDepartment, setSelectedDepartment] = useState("");
  const [chartData, setChartData] = useState([]);
  const [totalPatients, setTotalPatients] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handlePredict = async () => {
    setError("");

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

      const data = await res.json();

      if (data.error) throw new Error(data.error);

      setChartData(data.chartData);
      setTotalPatients(data.totalPatients);
    } catch (err) {
      setError(err.message || "Failed to fetch prediction.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "linear-gradient(to bottom, #e0f2fe, #f0f9ff)",
        padding: "40px 20px",
      }}
    >
      <h1
        style={{
          fontSize: "2.2rem",
          fontWeight: "700",
          color: "#1e3a8a",
          textAlign: "center",
        }}
      >
        🩺 Patient Load Prediction
      </h1>

      <div
        style={{
          background: "white",
          borderRadius: "20px",
          padding: "20px",
          boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
          maxWidth: "900px",
          margin: "auto",
          marginTop: "20px",
          display: "flex",
          gap: "20px",
          justifyContent: "center",
        }}
      >
        {/* DATE */}
        <div>
          <label>Date</label>
          <input
            type="date"
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
          />
        </div>

        {/* DEPARTMENT */}
        <div>
          <label>Department</label>
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

        <button onClick={handlePredict}>
          {loading ? "Predicting..." : "🔍 Predict"}
        </button>
      </div>

      {error && (
        <p style={{ color: "red", textAlign: "center", marginTop: "10px" }}>
          {error}
        </p>
      )}

      {chartData.length > 0 && (
        <div
          style={{
            background: "white",
            marginTop: "40px",
            borderRadius: "16px",
            padding: "20px",
            maxWidth: "800px",
            marginLeft: "auto",
            marginRight: "auto",
          }}
        >
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="hour" />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="predicted" stroke="#2563eb" />
            </LineChart>
          </ResponsiveContainer>

          <p style={{ textAlign: "center", marginTop: "15px" }}>
            Total Predicted Patients: <strong>{totalPatients}</strong>
          </p>
        </div>
      )}
    </div>
  );
}
