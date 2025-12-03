// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
import { getAuth, GoogleAuthProvider, signInWithPopup } from "firebase/auth";
import { getFirestore } from "firebase/firestore";

// Your web app's Firebase configuration
const firebaseConfig = {
  apiKey: "AIzaSyAP1K8sXth10RunUVIsXuO41Ubq9J5Aj58",
  authDomain: "hospital-registration-41343.firebaseapp.com",
  projectId: "hospital-registration-41343",
  storageBucket: "hospital-registration-41343.firebasestorage.app",
  messagingSenderId: "961276628394",
  appId: "1:961276628394:web:5b85966780dbb287cc6fd3"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);

// Auth setup
const auth = getAuth(app);
const provider = new GoogleAuthProvider();

// Firestore setup
const db = getFirestore(app);

// Google sign-in
export const signInWithGoogle = async () => {
  try {
    const result = await signInWithPopup(auth, provider);
    console.log("User signed in:", result.user);
    return result.user;
  } catch (error) {
    console.error("Google Sign-in Error:", error);
    throw error;
  }
};

// ✅ Export everything you need
export { auth, provider, db };
