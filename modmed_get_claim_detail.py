from curl_cffi import requests
import re
import json


def run(headers, user_input):
    """Fetch comprehensive detail for a specific claim by claim ID."""
    base_url = BASE_URL

    claim_id = user_input.get("claim_id")
    if not claim_id:
        return {"status_code": 400, "body": {"error": "claim_id is required"}}

    # Step 1: Extract bill identifier from claim ID (e.g., "CB001ZLZ7C017" -> "CB001ZLZ7")
    match = re.match(r"^(.+?)(C\d+)$", claim_id)
    if not match:
        return {"status_code": 400, "body": {"error": f"Invalid claim_id format: {claim_id}"}}
    bill_identifier = match.group(1)

    # Step 2: Resolve bill identifier to numeric bill ID
    resolve_resp = requests.get(
        f"{base_url}/ema/ws/v3/bill",
        params={
            "paging.pageNumber": "1",
            "paging.pageSize": "1",
            "selector": "billIdentifier",
            "where": f'billIdentifier=="{bill_identifier}"',
        },
        headers={**headers, "Accept": "application/json"},
        impersonate="chrome131",
        timeout=30,
    )
    if resolve_resp.status_code != 200:
        return {"status_code": 401, "body": {"error": "Session expired"}}
    resolve_data = resolve_resp.json()
    if not resolve_data:
        return {"status_code": 404, "body": {"error": f"Claim not found: {claim_id}"}}
    bill_id = resolve_data[0]["id"]

    # Step 3: Fetch full bill detail
    detail_resp = requests.get(
        f"{base_url}/ema/ws/v3/bill/{bill_id}",
        params={"selector": "$manageBill"},
        headers={**headers, "Accept": "application/json"},
        impersonate="chrome131",
        timeout=30,
    )
    if detail_resp.status_code != 200:
        return {"status_code": 401, "body": {"error": "Session expired"}}
    bill = detail_resp.json()
    if "ProviderLogin" in detail_resp.url:
        return {"status_code": 401, "body": {"error": "Session expired"}}

    # Step 4: Fetch responsible party
    rp_resp = requests.get(
        f"{base_url}/ema/ws/v3/bill/{bill_id}/responsibleParty",
        params={"selector": "$billResponsibleParty"},
        headers={**headers, "Accept": "application/json"},
        impersonate="chrome131",
        timeout=30,
    )
    responsible_party = rp_resp.json() if rp_resp.status_code == 200 else {}

    # Step 5: Fetch bill notes
    notes_resp = requests.get(
        f"{base_url}/ema/ws/v3/pm-note/bill/{bill_id}",
        params={"selector": "fileAttachment(inlineFilePath),author(domainSubjectType)"},
        headers={**headers, "Accept": "application/json"},
        impersonate="chrome131",
        timeout=30,
    )
    notes_data = notes_resp.json() if notes_resp.status_code == 200 else []

    # Step 6: Fetch available authorizations for each policy
    patient_id = (bill.get("patient") or {}).get("id")
    available_auths_by_policy = {}
    if patient_id:
        for pol in bill.get("policies") or []:
            ins = pol.get("insurancePolicy") or {}
            ins_id = ins.get("id")
            if ins_id:
                auth_resp = requests.get(
                    f"{base_url}/ema/ws/v2/patient/{patient_id}/insurance/{ins_id}/authorization/all",
                    headers={**headers, "Accept": "application/json"},
                    impersonate="chrome131",
                    timeout=30,
                )
                if auth_resp.status_code == 200:
                    available_auths_by_policy[ins_id] = auth_resp.json()

    # Transform into clean output
    patient = bill.get("patient") or {}
    rendering = bill.get("renderingProvider") or {}
    primary = bill.get("primaryProvider") or {}
    referring = bill.get("referringProvider") or {}
    svc_loc = bill.get("serviceLocation") or {}
    svc_addr = svc_loc.get("address") or {}
    billing_loc = bill.get("billingLocation") or {}
    billing_addr = billing_loc.get("address") or {}
    appointment = bill.get("appointment") or {}
    visit = bill.get("visit") or {}
    assignee_data = bill.get("assignee") or {}
    assignee_staff = assignee_data.get("staff") or {}
    bu = bill.get("businessUnit") or {}
    bu_addr = bu.get("address") or {}

    # Parse dates
    def parse_date(raw):
        return raw[:10] if raw else None

    # Build patient info
    patient_out = {
        "full_name": patient.get("fullName"),
        "first_name": patient.get("firstName"),
        "last_name": patient.get("lastName"),
        "date_of_birth": parse_date(patient.get("dateOfBirth")),
        "gender": patient.get("gender"),
        "mrn": patient.get("mrn"),
        "phone": (patient.get("preferredPhone") or {}).get("formattedPhoneNumber"),
    }

    # Helper to build authorization output
    def _build_auth(auth):
        if not auth:
            return None
        return {
            "authorization_number": auth.get("authorizationNumber"),
            "description": auth.get("description"),
            "active": auth.get("active"),
            "start_date": parse_date(auth.get("startDate")),
            "end_date": parse_date(auth.get("endDate")),
            "num_visits": auth.get("numVisits"),
            "num_remaining": auth.get("numRemaining"),
            "is_unlimited": auth.get("isUnlimited"),
            "notes": auth.get("notes"),
            "auth_type": auth.get("authType"),
        }

    # Build insurance policies
    policies = []
    for pol in bill.get("policies") or []:
        ins = pol.get("insurancePolicy") or {}
        payer = ins.get("payer") or {}
        policies.append({
            "position": pol.get("position"),
            "insurance_company": ins.get("insuranceCompanyName") or payer.get("payerName"),
            "payer_id": ins.get("payerId"),
            "policy_number": ins.get("policyNumber"),
            "policy_type": ins.get("mavPolicyType"),
            "policy_holder": f"{ins.get('policyHolderFirstName', '')} {ins.get('policyHolderLastName', '')}".strip(),
            "relationship": ins.get("patientRelationshipToPolicyHolder"),
            "active": ins.get("insuranceActive"),
            "current_authorization": _build_auth(pol.get("authorization")),
            "available_authorizations": [
                _build_auth(a) for a in available_auths_by_policy.get(ins.get("id"), [])
            ],
        })

    # Collect all diagnosis IDs referenced by procedure line pointers
    referenced_dx_ids = set()
    for item in bill.get("items") or []:
        for dp in item.get("diagnosisPointers") or []:
            bd = dp.get("billDiagnosis") or {}
            if bd.get("id"):
                referenced_dx_ids.add(bd["id"])

    # Build diagnoses
    diagnoses = []
    for dx in bill.get("diagnoses") or []:
        diagnoses.append({
            "code": dx.get("code"),
            "description": dx.get("description"),
            "position": dx.get("position"),
            "referenced_by_procedures": dx.get("id") in referenced_dx_ids,
        })
    diagnoses.sort(key=lambda d: d.get("position") or 0)

    # Build services/procedures (line items)
    services = []
    for item in bill.get("items") or []:
        mav = item.get("mavCharge") or {}
        modifiers = [m.get("modifier") for m in (item.get("modifiers") or []) if m.get("modifier")]

        # Build charge responsibilities
        responsibilities = []
        for cr in mav.get("allActiveChargeResponsibilities") or []:
            rb = cr.get("responsibleBalance") or {}
            ins_pol = rb.get("insurancePolicy") or {}
            responsibilities.append({
                "type": rb.get("balanceType"),
                "balance": cr.get("balance"),
                "paid": cr.get("paidAmount"),
                "adjusted": cr.get("adjAmount"),
                "assigned": cr.get("assignedAmount"),
                "payer": ins_pol.get("insuranceCompanyName") if rb.get("balanceType") == "INSURANCE" else None,
            })

        # Build diagnosis pointers
        diagnosis_pointers = []
        for dp in sorted(item.get("diagnosisPointers") or [], key=lambda d: d.get("position") or 0):
            bd = dp.get("billDiagnosis") or {}
            diagnosis_pointers.append({
                "position": dp.get("position"),
                "code": bd.get("code"),
            })

        services.append({
            "code": item.get("code"),
            "description": item.get("codeDescription"),
            "charge": item.get("charge"),
            "units": item.get("units"),
            "balance": item.get("balance"),
            "modifiers": modifiers,
            "diagnosis_pointers": diagnosis_pointers,
            "service_date": parse_date(item.get("serviceDateFrom")),
            "status": item.get("status"),
            "item_type": item.get("itemType"),
            "position": item.get("position"),
            "responsibilities": responsibilities,
        })
    services.sort(key=lambda s: s.get("position") or 0)

    # Build responsible party
    rp_ins = responsible_party.get("insurancePolicy") or {}
    current_responsible = {
        "type": responsible_party.get("balanceType"),
        "balance": responsible_party.get("balance"),
        "payer": rp_ins.get("insuranceCompanyName"),
        "policy_number": rp_ins.get("policyNumber"),
        "policy_type": rp_ins.get("mavPolicyType"),
    }

    # Build notes
    notes = []
    for n in notes_data:
        author = n.get("author") or {}
        notes.append({
            "text": n.get("noteText"),
            "date": parse_date(n.get("noteCreatedDate")),
            "author": author.get("name"),
            "type": n.get("type"),
        })

    # Build appointment info
    appt = None
    if appointment:
        appt = {
            "reason": appointment.get("reason"),
            "notes": appointment.get("notes"),
            "status": appointment.get("statusValue"),
            "scheduled_date": parse_date(appointment.get("scheduledStartDateLd")),
            "display_time": appointment.get("displayStartTime"),
            "duration_minutes": appointment.get("scheduledDuration"),
            "type": (appointment.get("appointmentType") or {}).get("name"),
            "provider": (appointment.get("provider") or {}).get("name"),
            "responsible_party": appointment.get("responsibleParty"),
            "origin": appointment.get("origin"),
        }

    result = {
        "claim_id": claim_id,
        "bill_id": bill_id,
        "bill_identifier": bill.get("billIdentifier"),
        "status": bill.get("status"),
        "type": bill.get("type"),
        "billing_type": bill.get("billingType"),
        "reportable_reason": bill.get("reportableReason"),
        "bill_creation_date": parse_date(bill.get("billCreationDate")),
        "service_date": parse_date(bill.get("serviceDateLd")),
        "bill_overridden": bill.get("billOverridden"),

        "patient": patient_out,

        "rendering_provider": {
            "name": rendering.get("name"),
            "npi": rendering.get("npi"),
        },
        "primary_provider": {
            "name": primary.get("name"),
        },
        "referring_provider": {
            "name": referring.get("name"),
            "npi": referring.get("npi"),
        } if referring else None,

        "service_location": {
            "name": svc_loc.get("name"),
            "address": f"{svc_addr.get('street1', '')} {svc_addr.get('street2', '')}".strip(),
            "city": svc_addr.get("city"),
            "state": svc_addr.get("state"),
            "zip": svc_addr.get("zipcode"),
        },
        "billing_location": {
            "name": billing_loc.get("name"),
            "address": f"{billing_addr.get('street1', '')} {billing_addr.get('street2', '')}".strip(),
            "city": billing_addr.get("city"),
            "state": billing_addr.get("state"),
            "zip": billing_addr.get("zipcode"),
        },

        "business_unit": {
            "name": bu.get("title"),
            "id": bu.get("id"),
            "ein": bu.get("identificationNumber"),
            "npi": bu.get("organizationalIdentificationNumber"),
        },

        "assignee": {
            "name": assignee_staff.get("name"),
            "type": assignee_data.get("type"),
        } if assignee_staff else None,

        "current_responsible": current_responsible,
        "policies": policies,
        "diagnoses": diagnoses,
        "services": services,

        "financials": {
            "total_charges": bill.get("totalCharges"),
            "total_payments": bill.get("totalPayments"),
            "total_allowable": bill.get("totalAllowable"),
            "total_adjustments": bill.get("appliedAdjustmentsTotal"),
            "total_posted_charges": bill.get("totalPostedCharges"),
            "balance": bill.get("balance"),
            "is_posted": bill.get("isPosted"),
        },

        "appointment": appt,

        "visit": {
            "type": visit.get("visitType"),
            "date": parse_date(visit.get("visitDate")),
            "medical_domain": visit.get("medicalDomain"),
        } if visit else None,

        "notes": notes,
    }

    return {"status_code": 200, "body": result}
