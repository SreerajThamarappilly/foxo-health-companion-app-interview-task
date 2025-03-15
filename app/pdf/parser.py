# app/pdf/parser.py
import re
import pdfplumber
import openai
from app.config import settings
import json
import re

def normalize_parameter_name(name: str) -> str:
    """
    Normalize a parameter name by converting to lowercase and removing all non-alphanumeric characters.
    This allows for case-insensitive comparisons that ignore spaces, hyphens, and special characters.
    """
    import re
    return re.sub(r'[^a-z0-9]', '', name.lower())

def is_valid_parameter_name(name_str: str) -> bool:
    """
    Returns True if the candidate parameter name looks valid.
    We require that it contains at least two words and that not too many words
    are common adjectives (e.g. "high", "borderline", "normal", etc.).
    """
    words = name_str.split()
    if len(words) < 2:
        return False
    disqualifiers = {"high", "borderline", "normal", "desirable", "above", "below", "ref", "method"}
    # If more than half the words are generic adjectives, reject.
    count_generic = sum(1 for w in words if w.lower() in disqualifiers)
    if count_generic >= len(words) / 2:
        return False
    return True

def extract_health_parameters_from_pdf(file_path):
    """
    Dynamically extracts health parameters from a PDF file.
    Mandatory: parameter name and its test result value.
    Optionally extracts: unit.
    Processes each page by combining all its lines (to overcome broken lines)
    and then applies a regex to find candidate parameter entries.
    Returns a dictionary where keys are normalized parameter names and values are details.
    """
    extracted = {}
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                # Combine all lines into one block so that valid entries are not broken by newlines.
                combined_text = " ".join(text.splitlines())
                # Regex: non-greedy capture for name, optional colon or dash, then a mandatory numeric value and a unit.
                pattern = re.compile(
                    r"(?P<name>[A-Za-z0-9()\.'°\s\-/]+?)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z/%]+)",
                    re.IGNORECASE
                )
                for match in pattern.finditer(combined_text):
                    details = match.groupdict()
                    candidate_name = details.get("name", "").strip().lower()
                    # Apply filtering: if the candidate name is too short or mostly generic, skip it.
                    if not is_valid_parameter_name(candidate_name):
                        continue
                    # Add the candidate only if it has a value and unit.
                    if details.get("value") and details.get("unit"):
                        extracted[candidate_name] = {
                            "value": details.get("value"),
                            "unit": details.get("unit")
                        }
    except Exception as e:
        print(f"Error extracting PDF: {e}")
    return extracted

def validate_health_parameters_with_openai(extracted_params):
    """
    Validates the extracted health parameters using one OpenAI API call.
    The API receives non-sensitive details only (i.e. parameter name and unit)
    and returns a JSON array indicating, for each parameter, whether it is valid.
    Returns two dictionaries:
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
        "Make sure that only the valid health test names (like 'Cholesterol - Total', 'Triglycerides', 'Cholesterol - HDL', 'Cholesterol - LDL', 'Cholesterol- VLDL', 'Cholesterol : HDL Cholesterol', 'LDL : HDL Cholesterol' and 'Non HDL Cholesterol', 'Non HDL Cholesterol' and other similar valid health checkup names, including non-case sensitive letters, combination with abbreviates of tests, etc.) are included in your response. "
        "Return ONLY a valid JSON array of objects, where each object has a single key 'is_valid' with a the valid health test name from the input as the value. You can ignore the invalid health test names from the input. "
        "Do not wrap the JSON output in markdown formatting or add any commentary."
        "In your response, make sure to include only the valid health test names from the given below Parameters. \n\n"
        "Parameters:\n" + json.dumps(params_for_validation, indent=2)
    )
    print("Raw OpenAI request:", json.dumps(params_for_validation, indent=2))
    
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
    print("Raw OpenAI response:", content)
    if content.startswith("```"):
        content = content.strip("```").strip()
    
    try:
        validation_results = json.loads(content)
    except Exception as e:
        raise Exception(f"Error parsing OpenAI response: {e}\nRaw response: {content}")
    
    valid_params = {}
    pending_params = {}
    # Now use the string returned by OpenAI as the validated parameter name.
    for i, key in enumerate(param_keys):
        result = validation_results[i] if i < len(validation_results) else {}
        validated_name = result.get("is_valid", "").strip()
        if validated_name:
            # Use the validated name as the key in valid_params.
            valid_params[validated_name] = extracted_params[key]
        else:
            pending_params[key] = extracted_params[key]
    return valid_params, pending_params
