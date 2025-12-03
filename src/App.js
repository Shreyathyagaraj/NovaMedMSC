// src/App.js
import React from "react";
import {
  BrowserRouter as Router,
  Routes,
  Route,
  useParams,
  Link,
} from "react-router-dom";

import LoginPage from "./LoginPage";
import SignupPage from "./SignupPage";
import HomePage from "./HomePage";
import AppointmentPage from "./AppointmentPage";
import PredictionPage from "./PredictionPage";
import PatientList from "./components/PatientList";
import FAQPage from "./FAQPage";


// ✅ Wrapper to extract department name from the URL
function AppointmentPageWrapper() {
  const { departmentName } = useParams();
  return <AppointmentPage department={departmentName} />;
}

// ✅ Main App
export default function App() {
  return (
    <Router>
      {/* 🔝 Navigation Bar */}
      <nav
        style={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          padding: "12px",
          backgroundColor: "#007bff",
          color: "white",
          fontWeight: "500",
          gap: "20px",
          position: "sticky",
          top: 0,
          zIndex: 1000,
        }}
      >
        <Link to="/home" style={navLink}>
          🏠 Home
        </Link>
        <Link to="/patients" style={navLink}>
          📋 Patients
        </Link>
        <Link to="/predict" style={navLink}>
          📊 Prediction
        </Link>
        <Link to="/faq" style={navLink}>
          ❓ FAQ
        </Link>
        <Link to="/" style={navLink}>
          🔐 Logout
        </Link>
      </nav>

      {/* ✅ Page Routes */}
      <Routes>
        <Route path="/" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/home" element={<HomePage />} />
        <Route path="/faq" element={<FAQPage />} />
        <Route path="/predict" element={<PredictionPage />} />
        <Route path="/patients" element={<PatientList />} />
        <Route
          path="/appointment/:departmentName"
          element={<AppointmentPageWrapper />}
        />
      </Routes>
      
    </Router>
  );
}

// ✅ Styling for navigation links
const navLink = {
  color: "white",
  textDecoration: "none",
  fontSize: "16px",
  fontWeight: "500",
  transition: "0.3s",
};

