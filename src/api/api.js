export const registerPatient = async (formData) => {
  const response = await fetch("http://localhost:8000/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(formData),
  });
  return response.json();
};
