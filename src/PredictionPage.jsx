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
      const res = await fetch("http://localhost:8000/predict", {
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
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "linear-gradient(to bottom, #e0f2fe, #f0f9ff)",
        fontFamily: "Inter, sans-serif",
        padding: "40px 20px",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
      }}
    >
      {/* Header */}
      <h1
        style={{
          fontSize: "2.2rem",
          fontWeight: "700",
          color: "#1e3a8a",
          display: "flex",
          alignItems: "center",
          gap: "10px",
          marginBottom: "30px",
        }}
      >
        🩺 Patient Load Prediction
      </h1>

      {/* Input Section */}
      <div
        style={{
          background: "white",
          borderRadius: "20px",
          boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
          padding: "20px 30px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: "20px",
          width: "100%",
          maxWidth: "900px",
        }}
      >
        {/* Date Input */}
        <div style={{ display: "flex", flexDirection: "column" }}>
          <label
            style={{
              color: "#334155",
              fontSize: "0.9rem",
              fontWeight: 500,
              marginBottom: "5px",
            }}
          >
            Date
          </label>
          <input
            type="date"
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
            style={{
              border: "1px solid #cbd5e1",
              borderRadius: "8px",
              padding: "8px 12px",
              width: "180px",
              fontSize: "0.95rem",
              outline: "none",
            }}
          />
        </div>

        {/* Department Input */}
        <div style={{ display: "flex", flexDirection: "column" }}>
          <label
            style={{
              color: "#334155",
              fontSize: "0.9rem",
              fontWeight: 500,
              marginBottom: "5px",
            }}
          >
            Department
          </label>
          <select
            value={selectedDepartment}
            onChange={(e) => setSelectedDepartment(e.target.value)}
            style={{
              border: "1px solid #cbd5e1",
              borderRadius: "8px",
              padding: "8px 12px",
              width: "200px",
              fontSize: "0.95rem",
              outline: "none",
            }}
          >
            <option value="">-- Select Department --</option>
            <option value="Cardiology">Cardiology</option>
            <option value="Neurology">Neurology</option>
            <option value="Orthopedics">Orthopedics</option>
            <option value="Pediatrics">Pediatrics</option>
            <option value="General Medicine">General Medicine</option>
            <option value="Dermatology">Dermatology</option>
          </select>
        </div>

        {/* Predict Button */}
        <button
          onClick={handlePredict}
          disabled={loading}
          style={{
            background: "#2563eb",
            color: "white",
            fontWeight: 600,
            padding: "12px 24px",
            borderRadius: "10px",
            border: "none",
            cursor: "pointer",
            fontSize: "1rem",
            marginTop: "20px",
            transition: "all 0.3s",
          }}
          onMouseOver={(e) => (e.target.style.background = "#1e40af")}
          onMouseOut={(e) => (e.target.style.background = "#2563eb")}
        >
          {loading ? "Predicting..." : "🔍 Predict"}
        </button>
      </div>

      {/* Error Message */}
      {error && (
        <p style={{ color: "#dc2626", marginTop: "15px", fontWeight: 500 }}>
          {error}
        </p>
      )}

      {/* Chart Display */}
      {chartData.length > 0 && (
        <div
          style={{
            background: "white",
            borderRadius: "16px",
            boxShadow: "0 4px 15px rgba(0,0,0,0.1)",
            padding: "25px",
            marginTop: "40px",
            width: "100%",
            maxWidth: "800px",
          }}
        >
          <h2
            style={{
              textAlign: "center",
              color: "#1e3a8a",
              fontWeight: 600,
              fontSize: "1.3rem",
              marginBottom: "20px",
            }}
          >
            Predicted Patient Count (Hourly)
          </h2>

          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="hour" />
              <YAxis />
              <Tooltip />
              <Line
                type="monotone"
                dataKey="predicted"
                stroke="#2563eb"
                strokeWidth={3}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>

          <div style={{ textAlign: "center", marginTop: "20px" }}>
            <p style={{ fontSize: "1.1rem" }}>
              Total Predicted Patients:{" "}
              <strong style={{ color: "#1e3a8a" }}>{totalPatients}</strong>
            </p>
            <p style={{ color: "#475569", marginTop: "5px" }}>
              Department: <strong>{selectedDepartment}</strong> | Date:{" "}
              <strong>{selectedDate}</strong>
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
