from fpdf import FPDF
import os

def generate_patient_pdf(patient: dict) -> str:
    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "NovaMed Multi-speciality Care", ln=True)

    pdf.ln(5)
    pdf.set_font("Helvetica", "", 12)

    for k, v in patient.items():
        if k in ["PatientID", "FirstName", "LastName", "Department", "RegistrationDate", "RegistrationTime"]:
            pdf.cell(0, 8, f"{k}: {v}", ln=True)

    os.makedirs("reports", exist_ok=True)
    file_path = f"reports/{patient['PatientID']}.pdf"
    pdf.output(file_path)

    return file_path
