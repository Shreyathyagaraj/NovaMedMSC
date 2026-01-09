import React, { useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer
} from "recharts";
import { BACKEND_URL } from "./config";
import "./PredictionPage.css";

export default function PredictionPage() {
  const [date, setDate] = useState("");
  const [department, setDepartment] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const predict = async () => {
    setError("");
    setResult(null);
    if (!date || !department) {
      setError("Select date & department");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${BACKEND_URL}/predict`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date, department })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);
      setResult(data);
    } catch (e) {
      setError(e.message);
    }
    setLoading(false);
  };

  return (
    <div className="prediction-page">
      <h1>🩺 Patient Load Prediction</h1>

      <div className="input-card">
        <div>
          <label>Date</label>
          <input type="date" value={date} onChange={e => setDate(e.target.value)} />
        </div>

        <div>
          <label>Department</label>
          <select value={department} onChange={e => setDepartment(e.target.value)}>
            <option value="">Select</option>
            {[
              "Cardiology","Pediatrics","Dermatology","Dentist","ENT",
              "Gynecology","Anesthesiology","General Surgeon","Physician","Ophthalmology"
            ].map(d => <option key={d}>{d}</option>)}
          </select>
        </div>

        <button onClick={predict}>{loading ? "Predicting..." : "🔍 Predict"}</button>
      </div>

      {error && <p className="error">{error}</p>}

      {result && (
        <>
          <div className="stats">
            <div className="card"><h4>Already Booked</h4><p>{result.alreadyBooked}</p></div>
            <div className="card"><h4>Hourly Avg Load</h4><p>{result.hourlyAvg}</p></div>
            <div className="card"><h4>Estimated Daily Visits</h4><p>{result.estimatedRange}</p></div>
            <div className="card crowd"><h4>Crowd Level</h4><p>{result.crowdLevel}</p></div>
          </div>

          <div className="chart-card">
            <h3>Hour-wise Patient Prediction</h3>
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={result.chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="hour" />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey="predicted" stroke="#2563eb" strokeWidth={3} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}
