#!/usr/bin/env bash
# Grant Cognitive Services data-plane roles, then wait until GET /models works.
# Never prints tokens, response bodies, or secret-bearing URLs.
set -euo pipefail

if [[ -z "${AZURE_OPENAI_ENDPOINT:-}" ]]; then
  echo "AZURE_OPENAI_ENDPOINT is required" >&2
  exit 1
fi
if [[ -z "${AZURE_CLIENT_ID:-}" ]]; then
  echo "AZURE_CLIENT_ID is required" >&2
  exit 1
fi

eval "$(
  python3 - <<'PY'
import os
import shlex
from urllib.parse import urlsplit

endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
parts = urlsplit(endpoint)
host = (parts.hostname or "").lower()
path = parts.path.rstrip("/").lower()
suffixes = (
    ".openai.azure.com",
    ".cognitiveservices.azure.com",
    ".services.ai.azure.com",
)
name = next((host.split(".", 1)[0] for suffix in suffixes if host.endswith(suffix)), "")
if not name:
    raise SystemExit("endpoint host is not a Cognitive Services or Azure OpenAI account")
normalized = endpoint.rstrip("/")
models_url = (
    f"{normalized}/models"
    if path.endswith("/openai/v1")
    else f"{normalized}/openai/models?api-version=2024-10-21"
)
if host.endswith((".openai.azure.com", ".cognitiveservices.azure.com")):
    resource = "https://cognitiveservices.azure.com"
elif path.endswith("/openai/v1"):
    resource = "https://ai.azure.com"
else:
    resource = "https://cognitiveservices.azure.com"
print(f"ACCOUNT_NAME={shlex.quote(name)}")
print(f"MODELS_URL={shlex.quote(models_url)}")
print(f"TOKEN_RESOURCE={shlex.quote(resource)}")
PY
)"

ACCOUNT_ID="$(az cognitiveservices account list \
  --query "[?name=='${ACCOUNT_NAME}'].id | [0]" \
  --output tsv \
  --only-show-errors)"
if [[ -z "${ACCOUNT_ID}" || "${ACCOUNT_ID}" == "None" ]]; then
  echo "No Cognitive Services account named ${ACCOUNT_NAME} in this subscription" >&2
  exit 1
fi

echo "Resolved Cognitive Services account ${ACCOUNT_NAME}"

ROLES=(
  "Cognitive Services OpenAI User"
  "Cognitive Services User"
)

principal_ids=()
github_principal="$(az identity list \
  --query "[?clientId=='${AZURE_CLIENT_ID}'].principalId | [0]" \
  --output tsv \
  --only-show-errors || true)"
if [[ -z "${github_principal}" || "${github_principal}" == "None" ]]; then
  github_principal="$(az ad sp show \
    --id "${AZURE_CLIENT_ID}" \
    --query id \
    --output tsv \
    --only-show-errors || true)"
fi
if [[ -z "${github_principal}" || "${github_principal}" == "None" ]]; then
  echo "Could not resolve the GitHub OIDC identity principal" >&2
  exit 1
fi
principal_ids+=("${github_principal}")

if [[ -n "${AZURE_RESOURCE_GROUP:-}" && -n "${AZURE_FUNCTIONAPP_NAME:-}" ]]; then
  while IFS= read -r principal; do
    if [[ -n "${principal}" && "${principal}" != "None" ]]; then
      principal_ids+=("${principal}")
    fi
  done < <(az functionapp identity show \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "${AZURE_FUNCTIONAPP_NAME}" \
    --query "userAssignedIdentities.*.principalId" \
    --output tsv \
    --only-show-errors || true)
fi

mapfile -t principal_ids < <(printf '%s\n' "${principal_ids[@]}" | awk 'NF && !seen[$0]++')

for principal in "${principal_ids[@]}"; do
  for role in "${ROLES[@]}"; do
    existing="$(az role assignment list \
      --assignee-object-id "${principal}" \
      --role "${role}" \
      --scope "${ACCOUNT_ID}" \
      --query "[0].id" \
      --output tsv \
      --only-show-errors || true)"
    if [[ -n "${existing}" && "${existing}" != "None" ]]; then
      echo "Role already present: ${role}"
      continue
    fi
    az role assignment create \
      --assignee-object-id "${principal}" \
      --assignee-principal-type ServicePrincipal \
      --role "${role}" \
      --scope "${ACCOUNT_ID}" \
      --output none \
      --only-show-errors
    echo "Granted ${role}"
  done
done

probe_status() {
  local output
  if output="$(az rest \
    --method get \
    --url "${MODELS_URL}" \
    --resource "${TOKEN_RESOURCE}" \
    --output none \
    --only-show-errors 2>&1)"; then
    return 0
  fi
  if [[ "${output}" == *401* ]]; then
    echo "models probe status=401"
  elif [[ "${output}" == *403* ]]; then
    echo "models probe status=403"
  else
    echo "models probe failed"
  fi
  return 1
}

attempts=18
for attempt in $(seq 1 "${attempts}"); do
  if probe_status; then
    echo "Model data-plane access confirmed"
    exit 0
  fi
  echo "Waiting for role assignment to propagate (${attempt}/${attempts})"
  sleep 10
done

echo "Identity cannot call the model endpoint after granting data-plane roles" >&2
exit 1
