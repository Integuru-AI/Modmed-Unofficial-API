# Modmed Unofficial API

Unofficial Python integrations for Modmed.

## Integrations

- `modmed_get_claim_detail.py` - `get_claim_detail` (2,719 live events).
- `modmed_get_eligibility_original_response.py` - `get_eligibility_original_response` (1,891 live events).
- `modmed_get_patient_active_policies.py` - `get_patient_active_policies` (1,875 live events).
- `modmed_get_policy_details.py` - `get_policy_details` (1,872 live events).

## Usage

Each file exposes a `run(input, context)` entrypoint. The runtime is expected to provide:

- `input`: integration-specific request fields.
- `context["headers"]`: authenticated request headers when required.
- `context["base_url"]`: the platform base URL when overriding the default.

Install dependencies:

```bash
pip install -r requirements.txt
```

## Info

This unofficial API is built by [Integuru.ai](https://integuru.ai/).

For custom requests or hosted authentication, contact richard@taiki.online.

See the [complete list of APIs by Integuru](https://github.com/Integuru-AI/APIs-by-Integuru).
