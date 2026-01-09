// src/App.js
import React from "react";
import {
  BrowserRouter as Router,
  Routes,
  Route,
  useParams,
  Link,
  useLocation,
} from "react-router-dom";

import LoginPage from "./LoginPage";
import SignupPage from "./SignupPage";
import HomePage from "./HomePage";
import AppointmentPage from "./AppointmentPage";
import PredictionPage from "./PredictionPage";
import PatientList from "./components/PatientList";
import FAQPage from "./FAQPage";

// ✅ Wrapper to extract department name
function AppointmentPageWrapper() {
  const { departmentName } = useParams();
  return <AppointmentPage department={departmentName} />;
}

// ✅ Navbar Component
function Navbar() {
  return (
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
      <Link to="/home" style={navLink}>🏠 Home</Link>
      <Link to="/patients" style={navLink}>📋 Patients</Link>
      <Link to="/predict" style={navLink}>📊 Prediction</Link>
      <Link to="/faq" style={navLink}>❓ FAQ</Link>
      <Link to="/" style={navLink}>🔐 Logout</Link>
    </nav>
  );
}

// ✅ App Layout (controls navbar visibility)
function AppLayout() {
  const location = useLocation();

  // ❌ Routes where navbar should NOT appear
  const hideNavbarRoutes = ["/", "/signup"];

  const showNavbar = !hideNavbarRoutes.includes(location.pathname);

  return (
    <>
      {showNavbar && <Navbar />}

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
    </>
  );
}

// ✅ Main App
export default function App() {
  return (
    <Router>
      <AppLayout />
    </Router>
  );
}

// ✅ Navbar link style
const navLink = {
  color: "white",
  textDecoration: "none",
  fontSize: "16px",
  fontWeight: "500",
  transition: "0.3s",
};
