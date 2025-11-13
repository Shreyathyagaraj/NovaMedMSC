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
            <p>Get insights into the expected patient count for the selected date. Helps in planning the date and time of the visit.</p>
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
            SDM Multispeciality Hospital, Ujire, provides comprehensive healthcare services with state-of-the-art facilities and expert doctors.
          </p>
        </footer>

        {/* Floating Chatbot Button */}
        <div
          className="chatbot-toggle"
          onClick={() => setIsOpen(!isOpen)}
          style={{
            position: "fixed",
            bottom: "20px",
            right: "20px",
            backgroundColor: "#0066cc",
            color: "white",
            borderRadius: "50%",
            width: "60px",
            height: "60px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "28px",
            cursor: "pointer",
            boxShadow: "0 2px 8px rgba(0,0,0,0.3)",
            zIndex: 9999,
          }}
        >
          💬
        </div>

        {/* Chatbot Window */}
        {isOpen && (
          <div
            className="chatbot-window"
            style={{
              position: "fixed",
              bottom: "90px",
              right: "20px",
              width: "340px",
              height: "420px",
              backgroundColor: "#fff",
              borderRadius: "10px",
              boxShadow: "0 4px 10px rgba(0,0,0,0.2)",
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
              zIndex: 10000,
            }}
          >
            <div style={{ backgroundColor: "#0066cc", color: "white", padding: "10px", textAlign: "center" }}>🩺 Nova Assistant</div>

            <div style={{ flex: 1, padding: "10px", overflowY: "auto", background: "#f9f9f9" }}>
              {messages.map((msg, idx) => (
                <div key={idx} style={{ textAlign: msg.from === "bot" ? "left" : "right", margin: "6px 0" }}>
                  <div style={{
                    display: "inline-block",
                    backgroundColor: msg.from === "bot" ? "#e0e0e0" : "#0066cc",
                    color: msg.from === "bot" ? "black" : "white",
                    padding: "8px 12px",
                    borderRadius: "10px",
                    maxWidth: "80%",
                    wordBreak: "break-word"
                  }}>
                    {msg.text}
                  </div>
                </div>
              ))}
            </div>

            <div style={{ display: "flex", padding: "8px", background: "#eee" }}>
              <input
                type="text"
                value={userInput}
                onChange={(e) => setUserInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSend()}
                placeholder="Type your message..."
                style={{ flex: 1, borderRadius: "20px", border: "1px solid #ccc", padding: "8px 12px" }}
              />
              <button onClick={handleSend} style={{ marginLeft: "8px", backgroundColor: "#0066cc", color: "white", border: "none", borderRadius: "20px", padding: "8px 14px" }}>Send</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
