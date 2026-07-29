#!/usr/bin/env bash
# Verify a running deployment.
#
# Exit 0 means the stack is serving. Used by deploy.sh to decide whether to keep
# a release or roll it back, and safe to run by hand at any time.
#
# Checks the things whose failure a user would notice, in the order they would
# notice them. Container state is not one of them: a container can be "running"
# and serving 500s, so every check here goes through the actual surface.

set -uo pipefail

BASE_URL="${BASE_URL:-http://localhost:8001}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3000}"
TIMEOUT="${HEALTH_TIMEOUT:-10}"

pass=0
fail=0

check() {
	local name="$1" url="$2" expect="${3:-200}"
	local code
	code="$(curl -s -o /dev/null -w '%{http_code}' -m "$TIMEOUT" "$url" 2>/dev/null || echo 000)"
	if [ "$code" = "$expect" ]; then
		printf '  ✓ %-28s %s\n' "$name" "$code"
		pass=$((pass + 1))
	else
		printf '  ✗ %-28s %s (expected %s)\n' "$name" "$code" "$expect"
		fail=$((fail + 1))
	fi
}

check_json() {
	local name="$1" url="$2" needle="$3"
	local body
	body="$(curl -s -m "$TIMEOUT" "$url" 2>/dev/null || true)"
	if printf '%s' "$body" | grep -q "$needle"; then
		printf '  ✓ %-28s %s\n' "$name" "$needle"
		pass=$((pass + 1))
	else
		printf '  ✗ %-28s missing %s\n' "$name" "$needle"
		fail=$((fail + 1))
	fi
}

echo "Health check — backend ${BASE_URL}, frontend ${FRONTEND_URL}"
echo

echo "Backend"
check "liveness" "${BASE_URL}/live"
check "readiness" "${BASE_URL}/ready"
# Readiness reporting 200 while a dependency is down would be the probe lying;
# check the body, not just the status.
check_json "database" "${BASE_URL}/ready" '"database":{"status":"ok"}'
check_json "redis" "${BASE_URL}/ready" '"redis":{"status":"ok"}'
check "scores API" "${BASE_URL}/api/v1/scores/top?page_size=1"
check "scoring model" "${BASE_URL}/api/v1/scores/model"
check "token feed" "${BASE_URL}/api/v1/tokens/latest?limit=1"

echo
echo "Frontend"
check "landing" "${FRONTEND_URL}/"
check "command centre" "${FRONTEND_URL}/command"
check "scanner" "${FRONTEND_URL}/feed"
check "division" "${FRONTEND_URL}/division"
check "system" "${FRONTEND_URL}/system"

echo
echo "${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ] || exit 1
