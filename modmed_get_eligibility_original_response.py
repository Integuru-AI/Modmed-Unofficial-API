from curl_cffi import requests


def run(headers, user_input):
    """Fetch the full original eligibility response for a patient's insurance policy."""
    base_url = BASE_URL

    # Validate input
    patient_id = user_input.get("patient_id")
    policy_number = user_input.get("policy_number")
    if not patient_id:
        return {"status_code": 400, "body": {"error": "patient_id is required"}}
    if not policy_number:
        return {"status_code": 400, "body": {"error": "policy_number is required"}}

    try:
        return _fetch_eligibility_original_response(base_url, headers, patient_id, policy_number)
    except Exception as e:
        return {"status_code": 500, "body": {"error": str(e)}}


# === PRIVATE ===


def _fetch_eligibility_original_response(base_url, headers, patient_id, policy_number):
    """Fetch the full original eligibility response for a patient's insurance policy."""

    # Build request headers matching what the frontend sends
    req_headers = {
        **headers,
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "referer": f"{base_url}/ema/web/practice/staff/",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }

    # Step 1: Look up all policies for this patient to resolve policy_number to internal ID
    lite_url = f"{base_url}/ema/ws/v2/patient/{patient_id}/insurance/lite"
    lite_resp = requests.get(
        lite_url,
        headers=req_headers,
        impersonate="chrome110",
        timeout=30,
    )

    if lite_resp.status_code == 401 or "/login" in lite_resp.url:
        return {"status_code": 401, "body": {"error": "Session expired"}}

    if lite_resp.status_code != 200:
        return {
            "status_code": lite_resp.status_code,
            "body": {"error": f"Failed to fetch patient policies: {lite_resp.text[:500]}"},
        }

    policies = lite_resp.json()
    policy_id = None
    for p in policies:
        if p.get("policyNumber") == policy_number:
            policy_id = p.get("id")
            break

    if not policy_id:
        return {
            "status_code": 404,
            "body": {"error": f"Policy number '{policy_number}' not found for patient {patient_id}"},
        }

    # Step 2: Get the insurance policy detail to find the latest eligibility history ID
    policy_url = f"{base_url}/ema/ws/v2/patient/{patient_id}/insurance/{policy_id}"
    policy_params = {
        "includeMedicareAdvantage": "true",
        "mapId": "MANAGE_POLICY",
    }

    policy_resp = requests.get(
        policy_url,
        params=policy_params,
        headers=req_headers,
        impersonate="chrome110",
        timeout=30,
    )

    if policy_resp.status_code == 401 or "/login" in policy_resp.url:
        return {"status_code": 401, "body": {"error": "Session expired"}}

    if policy_resp.status_code != 200:
        return {
            "status_code": policy_resp.status_code,
            "body": {"error": f"Failed to fetch policy detail: {policy_resp.text[:500]}"},
        }

    policy_data = policy_resp.json()
    latest_history = policy_data.get("latestEligibilityHistory", {})
    history_id = latest_history.get("id")

    if not history_id:
        return {
            "status_code": 404,
            "body": {"error": "No eligibility history found for this policy"},
        }

    # Step 3: Fetch the full original response using the eligibility history ID
    selector = (
        "dateCreated,user,activeCoverage,responseReceivedTime,fromBatch,"
        "requestPayerId,vendor,eligibilityResponse,requestPolicyNumber,payer,"
        "insurancePolicy(payer,latestEligibilityHistory,patientRelationshipToPolicyHolder),"
        "additionalInfo(npi,provider(fullName),serviceDateLd,businessUnit),"
        "eligibilityInfo(npi,serviceDate,providerName,eligibilityDates,planDates,planName),"
        "patient(dateOfBirth,firstName,lastName,middleName,fullName),"
        "dependent,hasStaleData,"
        "eligibilityDetailedResponse(benefitTypesInfo(benefitType,"
        "benefitCategoryInfo(benefitCategory,benefitInformation(serviceType,amount,percentage,"
        "authorizationOrCertificationRequired,messages)))),"
        "discrepancies(requestValue,responseValue,acknowledgeDatetime,acknowledgeUser,"
        "updateDatetime,updateUser),"
        "alerts(message,type)"
    )

    history_url = f"{base_url}/ema/ws/v3/eligibility/eligibility-history/{history_id}"
    history_params = {"selector": selector}

    history_resp = requests.get(
        history_url,
        params=history_params,
        headers=req_headers,
        impersonate="chrome110",
        timeout=30,
    )

    if history_resp.status_code == 401 or "/login" in history_resp.url:
        return {"status_code": 401, "body": {"error": "Session expired"}}

    if history_resp.status_code != 200:
        return {
            "status_code": history_resp.status_code,
            "body": {"error": f"Failed to fetch eligibility history: {history_resp.text[:500]}"},
        }

    return {"status_code": 200, "body": history_resp.json()}
