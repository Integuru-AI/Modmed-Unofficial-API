from curl_cffi import requests as cffi_requests
from urllib.parse import quote


def run(headers, user_input):
    """Fetch full details of an insurance policy including eligibility, authorizations, and card images."""
    base_url = BASE_URL

    # Validate input
    patient_id = user_input.get("patient_id")
    policy_id = user_input.get("policy_id")

    if not patient_id:
        return {"status_code": 400, "body": {"error": "patient_id is required"}}
    if not policy_id:
        return {"status_code": 400, "body": {"error": "policy_id is required"}}

    # Step 1: Fetch full policy detail
    policy_resp = _fetch_policy_detail(base_url, headers, patient_id, policy_id)

    if policy_resp.status_code == 401 or "/login" in policy_resp.url:
        return {"status_code": 401, "body": {"error": "Session expired"}}

    if policy_resp.status_code == 404 or policy_resp.status_code == 500:
        return {
            "status_code": 404,
            "body": {"error": "Policy not found. Verify the patient_id and policy_id are correct."},
        }

    if policy_resp.status_code != 200:
        return {
            "status_code": policy_resp.status_code,
            "body": {"error": f"Policy detail request failed with status {policy_resp.status_code}"},
        }

    policy = policy_resp.json()

    # Step 2: Fetch eligibility last reviewed
    eligibility_resp = _fetch_eligibility_last_reviewed(base_url, headers, policy_id)

    eligibility_last_reviewed = None
    if eligibility_resp.status_code == 200:
        try:
            elig_data = eligibility_resp.json()
            eligibility_last_reviewed = elig_data.get("dateReviewed")
        except Exception:
            pass

    # Step 3: Fetch authorizations
    auth_resp = _fetch_authorizations(base_url, headers, policy_id)

    authorizations = []
    if auth_resp.status_code == 200:
        try:
            auth_data = auth_resp.json()
            for auth in auth_data:
                authorizations.append({
                    "id": auth.get("id"),
                    "auth_number": auth.get("authorizationNumber"),
                    "active": auth.get("active"),
                    "start_date": auth.get("startDate"),
                    "end_date": auth.get("endDate"),
                    "num_visits": auth.get("numVisits"),
                    "num_remaining": auth.get("numRemaining"),
                    "is_unlimited": auth.get("isUnlimited"),
                    "notes": auth.get("notes"),
                    "description": auth.get("description"),
                    "assigned_provider": None,
                })
                # Add provider if present
                provider = auth.get("assignedProvider")
                if provider:
                    authorizations[-1]["assigned_provider"] = {
                        "first_name": provider.get("firstName"),
                        "last_name": provider.get("lastName"),
                    }
        except Exception:
            pass

    # Format the response
    # Payer info
    payer_info = None
    payer = policy.get("payer")
    if payer:
        claims_addresses = []
        for addr_entry in payer.get("payerAddresses", []):
            addr = addr_entry.get("address", {})
            phone = addr_entry.get("phoneNumber", {})
            claims_addresses.append({
                "street1": addr.get("street1"),
                "street2": addr.get("street2"),
                "city": addr.get("city"),
                "state": addr.get("state"),
                "zipcode": addr.get("zipcode"),
                "phone": phone.get("formattedPhoneNumber"),
                "billing_type": addr_entry.get("billingType"),
            })

        payer_info = {
            "id": payer.get("id"),
            "name": payer.get("payerName"),
            "payer_id": payer.get("payerId"),
            "status": payer.get("status"),
            "is_contracted": payer.get("isContracted"),
            "is_medical": payer.get("isMedical"),
            "is_vision": payer.get("isVision"),
            "is_workers_comp": payer.get("isWorkersComp"),
            "financial_category": None,
            "claims_addresses": claims_addresses,
            "plans": [p.get("planName") for p in payer.get("plans", [])],
        }
        fin_cat = payer.get("payerFinancialCategory")
        if fin_cat:
            payer_info["financial_category"] = fin_cat.get("name")

    # Policy holder info
    policy_holder = {
        "first_name": policy.get("policyHolderFirstName"),
        "last_name": policy.get("policyHolderLastName"),
        "middle_name": policy.get("policyHolderMiddleName"),
        "suffix": policy.get("policyHolderSuffix"),
        "date_of_birth": policy.get("policyHolderDateOfBirth"),
        "sex": policy.get("policyHolderSex"),
        "relationship_to_patient": policy.get("patientRelationshipToPolicyHolder"),
        "address": None,
    }
    ph_addr = policy.get("policyHolderAddress")
    if ph_addr:
        policy_holder["address"] = {
            "street1": ph_addr.get("street1"),
            "street2": ph_addr.get("street2"),
            "city": ph_addr.get("city"),
            "state": ph_addr.get("state"),
            "zipcode": ph_addr.get("zipcode"),
        }

    # Guarantor info
    guarantor = {
        "first_name": policy.get("guarantorFirstName"),
        "last_name": policy.get("guarantorLastName"),
        "middle_name": policy.get("guarantorMiddleName"),
        "date_of_birth": policy.get("guarantorDateOfBirth"),
        "sex": policy.get("guarantorSex"),
        "relationship_to_patient": policy.get("patientRelationshipToGuarantor"),
        "address": None,
        "home_phone": None,
        "work_phone": None,
    }
    guar_addr = policy.get("guarantorAddress")
    if guar_addr:
        guarantor["address"] = {
            "street1": guar_addr.get("street1"),
            "street2": guar_addr.get("street2"),
            "city": guar_addr.get("city"),
            "state": guar_addr.get("state"),
            "zipcode": guar_addr.get("zipcode"),
        }
    guar_home = policy.get("guarantorHomePhoneNumber")
    if guar_home:
        guarantor["home_phone"] = guar_home.get("formattedPhoneNumber")
    guar_work = policy.get("guarantorWorkPhoneNumber")
    if guar_work:
        guarantor["work_phone"] = guar_work.get("formattedPhoneNumber")

    # Card images
    card_images = []
    for att in policy.get("attachments", []):
        card_images.append({
            "type": att.get("attachmentType"),
            "file_name": att.get("fileName"),
            "file_size": att.get("fileSize"),
            "url": f"{base_url}{att['filePath']}" if att.get("filePath") else None,
            "uploaded_date": att.get("dateCreated"),
        })

    # Insurance policy PM info (eligibility manual status, signature on file)
    pm_info = policy.get("insurancePolicyPmInfo", {}) or {}
    eligibility_manual_status = None
    changed_by = pm_info.get("eligibilityManualChangedStatusBy")
    if changed_by:
        eligibility_manual_status = {
            "changed_by": f"{changed_by.get('firstName', '')} {changed_by.get('lastName', '')}".strip(),
            "changed_date": pm_info.get("eligibilityManualChangedStatusDate"),
            "changed_from_status": pm_info.get("eligibilityManualChangedFromStatus"),
            "changed_to_status": pm_info.get("eligibilityManualChangedToStatus"),
        }

    # Notes
    note_text = None
    note_obj = policy.get("note")
    if note_obj:
        note_text = note_obj.get("noteText")

    # Payer contacts
    payer_contacts = policy.get("payerContacts", [])

    result = {
        "id": policy.get("id"),
        "ranking": policy.get("ranking"),
        "insurance_active": policy.get("insuranceActive"),
        "insurance_company_name": policy.get("insuranceCompanyName"),
        "insurance_code": policy.get("insuranceCode"),
        "policy_number": policy.get("policyNumber"),
        "group_number": policy.get("groupNumber"),
        "policy_type": policy.get("policyType"),
        "mav_policy_type": policy.get("mavPolicyType"),
        "plan_name": policy.get("planName"),
        "payer_id": policy.get("payerId"),
        "note": note_text,
        "referral_needed": policy.get("referralNeeded"),
        "inpatient_precertification_needed": policy.get("inpatientPrecertificationNeeded"),
        "outpatient_preauthorization_needed": policy.get("outpatientPreauthorizationNeeded"),
        "medicare_advantage": policy.get("medicareAdvantage"),
        "signature_on_file": pm_info.get("signatureOnFile"),
        "eligibility_active": policy.get("eligibilityActive"),
        "eligibility_last_updated": policy.get("eligibilityLastUpdatedTime"),
        "eligibility_last_reviewed": eligibility_last_reviewed,
        "eligibility_manual_changed_status": eligibility_manual_status,
        "copay_amount": policy.get("copayAmount"),
        "coinsurance_percent": policy.get("copayPercent"),
        "deductible": policy.get("copayDeductible"),
        "remaining_deductible": policy.get("deductibleRemaining"),
        "out_of_pocket": policy.get("outOfPocketAmount"),
        "remaining_out_of_pocket": policy.get("outOfPocketRemainingAmount"),
        "policy_effective_date": policy.get("insuranceEffectiveDate"),
        "policy_end_date": policy.get("insuranceTermDate"),
        "insurance_address": None,
        "payer": payer_info,
        "patient_name_on_insurance": {
            "first_name": policy.get("patientInsuranceFirstName"),
            "last_name": policy.get("patientInsuranceLastName"),
        },
        "policy_holder": policy_holder,
        "guarantor": guarantor,
        "card_images": card_images,
        "authorizations": authorizations,
        "payer_contacts": payer_contacts,
    }

    # Insurance address
    ins_addr = policy.get("insuranceAddress")
    if ins_addr:
        result["insurance_address"] = {
            "street1": ins_addr.get("street1"),
            "street2": ins_addr.get("street2"),
            "city": ins_addr.get("city"),
            "state": ins_addr.get("state"),
            "zipcode": ins_addr.get("zipcode"),
        }

    return {
        "status_code": 200,
        "body": result,
    }


# === PRIVATE ===


def _get_common_headers(base_url, headers):
    """Build common request headers matching browser behavior."""
    return {
        **headers,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"{base_url}/ema/patient/InsuranceOverviewForm.action",
        "X-Requested-With": "XMLHttpRequest",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }


def _fetch_policy_detail(base_url, headers, patient_id, policy_id):
    """Fetch the full policy detail for a patient's insurance policy."""
    common_headers = _get_common_headers(base_url, headers)
    policy_url = (
        f"{base_url}/ema/ws/v2/patient/{patient_id}/insurance/{policy_id}"
        f"?includeMedicareAdvantage=true&mapId=MANAGE_POLICY"
    )

    return cffi_requests.get(
        policy_url,
        headers=common_headers,
        impersonate="chrome131",
        timeout=30,
    )


def _fetch_eligibility_last_reviewed(base_url, headers, policy_id):
    """Fetch the eligibility last reviewed date for a policy."""
    common_headers = _get_common_headers(base_url, headers)
    eligibility_url = f"{base_url}/ema/ws/v2/eligibilityReport/lastReviewed?insurancePolicyId={policy_id}"

    return cffi_requests.get(
        eligibility_url,
        headers=common_headers,
        impersonate="chrome131",
        timeout=30,
    )


def _fetch_authorizations(base_url, headers, policy_id):
    """Fetch authorizations linked to a policy."""
    common_headers = _get_common_headers(base_url, headers)
    auth_selector = (
        "active,authorizationNumber,startDate,endDate,numVisits,notes,"
        "numRemaining,description,isUnlimited,insurancePolicy(id),"
        "assignedProvider(firstName,lastName),appointmentTypes(id)"
    )
    auth_where = quote(f'insurancePolicy=="{policy_id}"')
    auth_url = (
        f"{base_url}/ema/ws/v3/insurances/authorizations"
        f"?paging.pageNumber=1&paging.pageSize=50"
        f"&selector={auth_selector}"
        f"&where={auth_where}"
    )

    return cffi_requests.get(
        auth_url,
        headers=common_headers,
        impersonate="chrome131",
        timeout=30,
    )
