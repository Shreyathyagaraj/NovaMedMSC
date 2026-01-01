from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import os

REPORT_DIR = "reports"
os.makedirs(REPORT_DIR, exist_ok=True)

def generate_report_pdf(patient: dict):
    pid = patient["PatientID"]
    path = f"{REPORT_DIR}/{pid}.pdf"

    c = canvas.Canvas(path, pagesize=A4)
    text = c.beginText(40, 800)

    text.setFont("Helvetica", 12)
    text.textLine("NovaMed Multispeciality Hospital")
    text.textLine("-" * 40)
    text.textLine(f"Patient ID: {pid}")
    text.textLine(f"Name: {patient['FirstName']} {patient['LastName']}")
    text.textLine(f"Department: {patient['Department']}")
    text.textLine(f"Date: {patient['RegistrationDate']}")
    text.textLine(f"Time: {patient['RegistrationTime']}")
    text.textLine("")
    text.textLine("Please arrive 5 minutes early.")
    text.textLine("Get well soon!")

    c.drawText(text)
    c.showPage()
    c.save()

    return path
