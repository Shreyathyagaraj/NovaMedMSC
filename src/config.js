// Detect if running locally
const isLocalhost =
  window.location.hostname === "localhost" ||
  window.location.hostname === "127.0.0.1";

// Backend URLs
const LOCAL_BACKEND = "http://localhost:8000"; 
const PROD_BACKEND = "https://novamedmsc-back.onrender.com";

// Export final dynamic backend URL
export const BACKEND_URL = isLocalhost ? LOCAL_BACKEND : PROD_BACKEND;

console.log("Backend in use:", BACKEND_URL);
