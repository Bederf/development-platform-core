#!/usr/bin/env bash
# Install project-local wrappers for shared development quality capabilities.
set -euo pipefail

PROJECT=""
PROJECT_ID=""
OCR_TRANSPORT="direct"
INFISICAL_PROJECT_ID=""
INFISICAL_ENV="prod"
INFISICAL_PATH="/omniroute"
CORE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
CAPABILITIES=()
PROFILES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --ocr-transport) OCR_TRANSPORT="$2"; shift 2 ;;
    --infisical-project-id) INFISICAL_PROJECT_ID="$2"; shift 2 ;;
    --infisical-env) INFISICAL_ENV="$2"; shift 2 ;;
    --infisical-path) INFISICAL_PATH="$2"; shift 2 ;;
    --capability) CAPABILITIES+=("$2"); shift 2 ;;
    --profile) PROFILES+=("$2"); shift 2 ;;
    --help|-h) echo "Usage: init-development-quality.sh --project PROJECT_ROOT [--capability ID] [--profile CAPABILITY=PROFILE@VERSION]"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$PROJECT" ]] || { echo "--project is required" >&2; exit 2; }
PROJECT="$(cd -- "$PROJECT" && pwd -P)"
[[ -e "$PROJECT/.git" ]] || { echo "project is not a git repository: $PROJECT" >&2; exit 1; }
if [[ -z "$PROJECT_ID" && -f "$PROJECT/development-platform.yaml" ]]; then
  PROJECT_ID="$(awk '$1 == "id:" { print $2; exit }' "$PROJECT/development-platform.yaml")"
fi
[[ -n "$PROJECT_ID" ]] || { echo "project_id is required; use --project-id or provide development-platform.yaml" >&2; exit 1; }
[[ "$OCR_TRANSPORT" == "direct" ]] || {
  echo "only the AGY direct review route is supported; OmniRoute is removed" >&2
  exit 2
}

python3 "$CORE_ROOT/scripts/install-quality-hooks.py" --project "$PROJECT" --check

if [[ -f "$PROJECT/development-platform.yaml" ]] && ! grep -q '^capabilities_manifest:' "$PROJECT/development-platform.yaml"; then
  sed -i '/^schema: development-platform.v1$/a capabilities_manifest: .development-platform/capabilities.yaml' "$PROJECT/development-platform.yaml"
fi

mkdir -p "$PROJECT/.githooks" "$PROJECT/.development-platform" "$PROJECT/docs"

# Install platform-owned skills where agent clients discover project skills.
# Existing consumer files are authoritative and are never overwritten.
SKILL_ROOT="$PROJECT/.agents/skills"
mkdir -p "$SKILL_ROOT"
for skill_dir in "$CORE_ROOT"/skills/*; do
  [[ -d "$skill_dir" ]] || continue
  skill_name="$(basename "$skill_dir")"
  [[ "$skill_name" == "README.md" ]] && continue
  target="$SKILL_ROOT/$skill_name"
  mkdir -p "$target"
  while IFS= read -r -d '' source_file; do
    relative="${source_file#"$skill_dir/"}"
    destination="$target/$relative"
    if [[ ! -e "$destination" ]]; then
      mkdir -p "$(dirname "$destination")"
      cp "$source_file" "$destination"
    fi
  done < <(find "$skill_dir" -type f -print0)
done
cat > "$PROJECT/.development-platform/skills.yaml" <<EOF
schema: development-platform-skills.v1
source: $CORE_ROOT/skills
destination: $SKILL_ROOT
policy: existing-files-preserved
EOF

has_capability() {
  local requested
  for requested in "${CAPABILITIES[@]}"; do
    [[ "$requested" == "$1" ]] && return 0
  done
  return 1
}

profile_yaml() {
  local capability="$1" entry selected_capability selected_profile selected_version
  for entry in "${PROFILES[@]}"; do
    [[ "$entry" == *=*@* ]] || { echo "invalid profile selection: $entry" >&2; exit 2; }
    selected_capability="${entry%%=*}"
    selected_profile="${entry#*=}"
    selected_version="${selected_profile##*@}"
    selected_profile="${selected_profile%@*}"
    [[ -n "$selected_capability" && -n "$selected_profile" && "$selected_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
      echo "invalid profile selection: $entry" >&2
      exit 2
    }
    if [[ "$selected_capability" == "$capability" ]]; then
      cat <<EOF
    profiles:
      - id: $selected_profile
        version: $selected_version
EOF
    fi
  done
}

HOOK_ARGS=(--project "$PROJECT" --ocr-transport "$OCR_TRANSPORT"
  --infisical-project-id "$INFISICAL_PROJECT_ID" --infisical-env "$INFISICAL_ENV"
  --infisical-path "$INFISICAL_PATH")
for capability in "${CAPABILITIES[@]}"; do HOOK_ARGS+=(--capability "$capability"); done
for profile in "${PROFILES[@]}"; do HOOK_ARGS+=(--profile "$profile"); done
python3 "$CORE_ROOT/scripts/install-quality-hooks.py" "${HOOK_ARGS[@]}"

if has_capability property-testing; then
  mkdir -p "$PROJECT/tests/property"
fi
if has_capability property-testing && [[ ! -e "$PROJECT/tests/property/README.md" ]]; then
cat > "$PROJECT/tests/property/README.md" <<'EOF'
# Property-testing boundary

This directory is a project-local scaffold. Add properties only for rules
that can be stated independently of example fixtures, such as invariants,
idempotency, authorization boundaries, conservation laws, or round trips.

The project chooses the test framework and runner. Initialization does not add
dependencies or invent domain properties. Each property must identify its
domain rule and its verification command.
EOF
fi

if [[ ! -e "$PROJECT/.development-platform/capabilities.yaml" ]]; then
cat > "$PROJECT/.development-platform/capabilities.yaml" <<EOF
schema: development-capability-selection.v1
project_id: $PROJECT_ID
capabilities:
  ocr:
    enabled: $(has_capability ocr && echo true || echo false)
    implementation: core.ocr-gate
    version: 1.0.0
$(profile_yaml ocr)
  backpass:
    enabled: $(has_capability backpass && echo true || echo false)
    implementation: core.backpass
    version: 1.0.0
    configuration:
      capture: disabled
      transmission: disabled
$(profile_yaml backpass)
  property-testing:
    enabled: $(has_capability property-testing && echo true || echo false)
    implementation: project-defined
    version: 1.0.0
$(profile_yaml property-testing)
  gsd:
    enabled: $(has_capability gsd && echo true || echo false)
    implementation: gsd.master
    version: 3.3.0
$(profile_yaml gsd)
  security-audit:
    enabled: true
    implementation: core.security-audit-build
    version: 1.0.2
    configuration:
      execution: explicit-build-release
      pre_commit: disabled
      production: disabled
EOF
fi

echo "Development quality layer initialized under $PROJECT"
echo "OCR deterministic gate: enabled"
echo "Backpass capture/transmission: disabled"
echo "Property-testing scaffold: tests/property/"
echo "Platform skills: $SKILL_ROOT"
