#!/usr/bin/env bash
# Run the test suite of business-plan-orchestrator.
#
#   bash tests/run-tests.sh                 smoke + integration
#   bash tests/run-tests.sh --smoke         smoke tests only (fast)
#   bash tests/run-tests.sh --integration   integration tests only
#
# Every test is a standalone script invoked as: python <test> --root <repo>.
# Tests work in temporary directories and never write into the checkout.
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(dirname "$here")"
suite="all"
case "${1:-}" in
  ""|--all) suite="all" ;;
  --smoke) suite="smoke" ;;
  --integration) suite="integration" ;;
  -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
  *) echo "unknown option: $1" >&2; exit 2 ;;
esac

py="${PYTHON:-}"
if [[ -z "$py" ]]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >/dev/null 2>&1; then
      py="$candidate"
      break
    fi
  done
fi
if [[ -z "$py" ]]; then
  echo "Python >= 3.12 not found (set PYTHON=/path/to/python)" >&2
  exit 2
fi

export PYTHONDONTWRITEBYTECODE=1
export PYTHONIOENCODING=utf-8

dirs=()
[[ "$suite" == "all" || "$suite" == "smoke" ]] && dirs+=("$here/smoke")
[[ "$suite" == "all" || "$suite" == "integration" ]] && dirs+=("$here/integration")

passed=0
failed=()
for dir in "${dirs[@]}"; do
  for test in "$dir"/test_*.py; do
    name="$(basename "$(dirname "$test")")/$(basename "$test")"
    start=$SECONDS
    if "$py" "$test" --root "$repo"; then
      passed=$((passed + 1))
      echo "ok   $name ($((SECONDS - start))s)"
    else
      failed+=("$name")
      echo "FAIL $name ($((SECONDS - start))s)"
    fi
  done
done

echo
echo "passed: $passed, failed: ${#failed[@]}"
if (( ${#failed[@]} > 0 )); then
  printf '  %s\n' "${failed[@]}"
  exit 1
fi
