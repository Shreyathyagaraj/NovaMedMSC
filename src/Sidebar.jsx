// Sidebar.jsx
import React from "react";
import { Link } from "react-router-dom";
import "./Sidebar.css";

export default function Sidebar() {
  return (
    <div className="sidebar">
      <h3>Navigation</h3>
      <ul>
        <li><Link to="/appointment">Appointment</Link></li>
        <li><Link to="/prediction">Prediction</Link></li>
        <li><Link to="/faq">FAQ</Link></li>
      </ul>
    </div>
  );
}
