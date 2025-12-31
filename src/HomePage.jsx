// src/HomePage.jsx
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import "./HomePage.css";

export default function HomePage() {
  const navigate = useNavigate();

  const departments = [
    { name: "General Surgeon", description: "(Handles surgical procedures)", doct: "DR.BALAJI PRABHAKARAN", qual: "MBBS, MS (General Surgery)" },
    { name: "Orthopedics", description: "(Bone, joint, and muscle care)", doct: "DR.DEVENDRA KUMAR.P", qual: "MBBS, DNB (Orthopaedics)" },
    { name: "Pediatrics", description: "(Child health and wellness services)", doct: "DR.ARCHANA K M", qual: "MBBS, MD (Paediatrics)" },
    { name: "ENT Specialist", description: "(Diagnosis and treatment of Head and neck)", doct: "DR.ROHAN M DIXITH", qual: "MBBS, MS (ENT)" },
    { name: "Dermatology", description: "(Diagnosis and treatment of skin and hair)", doct: "DR.BHAVISHYA K SHETTY", qual: "MBBS, MD (Dermatology)" },
    { name: "Physician", description: "(Identifying illness and injuries)", doct: "DR.SATHVIK JAIN", qual: "MBBS, MD (General Medicine)" },
    { name: "Anaesthesiology", description: "(Administering anaesthesia)", doct: "DR.CHAITRA R", qual: "MBBS, DA (Anaesthesiology)" },
    { name: "Ophthalmology", description: "(Diagnosis and treatment of eye disorders)", doct: "DR.SUBHASHCHANDRA", qual: "MBBS, MS (Ophthalmology)" },
    { name: "Gynecology", description: "(Specializing in female reproductive system)", doct: "DR.SWARNALATHA", qual: "MBBS, MS (Obst & Gynae)" },
    { name: "Dentist", description: "(Dental care and treatment)", doct: "DR.MEERA ANUPAM", qual: "BDS" },
  ];

  const handleAppointment = (deptName) => {
    navigate(`/appointment/${encodeURIComponent(deptName)}`);
  };

  // Chatbot state
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([
    { from: "bot", text: "Hello 👋! I’m Nova, your health assistant. How can I help you today?" },
  ]);
  const [userInput, setUserInput] = useState("");
  const [sessionId] = useState(() => "sess-" + Math.random().toString(36).slice(2, 10));

  // Send user message to backend /chatbot (FastAPI)
  const handleSend = async () => {
    if (!userInput.trim()) return;
    const newMessages = [...messages, { from: "user", text: userInput }];
    setMessages(newMessages);

    // call backend chatbot
    try {
      const res = await fetch("http://localhost:8000/chatbot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userInput, session_id: sessionId }),
      });
      const json = await res.json();
      const reply = json.reply || "Sorry, no reply.";

      setMessages([...newMessages, { from: "bot", text: reply }]);
    } catch (err) {
      console.error("Chatbot error:", err);
      setMessages([...newMessages, { from: "bot", text: "⚠️ Could not reach chatbot server." }]);
    } finally {
      setUserInput("");
    }
  };

  return (
    <div className="home-layout">
      {/* Sidebar */}
      <aside className="sidebar">
        <h2>Menu</h2>
        <ul>
          <li onClick={() => navigate("/")}>🏠 Home</li>
          <li onClick={() => navigate("/predict")}>📊 Prediction</li>
          <li onClick={() => navigate("/faq")}>❓ FAQ</li>
        </ul>
      </aside>

      {/* Main Content */}
      <div className="home-container">
        <header className="home-header">
          <h1>NovaMed Multispeciality Care</h1>
          <p className="tagline">"Let there be no true illness"</p>
        </header>

        <div className="image-section">
          <img src="https://static.vecteezy.com/system/resources/thumbnails/036/372/442/small/hospital-building-with-ambulance-emergency-car-on-cityscape-background-cartoon-illustration-vector.jpg" alt="Hospital" className="hospital-image" />
          <div className="predict-box">
            <h3>📊 Patient Prediction</h3>
            <p>Get insights into the expected patient count for the selected date. Helps in planning the date and time of the visit.We hope you will have best experience at our place. Serving your problems is our responsibility</p>
            <div className="graph-placeholder"></div>
            <button className="predict-btn" onClick={() => navigate("/predict")}>Predict Patient Count</button>
          </div>
        </div>
        <section className="departments">
          <h2>Our Departments</h2>
          <div className="department-list">
            {departments.map((dept, index) => (
              <div className="department-card" key={index}>
                <h3>{dept.name}</h3>
                <p>{dept.description}</p>
                <h5>{dept.doct}</h5>
                <h5>{dept.qual}</h5>
                <button className="appointment-btn" onClick={() => handleAppointment(dept.name)}>Book Appointment</button>
              </div>
            ))}
          </div>
        </section>

        <footer className="hospital-info">
          <h2 style={{ textAlign: "center" }}>About Our Hospital</h2>
          <p style={{ textAlign: "center" }}>
            NovaMEd Multispeciality Hospital, provides comprehensive healthcare services with state-of-the-art facilities and expert doctors.
          </p>
        </footer>

        
      </div>
    </div>
  );
}
