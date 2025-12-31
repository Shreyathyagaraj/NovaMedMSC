import React, { useState } from "react";
import "./LoginPage.css";
import { Link, useNavigate } from "react-router-dom";
import { FaGoogle, FaEnvelope, FaLock } from "react-icons/fa";
import { signInWithGoogle, auth } from "./firebase";
import { signInWithEmailAndPassword } from "firebase/auth";

export default function LoginPage() {
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loadingEmail, setLoadingEmail] = useState(false);
  const [loadingGoogle, setLoadingGoogle] = useState(false);

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoadingEmail(true);
    try {
      await signInWithEmailAndPassword(auth, email, password);
      navigate("/home");
    } catch (error) {
      alert(error.message);
    } finally {
      setLoadingEmail(false);
    }
  };

  const handleGoogleLogin = async () => {
    setLoadingGoogle(true);
    try {
      const user = await signInWithGoogle();
      if (user) navigate("/home");
    } catch (error) {
      alert("Google sign-in failed");
    } finally {
      setLoadingGoogle(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-bg-overlay" />

      <div className="login-card animate-in">
        {/* Title */}
        <h1 className="brand-title">
          NovaMed <span>Multispeciality Care</span>
        </h1>
        <p className="brand-slogan">“There is no true illness”</p>

        {/* Email Login */}
        <form onSubmit={handleLogin} className="login-form">
          <div className="input-group">
            <FaEnvelope className="input-icon" />
            <input
              type="email"
              placeholder="Email address"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              disabled={loadingEmail || loadingGoogle}
            />
          </div>

          <div className="input-group">
            <FaLock className="input-icon" />
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={loadingEmail || loadingGoogle}
            />
          </div>

          <button
            type="submit"
            className="primary-btn"
            disabled={loadingEmail}
          >
            {loadingEmail ? <span className="spinner" /> : "Sign In"}
          </button>
        </form>

        {/* Divider */}
        <div className="divider">
          <span>OR</span>
        </div>

        {/* Google Login */}
        <div className="google-btn-wrapper">
          <button
            className="google-btn"
            onClick={handleGoogleLogin}
            disabled={loadingGoogle}
          >
            {loadingGoogle ? (
              <span className="spinner small" />
            ) : (
              <>
                <FaGoogle />
                <span>Continue with Google</span>
              </>
            )}
          </button>
        </div>

        <p className="signup-text">
          Don’t have an account? <Link to="/signup">Create one</Link>
        </p>
      </div>
    </div>
  );
}
