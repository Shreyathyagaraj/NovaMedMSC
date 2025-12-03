import React, { useEffect, useState } from "react";
import {
  collection,
  getDocs,
  doc,
  deleteDoc,
  updateDoc,
} from "firebase/firestore";
import { db } from "../firebase";
import "./PatientList.css";

export default function PatientList() {
  const [patients, setPatients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filterDept, setFilterDept] = useState("");
  const [sortField, setSortField] = useState("name");
  const [sortOrder, setSortOrder] = useState("asc");
  const [editingPatient, setEditingPatient] = useState(null);

  useEffect(() => {
    fetchPatients();
  }, []);

  const fetchPatients = async () => {
    setLoading(true);
    try {
      const querySnapshot = await getDocs(collection(db, "patients"));
      const data = querySnapshot.docs.map((doc) => ({
        id: doc.id,
        ...doc.data(),
      }));
      setPatients(data);
    } catch (error) {
      console.error("Error fetching patients:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id) => {
    if (window.confirm("Are you sure you want to delete this patient?")) {
      await deleteDoc(doc(db, "patients", id));
      setPatients(patients.filter((p) => p.id !== id));
    }
  };

  const handleEditChange = (field, value) => {
    setEditingPatient({ ...editingPatient, [field]: value });
  };

  const saveEdit = async () => {
    if (!editingPatient) return;

    const docRef = doc(db, "patients", editingPatient.id);
    await updateDoc(docRef, editingPatient);
    setPatients(
      patients.map((p) => (p.id === editingPatient.id ? editingPatient : p))
    );
    setEditingPatient(null);
  };

  const filteredPatients = patients
    .filter((p) => {
      const matchesSearch = p.name
        ?.toLowerCase()
        .includes(search.toLowerCase());
      const matchesDept = filterDept ? p.department === filterDept : true;
      return matchesSearch && matchesDept;
    })
    .sort((a, b) => {
      const fieldA = a[sortField] || "";
      const fieldB = b[sortField] || "";
      return sortOrder === "asc"
        ? fieldA.localeCompare(fieldB)
        : fieldB.localeCompare(fieldA);
    });

  return (
    <div className="patient-list-container">
      <h2>🩺 Registered Patients</h2>

      {/* Filters */}
      <div className="filters">
        <input
          type="text"
          placeholder="Search by name..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        <select
          value={filterDept}
          onChange={(e) => setFilterDept(e.target.value)}
        >
          <option value="">All Departments</option>
          <option value="Cardiology">Cardiology</option>
          <option value="Neurology">Neurology</option>
          <option value="ENT">ENT</option>
          <option value="Dermatology">Dermatology</option>
        </select>

        <select value={sortField} onChange={(e) => setSortField(e.target.value)}>
          <option value="name">Sort by Name</option>
          <option value="department">Sort by Department</option>
        </select>

        <button
          onClick={() =>
            setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"))
          }
          className="sort-btn"
        >
          {sortOrder === "asc" ? "⬆️ Asc" : "⬇️ Desc"}
        </button>
      </div>

      {loading ? (
        <p className="loading">Loading patient records...</p>
      ) : filteredPatients.length === 0 ? (
        <p>No matching records found.</p>
      ) : (
        <table className="patient-table">
          <thead>
            <tr>
              <th>Patient ID</th>
              <th>Name</th>
              <th>Age</th>
              <th>Gender</th>
              <th>Department</th>
              <th>Doctor</th>
              <th>Date</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredPatients.map((p) => (
              <tr key={p.id}>
                <td>{p.id}</td>
                <td>{p.name}</td>
                <td>{p.age}</td>
                <td>{p.gender}</td>
                <td>{p.department}</td>
                <td>{p.doctor}</td>
                <td>{p.appointment_date}</td>
                <td>
                  <button onClick={() => setEditingPatient(p)}>✏️ Edit</button>
                  <button onClick={() => handleDelete(p.id)}>🗑️ Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* ✨ Edit Modal */}
      {editingPatient && (
        <div className="modal-overlay">
          <div className="modal">
            <h3>✏️ Edit Patient Details</h3>
            <div className="modal-content">
              <label>Name</label>
              <input
                value={editingPatient.name}
                onChange={(e) => handleEditChange("name", e.target.value)}
              />

              <label>Age</label>
              <input
                type="number"
                value={editingPatient.age}
                onChange={(e) => handleEditChange("age", e.target.value)}
              />

              <label>Gender</label>
              <select
                value={editingPatient.gender}
                onChange={(e) => handleEditChange("gender", e.target.value)}
              >
                <option>Male</option>
                <option>Female</option>
                <option>Other</option>
              </select>

              <label>Department</label>
              <input
                value={editingPatient.department}
                onChange={(e) => handleEditChange("department", e.target.value)}
              />

              <label>Doctor</label>
              <input
                value={editingPatient.doctor}
                onChange={(e) => handleEditChange("doctor", e.target.value)}
              />

              <label>Appointment Date</label>
              <input
                type="date"
                value={editingPatient.appointment_date}
                onChange={(e) =>
                  handleEditChange("appointment_date", e.target.value)
                }
              />

              <div className="modal-buttons">
                <button onClick={saveEdit} className="save-btn">
                  💾 Save
                </button>
                <button
                  onClick={() => setEditingPatient(null)}
                  className="cancel-btn"
                >
                  ❌ Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
