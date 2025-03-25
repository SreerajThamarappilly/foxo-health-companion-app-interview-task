# app/pdf/parser.py
import os
import re
import uuid
import pdfplumber
import openai
import json
from abc import ABC, abstractmethod
from app.config import settings

# ============================
# Strategy Interface
# ============================
class PDFExtractionStrategy(ABC):
    """
    Abstract base class that defines the interface for all PDF extraction strategies.
    Any new strategy must implement the extract(file_path: str) -> dict method.
    """
    @abstractmethod
    def extract(self, file_path: str) -> dict:
        pass


# ============================
# Utility Functions
# ============================
def normalize_parameter_name(name: str) -> str:
    """
    Normalize a parameter name by converting to lowercase and removing all non-alphanumeric characters.
    This standardization is useful for consistent comparisons and dictionary key lookups.
    """
    return re.sub(r'[^a-z0-9]', '', name.lower())

def is_valid_parameter_name(name_str: str) -> bool:
    """
    Validates whether a candidate parameter name is appropriate.
    It must contain at least two words and not be made up of too many generic adjectives (e.g., 'high', 'normal').
    """
    words = name_str.split()
    if len(words) < 2:
        return False
    disqualifiers = {"high", "borderline", "normal", "desirable", "above", "below", "ref", "method"}
    count_generic = sum(1 for w in words if w.lower() in disqualifiers)
    return count_generic < len(words) / 2

def save_text_to_temp_file(combined_text: str, file_path: str = None) -> None:
    """
    Saves the provided combined text into a temporary text file in the 'sample' folder
    located at the root of the FastAPI application.
    
    Args:
      combined_text (str): The text to save.
      file_path (str, optional): The original PDF file path, used to generate a filename prefix.
        If not provided, a default prefix 'tmp' is used.
    
    This function always appends a unique UUID to the filename so that each call produces a unique file.
    """
    # Compute the absolute path to the 'sample' folder at the project root.
    sample_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "sample"))
    os.makedirs(sample_dir, exist_ok=True)
    
    # Use the basename from file_path if provided; otherwise, use a default prefix.
    if file_path:
        base_name = os.path.splitext(os.path.basename(file_path))[0]
    else:
        base_name = "tmp"
    
    # Append a unique UUID suffix so each call generates a unique filename.
    unique_suffix = uuid.uuid4().hex
    temp_txt_path = os.path.join(sample_dir, f"{base_name}_{unique_suffix}.txt")
    
    try:
        with open(temp_txt_path, "w", encoding="utf-8") as f:
            f.write(combined_text)
        print(f"Combined text saved to: {temp_txt_path}")
    except Exception as e:
        print(f"Error saving combined text to file: {e}")


# ============================
# Step 1: Text Extraction Function
# ============================
def extract_text_from_pdf(file_path: str) -> str:
    """
    Extracts and concatenates text from all pages of a PDF file.
    
    Process:
      1. Open the PDF using pdfplumber.
      2. Iterate through each page and extract text.
      3. Combine lines from each page into a single continuous block.
      4. Save the combined text to a temporary text file in the 'sample' folder at the root of the project.
    
    Returns:
      The combined text extracted from the PDF.
    """
    combined_text = ""
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                # Join lines with a space to avoid broken matches.
                combined_text += " " + " ".join(text.splitlines())
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
    return combined_text.strip()


# ============================
# Step 2: Filtering Function
# ============================
def filter_health_parameters_from_text(text: str) -> dict:
    """
    Filters and extracts health parameter data from the provided combined text.
    
    Process:
      1. Uses a regex pattern to capture candidate parameter entries (name, value, unit).
      2. Normalizes the candidate parameter name using normalize_parameter_name() for consistency.
      3. Validates the candidate name using is_valid_parameter_name(); if invalid, skips it.
      4. If both value and unit are present, adds the normalized name and its details to the results.
    
    Returns:
      A dictionary where keys are normalized parameter names and values are their details.
    """
    extracted = {}
    # Regex pattern to capture parameter name, value, and unit.
    pattern = re.compile(
        r"(?P<name>[A-Za-z0-9()\.'°\s\-/]+?)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z/%]+)",
        re.IGNORECASE
    )
    for match in pattern.finditer(text):
        details = match.groupdict()
        candidate_name_raw = details.get("name", "").strip().lower()
        # Normalize the candidate name for consistent storage and comparison.
        normalized_name = normalize_parameter_name(candidate_name_raw)
        # Validate the candidate name; skip if not valid.
        if not is_valid_parameter_name(candidate_name_raw):
            continue
        # Only add the parameter if both a value and unit are found.
        if details.get("value") and details.get("unit"):
            extracted[normalized_name] = {
                "value": details.get("value"),
                "unit": details.get("unit")
            }
    
    return extracted


# ============================
# Concrete Strategy: Regex-based extraction
# ============================
class DefaultPDFExtractionStrategy(PDFExtractionStrategy):
    """
    Concrete strategy that extracts health parameters in two distinct steps:
      1. Extract all text from the PDF file using extract_text_from_pdf().
      2. Filter out health parameters from the combined text using filter_health_parameters_from_text().
    
    This separation makes the process more modular and testable.
    """
    def extract(self, file_path: str) -> dict:
        # Step 1: Extract text from the PDF.
        combined_text = extract_text_from_pdf(file_path)
        save_text_to_temp_file(str(combined_text))
        # Step 2: Filter out health parameters from the combined text.
        extracted_params = filter_health_parameters_from_text(combined_text)
        save_text_to_temp_file(str(extracted_params))
        return extracted_params


# ============================
# Context Class for PDF Extraction
# ============================
class PDFExtractor:
    """
    Context class that uses a specified PDFExtractionStrategy to extract health parameters from a PDF file.
    This allows you to swap strategies (e.g., add OCR-based extraction) without changing the client code.
    """
    def __init__(self, strategy: PDFExtractionStrategy):
        self.strategy = strategy

    def extract_parameters(self, file_path: str) -> dict:
        return self.strategy.extract(file_path)


# ============================
# OpenAI Validation (unchanged)
# ============================
def validate_health_parameters_with_openai(extracted_params):
    """
    Validates the extracted health parameters using an OpenAI API call.
    
    The API receives non-sensitive details (parameter name and unit) and returns a JSON array indicating
    for each parameter whether it is valid. The function returns two dictionaries:
      - valid_params: parameters validated as valid (approved), with original details (including value)
      - pending_params: parameters not validated as valid.
    """
    # Build payload omitting sensitive test result values.
    params_for_validation = []
    param_keys = list(extracted_params.keys())
    for key in param_keys:
        details = extracted_params[key]
        data = {"name": key}
        if "unit" in details:
            data["unit"] = details["unit"]
        params_for_validation.append(data)

    openai.api_key = settings.OPENAI_API_KEY
    if not openai.api_key:
        raise Exception("OpenAI API key not set. Please set the OPENAI_API_KEY environment variable.")

    prompt = (
        "Validate the following list of health parameter details. "
        "For each item, determine if the parameter is a recognized health test parameter. "
        "Do NOT include any sensitive details such as test result values. "
        "Make sure that only the valid health test names (like 'Cholesterol - Total', 'Triglycerides', 'Cholesterol', "
        "'Cholesterol - HDL', 'Cholesterol - LDL', 'Cholesterol- VLDL', 'Cholesterol : HDL Cholesterol', 'HD Lipoprotein', 'LDlipoprotein' "
        "'LDL : HDL Cholesterol, 'Non HDL Cholesterol', 'CREATININE', 'ast/sgot', 'ALT / SGPT', 'glycated heamoglobin', 'Heamoglobin', 'Sugar', "
        "'blood sugar - fasting', 'thyroid', etc.) and any other valid health test parameter names (including their shortened form or "
        "abbreviated version or case insensitive form) are included in your response. "
        "Return ONLY a valid JSON array of objects, where each object has a single key 'is_valid' with the valid "
        "health test name as its value. You can ignore the invalid health test names from the input. "
        "Do not wrap the JSON output in markdown formatting or add any commentary. "
        "In your response, include only the valid health test names from the given below Parameters. \n\n"
        "Parameters:\n" + json.dumps(params_for_validation, indent=2)
    )
    save_text_to_temp_file(str(json.dumps(params_for_validation, indent=2)))
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a medical data validator. Validate health test parameters."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
    except Exception as e:
        raise Exception(f"OpenAI API request failed: {e}")
    
    content = response["choices"][0]["message"]["content"]
    save_text_to_temp_file(str(response))
    if content.startswith("```"):
        content = content.strip("```").strip()
    
    try:
        validation_results = json.loads(content)
    except Exception as e:
        raise Exception(f"Error parsing OpenAI response: {e}\nRaw response: {content}")
    
    valid_params = {}
    pending_params = {}
    # Use the response from OpenAI to partition the parameters.
    for i, key in enumerate(param_keys):
        result = validation_results[i] if i < len(validation_results) else {}
        validated_name = result.get("is_valid", "").strip()
        if validated_name:
            valid_params[validated_name] = extracted_params[key]
        else:
            pending_params[key] = extracted_params[key]
    return valid_params, pending_params
