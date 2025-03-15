# app/pdf/parser.py
import re

def extract_health_parameters_from_pdf(file_obj):
    """
    Simulated PDF parsing to extract health parameters.
    In production, integrate OCR (e.g. AWS Textract or Tesseract) and NLP to extract key/value pairs.
    Returns a dictionary of normalized health parameters.
    """
    # Dummy extraction: in real code, parse the PDF text.
    extracted = {
        "cholesterol_total": {"value": "289", "unit": "mg/dL", "reference": "<200"},
        "triglycerides": {"value": "265", "unit": "mg/dL", "reference": "<150"},
        "cholesterol_hdl": {"value": "29", "unit": "mg/dL", "reference": ">=60"},
        "cholesterol_ldl": {"value": "207", "unit": "mg/dL", "reference": "<100"}
    }
    # Here you would add normalization logic (e.g., converting units, standardizing parameter names)
    return extracted

def is_valid_health_parameter(param_key, param_details):
    """
    Check if a health parameter is valid.
    For demonstration, assume numeric values indicate a valid parameter.
    """
    try:
        float(param_details["value"])
        return True
    except ValueError:
        return False
