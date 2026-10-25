#!/usr/bin/env bash
# Add the project-local GSD Master layer to an already governed consumer.
set -euo pipefail

PROJECT=""; PROJECT_ID=""; OWNER=""; OBJECTIVE=""; SUCCESS=""; IN_SCOPE=""; OUT_OF_SCOPE=""
write_once() {
  local destination="$1"
  if [[ -e "$destination" ]]; then
    cat >/dev/null
  else
    cat >"$destination"
  fi
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --owner) OWNER="$2"; shift 2 ;;
    --objective) OBJECTIVE="$2"; shift 2 ;;
    --success) SUCCESS="$2"; shift 2 ;;
    --in-scope) IN_SCOPE="$2"; shift 2 ;;
    --out-of-scope) OUT_OF_SCOPE="$2"; shift 2 ;;
    --help|-h) echo "Usage: init-gsd-project.sh --project PATH --project-id ID --owner OWNER --objective TEXT --success TEXT --in-scope TEXT --out-of-scope TEXT"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$PROJECT" && -n "$PROJECT_ID" && -n "$OWNER" && -n "$OBJECTIVE" && -n "$SUCCESS" && -n "$IN_SCOPE" && -n "$OUT_OF_SCOPE" ]] || { echo "all project intent and boundary arguments are required" >&2; exit 2; }
PROJECT="$(cd -- "$PROJECT" && pwd -P)"
[[ -f "$PROJECT/development-platform.yaml" ]] || { echo "missing development-platform.yaml; run the governed consumer initializer first" >&2; exit 1; }
[[ -d "$PROJECT/agents" ]] || { echo "missing agents/; AOC scaffold is required" >&2; exit 1; }

mkdir -p "$PROJECT/.planning/phases" "$PROJECT/.forge" "$PROJECT/docs/architecture"
# Install the versioned Humanizer scaffold. Installation never enables it.
"$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/init-humanizer-v05.sh" --project "$PROJECT"
# Install shared quality wrappers and dormant learning/test scaffolds.
"$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/init-development-quality.sh" \
  --project "$PROJECT" --project-id "$PROJECT_ID" \
  --capability gsd --capability ocr --capability property-testing

if [[ ! -e "$PROJECT/.development-platform/capabilities.yaml" ]]; then
cat > "$PROJECT/.development-platform/capabilities.yaml" <<EOF
schema: development-capability-selection.v1
project_id: ${PROJECT_ID}
capabilities:
  gsd:
    enabled: true
    implementation: gsd.master
    version: 3.3.0
EOF
elif ! grep -q '^  gsd:' "$PROJECT/.development-platform/capabilities.yaml"; then
cat >> "$PROJECT/.development-platform/capabilities.yaml" <<EOF
  gsd:
    enabled: true
    implementation: gsd.master
    version: 3.3.0
EOF
fi

write_once "$PROJECT/.planning/ROADMAP.md" <<EOF
# ${PROJECT_ID} GSD Roadmap

## Phase 000 — Governed project bootstrap

${OBJECTIVE}

Success: ${SUCCESS}
EOF
write_once "$PROJECT/.planning/STATE.md" <<EOF
# ${PROJECT_ID} GSD State

- Current phase: `000-governed-bootstrap`
- Execution profile: `small`
- Status: planning layer created; verification pending
- Owner: ${OWNER}
- Next gate: complete the Control Matrix and verify the declared success criteria
- Disabled until separately qualified: writes, shell, tests, sandbox, network, provider tools, deployment, and production actions
EOF
write_once "$PROJECT/.planning/phases/000-governed-bootstrap.md" <<EOF
# Phase 000 — Governed project bootstrap

## Intent
${OBJECTIVE}

## Success criteria
${SUCCESS}

## In scope
${IN_SCOPE}

## Out of scope
${OUT_OF_SCOPE}

## Required gates
- Radix project-scoped context generation
- One no-tools provider response
- Control Matrix review
- Architecture Challenge review
- Capability-specific verification evidence
EOF
write_once "$PROJECT/docs/architecture/control-matrix.md" <<EOF
# Control Matrix — Bootstrap

| Control | Requirement | Status |
|---|---|---|
| Authority | ${PROJECT_ID} uses project-local records only | PENDING REVIEW |
| Context isolation | No other consumer state is inherited | PENDING REVIEW |
| Provider secrets | External references only | PENDING REVIEW |
| Capability scope | First capability is explicit and narrow | PENDING REVIEW |
| Verification | Evidence exists before promotion | PENDING REVIEW |
EOF
write_once "$PROJECT/docs/architecture/architecture-challenge.md" <<EOF
# Architecture Challenge — Bootstrap

- Owner: ${OWNER}
- Does the design inherit another project's state? It must not.
- Can model output grant authority? No; Nexus and project policy decide.
- Is the first capability narrower than necessary? Confirm before approval.
- What remains unproven? Record provider, executor, and verification gaps here.
EOF
write_once "$PROJECT/docs/governance/execution-profile.md" <<EOF
# Execution Profile — Bootstrap

- Profile: `small`
- Reason: bounded project bootstrap with explicit success criteria.
- Heavy stages remain deferred until the work meets the full-pipeline criteria.
- This profile never grants capabilities or overrides policy.
EOF
write_once "$PROJECT/.forge/manifest.yaml" <<EOF
schema: forge-manifest.v1
project_id: ${PROJECT_ID}
enabled: false
status: proposal
reason: Project-specific Forge qualification is pending.
verification: project-defined
EOF
echo "GSD project layer initialized under $PROJECT"
echo "Next: review .planning/phases/000-governed-bootstrap.md, then run Radix project-scoped startup."
