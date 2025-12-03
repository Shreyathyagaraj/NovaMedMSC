import React, { useState } from "react";
import "./LoginPage.css";
import { Link, useNavigate } from "react-router-dom";
import { FaGoogle } from "react-icons/fa";
import { signInWithGoogle, auth } from "./firebase"; 
import { signInWithEmailAndPassword } from "firebase/auth";

export default function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const handleLogin = async (e) => {
    e.preventDefault();
    try {
      await signInWithEmailAndPassword(auth, email, password);
      alert("Login Successful!");
      navigate("/home"); // redirect after login
    } catch (error) {
      console.error("Login error:", error.message);
      alert(error.message);
    }
  };

  const handleGoogleLogin = async () => {
    try {
      const user = await signInWithGoogle(); 
      if (user) {
        alert("Google Login Successful!");
        navigate("/home");
      }
    } catch (error) {
      alert("Google sign-in failed: " + error.message);
    }
  };

  return (
    <div className="login-page">
      {/* Blurred background */}
      <div className="login-bg"></div>

      {/* Login box */}
      <div className="login-box">
        <div className="header">
          <h1>NovaMed Multispeciality Care</h1>
          <p className="tagline">"Let there be no true illness"</p>
        </div>

        <form onSubmit={handleLogin} className="form">
          <label>Email Address</label>
          <input
            type="email"
            placeholder="Enter your email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />

          <label>Password</label>
          <input
            type="password"
            placeholder="Enter your password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />

          <button type="submit" className="login-btn">Login</button>
        </form>

        <div className="divider"><span>or</span></div>

        <button className="social-btn google" onClick={handleGoogleLogin}>
          <FaGoogle className="icon" /> Continue with Google
        </button>

        <p className="signup-text">
          Don’t have an account? <Link to="/signup">Sign up</Link>
        </p>
      </div>
    </div>
  );
}
