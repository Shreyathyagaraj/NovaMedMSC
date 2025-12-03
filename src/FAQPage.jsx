// src/FAQPage.jsx
import React, { useState } from "react";
import "./FAQPage.css";

export default function FAQPage() {
  const [openIndex, setOpenIndex] = useState(null);

  const faqs = [
    {
      question: "How can I book an appointment?",
      answer: "You can book an appointment online by visiting the Appointment page and selecting the desired department."
    },
    {
      question: "What are the hospital timings?",
      answer: "Our hospital is open 24/7. However, doctor consultation timings vary by department."
    },
    {
      question: "Can I cancel or reschedule my appointment?",
      answer: "Yes, appointments can be rescheduled or canceled by contacting the hospital helpdesk at least 24 hours in advance."
    },
    {
      question: "Do you provide emergency services?",
      answer: "Yes, we have a dedicated emergency ward available 24/7 for critical cases."
    },
    {
      question: "Is online payment available?",
      answer: "Currently, we accept payments at the hospital. Online payment integration is coming soon."
    }
  ];

  const toggleFAQ = (index) => {
    setOpenIndex(openIndex === index ? null : index);
  };

  return (
    <div className="faq-container">
      <h2>Frequently Asked Questions</h2>
      <div className="faq-list">
        {faqs.map((item, index) => (
          <div key={index} className={`faq-item ${openIndex === index ? "open" : ""}`}>
            <button className="faq-question" onClick={() => toggleFAQ(index)}>
              {item.question}
              <span className="arrow">{openIndex === index ? "▲" : "▼"}</span>
            </button>
            {openIndex === index && <p className="faq-answer">{item.answer}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}
