#!/usr/bin/env bash
# Install the project-local, dormant Humanizer v0.5 scaffold.
set -euo pipefail

PROJECT=""
CORE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --help|-h) echo "Usage: init-humanizer-v05.sh --project PROJECT_ROOT"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$PROJECT" ]] || { echo "--project is required" >&2; exit 2; }
PROJECT="$(cd -- "$PROJECT" && pwd -P)"
TEMPLATE="$CORE_ROOT/templates/humanizer-v0.5"
[[ -d "$TEMPLATE" ]] || { echo "missing Humanizer v0.5 template" >&2; exit 1; }
while IFS= read -r -d '' source; do
  relative="${source#"$TEMPLATE/"}"
  destination="$PROJECT/$relative"
  mkdir -p "$(dirname -- "$destination")"
  [[ -e "$destination" ]] || install -m 0644 "$source" "$destination"
done < <(find "$TEMPLATE" -type f -print0)
chmod 0755 "$PROJECT/enable-humanizer.sh" 2>/dev/null || true
echo "Humanizer v0.5 scaffold installed under $PROJECT"
echo "State: dormant; qualification and explicit activation are still required."
