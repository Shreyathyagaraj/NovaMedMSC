import os
import io
import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from firebase_admin import firestore
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# If firebase is already initialized in your project, no need to reinitialize
db = firestore.client()

router = APIRouter()
logger = logging.getLogger("support_reports")


# ---------------- NLP SUPPORT --------------------
@router.post("/nlp_support")
async def nlp_support(req: Request):
    data = await req.json()
    query = data.get("query", "").lower()

    if not query:
        return JSONResponse({"answer": "Please type your question."})

    # RULE-BASED ANSWERS (no external API needed)
    if "appointment" in query:
        return {"answer": "To book an appointment, choose 'Book Appointment' and follow the steps."}

    if "report" in query:
        return {"answer": "To get your report, select Get Report and send your Patient ID."}

    if "timing" in query or "time" in query:
        return {"answer": "Hospital timings vary by department. Please mention the department name."}

    if "cardiology" in query:
        return {"answer": "Cardiology operates from 09:00 AM to 12:00 PM daily."}

    # Default fallback
    return {"answer": "I’m here to help! Please be specific about your question."}


# --------------- DYNAMIC PDF GENERATION ----------------
@router.get("/reports/{patient_id}")
async def generate_pdf(patient_id: str):

    # Ensure patient ID starts with P
    if patient_id.isdigit():
        patient_id = "P" + patient_id

    doc_ref = db.collection("patients").document(patient_id)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Patient not found")

    pdata = doc.to_dict()

    # Start PDF buffer
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, "NovaMed Multispeciality - Patient Report")

    y = height - 100
    p.setFont("Helvetica", 12)

    for label, value in pdata.items():
        p.drawString(50, y, f"{label}: {value}")
        y -= 20

    p.showPage()
    p.save()

    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{patient_id}_report.pdf"'
        }
    )
