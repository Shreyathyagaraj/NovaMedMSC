import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createUserWithEmailAndPassword } from "firebase/auth"; 
import { auth } from "./firebase"; // make sure you have firebase.js file
import "./SignupPage.css";

export default function SignupPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const handleSignup = async (e) => {
    e.preventDefault();

    if (!name || !email || !password) {
      alert("Please fill in all fields");
      return;
    }
    if (password.length < 8) {
    alert("Password must be at least 8 characters long");
    return;
  }

    try {
      // ✅ Create user in Firebase
      await createUserWithEmailAndPassword(auth, email, password);

      // Optionally store name in localStorage (or Firestore if needed)
      localStorage.setItem("userName", name);

      alert("Signup Successful!");
      navigate("/home"); // redirect to homepage
    } catch (error) {
      console.error("Signup error:", error.message);
      alert(error.message);
    }
  };

  return (
    <div className="signup-container">
      <div className="signup-box">
        <h1>Create Your Account</h1>
        <p>Join SDM Multispeciality Hospital Portal</p>

        <form onSubmit={handleSignup}>
          <label>Full Name</label>
          <input
            type="text"
            placeholder="Enter your full name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />

          <label>Email Address</label>
          <input
            type="email"
            placeholder="Enter your email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />

          <label>Create Password</label>
          <input
            type="password"
            placeholder="Create a strong password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />

          <button type="submit" className="signup-btn">
            Sign Up
          </button>
        </form>
      </div>
    </div>
  );
}
