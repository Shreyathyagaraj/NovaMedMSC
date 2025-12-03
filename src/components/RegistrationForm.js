import React, { useState } from "react";
import { registerPatient } from "../api/api";

export default function RegistrationForm() {
  const [formData, setFormData] = useState({
    firstName: "",
    lastName: "",
    phoneNumber: ""
  });
  const [message, setMessage] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    const result = await registerPatient(formData);
    if(result.success){
      setMessage(`Registered successfully! Patient ID: ${result.patient_id}`);
    } else {
      setMessage(`Error: ${result.error}`);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <input placeholder="First Name" onChange={e => setFormData({...formData, firstName: e.target.value})} />
      <input placeholder="Last Name" onChange={e => setFormData({...formData, lastName: e.target.value})} />
      <input placeholder="Phone Number" onChange={e => setFormData({...formData, phoneNumber: e.target.value})} />
      <button type="submit">Register</button>
      <p>{message}</p>
    </form>
  );
}
