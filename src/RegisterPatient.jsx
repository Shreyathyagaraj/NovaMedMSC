import React, { useState } from "react";
import axios from "axios";

export default function RegisterPatient() {
  const [form, setForm] = useState({
    name: "",
    age: "",
    gender: "",
    phone: "",
    email: "",
    address: "",
    appointment_date: "",
    department: "",
    doctor: ""
  });

  const [loading, setLoading] = useState(false);

  const handleChange = (e) => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);

    try {
      const response = await axios.post("http://127.0.0.1:8000/register_patient", {
        name: form.name,
        age: parseInt(form.age),
        gender: form.gender,
        phone: form.phone,
        email: form.email,
        address: form.address,
        appointment_date: form.appointment_date,
        department: form.department,
        doctor: form.doctor,
      });

      console.log("✅ Success:", response.data);
      alert("✅ Registered successfully! WhatsApp message sent.");
      
      // Reset form
      setForm({
        name: "",
        age: "",
        gender: "",
        phone: "",
        email: "",
        address: "",
        appointment_date: "",
        department: "",
        doctor: ""
      });

    } catch (error) {
      console.error("❌ Registration error:", error.response?.data || error.message);
      alert("❌ Registration failed. Please check console for details.");
    }

    setLoading(false);
  };

  return (
    <form onSubmit={handleSubmit} style={styles.form}>
      <h2>🩺 Patient Registration</h2>

      {Object.keys(form).map((field) => (
        <input
          key={field}
          type={field === "age" ? "number" : "text"}
          name={field}
          placeholder={field.replace("_", " ").toUpperCase()}
          value={form[field]}
          onChange={handleChange}
          required={["name", "age", "gender", "phone", "department"].includes(field)}
          style={styles.input}
        />
      ))}

      <button type="submit" disabled={loading} style={styles.button}>
        {loading ? "Registering..." : "Register"}
      </button>
    </form>
  );
}

const styles = {
  form: {
    display: "flex",
    flexDirection: "column",
    maxWidth: "400px",
    margin: "auto",
    padding: "20px",
    background: "#f9f9f9",
    borderRadius: "10px",
  },
  input: {
    margin: "8px 0",
    padding: "10px",
    borderRadius: "5px",
    border: "1px solid #ccc",
  },
  button: {
    backgroundColor: "#007bff",
    color: "white",
    border: "none",
    padding: "10px",
    borderRadius: "5px",
    cursor: "pointer",
  },
};
