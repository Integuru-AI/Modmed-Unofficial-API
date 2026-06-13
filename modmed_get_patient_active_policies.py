from curl_cffi import requests as cffi_requests
from urllib.parse import quote


def run(headers, user_input):
    """Look up a patient and return their active insurance policies. Accepts patient_id directly or first/last name for search."""
    base_url = BASE_URL

    # Validate input - either patient_id OR first_name+last_name required
    patient_id = user_input.get("patient_id", "").strip()
    first_name = user_input.get("first_name", "").strip()
    last_name = user_input.get("last_name", "").strip()

    if not patient_id and (not first_name or not last_name):
        return {"status_code": 400, "body": {"error": "Either patient_id or both first_name and last_name are required"}}

    matched_patient = None

    if patient_id:
        # Direct lookup by ID - skip name search
        matched_patient = {"id": int(patient_id) if patient_id.isdigit() else patient_id}
    else:
        # Step 1: Search for patient by name
        search_resp = _search_patients(base_url, headers, first_name, last_name)

        if search_resp.status_code == 401 or "/login" in search_resp.url:
            return {"status_code": 401, "body": {"error": "Session expired"}}

        if search_resp.status_code != 200:
            return {
                "status_code": search_resp.status_code,
                "body": {"error": f"Patient search failed with status {search_resp.status_code}"},
            }

        patients = search_resp.json()

        if not patients:
            return {"status_code": 404, "body": {"error": "No patients found matching that name"}}

        # Find exact match (case-insensitive)
        for p in patients:
            if (
                p.get("firstName", "").lower() == first_name.lower()
                and p.get("lastName", "").lower() == last_name.lower()
            ):
                matched_patient = p
                break

        if not matched_patient:
            # Return partial matches for user to refine
            partial_matches = [
                {"id": p["id"], "first_name": p.get("firstName"), "last_name": p.get("lastName"), "mrn": p.get("mrn"), "date_of_birth": p.get("displayDateOfBirth")}
                for p in patients[:10]
            ]
            return {
                "status_code": 404,
                "body": {
                    "error": "No exact match found. Partial matches returned.",
                    "partial_matches": partial_matches,
                },
            }

    patient_id = matched_patient["id"]

    # Step 2: Fetch insurance policies for the patient
    insurance_resp = _fetch_insurance(base_url, headers, patient_id)

    if insurance_resp.status_code == 401 or "/login" in insurance_resp.url:
        return {"status_code": 401, "body": {"error": "Session expired"}}

    if insurance_resp.status_code != 200:
        return {
            "status_code": insurance_resp.status_code,
            "body": {"error": f"Insurance lookup failed with status {insurance_resp.status_code}"},
        }

    all_policies = insurance_resp.json()

    # Filter to active policies only
    active_policies = [p for p in all_policies if p.get("insuranceActive") is True]

    # Format the response
    formatted_policies = []
    for policy in active_policies:
        formatted_policy = {
            "id": policy.get("id"),
            "ranking": policy.get("ranking"),
            "insurance_company_name": policy.get("insuranceCompanyName"),
            "insurance_code": policy.get("insuranceCode"),
            "policy_number": policy.get("policyNumber"),
            "group_number": policy.get("groupNumber"),
            "policy_type": policy.get("policyType"),
            "eligibility_active": policy.get("eligibilityActive"),
            "referral_needed": policy.get("referralNeeded"),
            "medicare_advantage": policy.get("medicareAdvantage"),
            "insurance_address": None,
            "policy_holder": {
                "first_name": policy.get("policyHolderFirstName"),
                "last_name": policy.get("policyHolderLastName"),
                "date_of_birth": policy.get("policyHolderDateOfBirth"),
                "relationship_to_patient": policy.get("patientRelationshipToPolicyHolder"),
            },
        }

        # Include insurance address if available
        ins_addr = policy.get("insuranceAddress")
        if ins_addr:
            formatted_policy["insurance_address"] = {
                "street1": ins_addr.get("street1"),
                "street2": ins_addr.get("street2"),
                "city": ins_addr.get("city"),
                "state": ins_addr.get("state"),
                "zipcode": ins_addr.get("zipcode"),
            }

        formatted_policies.append(formatted_policy)

    # Sort by ranking
    formatted_policies.sort(key=lambda x: x.get("ranking") or 999)

    # Build patient info from search result or from policy data
    patient_info = {
        "id": matched_patient["id"],
        "first_name": matched_patient.get("firstName"),
        "last_name": matched_patient.get("lastName"),
        "mrn": matched_patient.get("mrn"),
        "date_of_birth": matched_patient.get("displayDateOfBirth"),
    }

    # If we looked up by ID, try to fill patient name from policy data
    if not patient_info["first_name"] and active_policies:
        patient_obj = active_policies[0].get("patient", {})
        if patient_obj:
            patient_info["first_name"] = patient_obj.get("firstName")
            patient_info["last_name"] = patient_obj.get("lastName")

    return {
        "status_code": 200,
        "body": {
            "patient": patient_info,
            "active_policies": formatted_policies,
        },
    }


# === PRIVATE ===


def _get_common_headers(base_url, headers):
    """Build common request headers matching browser behavior."""
    return {
        **headers,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"{base_url}/ema/practice/financial/Financials.action",
        "X-Requested-With": "XMLHttpRequest",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }


def _search_patients(base_url, headers, first_name, last_name):
    """Search for patients by name using Last,First format."""
    common_headers = _get_common_headers(base_url, headers)
    search_term = quote(f"{last_name},{first_name}")
    search_url = (
        f"{base_url}/ema/ws/v3/patients/search"
        f"?term={search_term}"
        f"&selector=lastName,firstName,fullName,mrn,pmsId,dateOfBirth,encryptedId"
        f"&sorting.sortBy=lastName,firstName"
        f"&sorting.sortOrder=asc"
        f"&paging.pageSize=25"
    )

    return cffi_requests.get(
        search_url,
        headers=common_headers,
        impersonate="chrome131",
        timeout=30,
    )


def _fetch_insurance(base_url, headers, patient_id):
    """Fetch insurance policies for a patient."""
    common_headers = _get_common_headers(base_url, headers)
    insurance_url = f"{base_url}/ema/ws/v2/patient/{patient_id}/insurance"

    return cffi_requests.get(
        insurance_url,
        headers=common_headers,
        impersonate="chrome131",
        timeout=30,
    )
