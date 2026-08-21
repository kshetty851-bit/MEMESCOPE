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
COOKIE_JAR="$(mktemp -t memescope-health-cookie.XXXXXX)"
ALPHA_PAYLOAD="$(mktemp -t memescope-alpha-payload.XXXXXX)"

pass=0
fail=0

cleanup() {
	rm -f "$COOKIE_JAR"
	rm -f "$ALPHA_PAYLOAD"
}
trap cleanup EXIT

check() {
	local name="$1" url="$2" expect="${3:-200}"
	local code
	# `-L` follows redirects, and the apex host issues one: memescope.site is a
	# 308 to www.memescope.site. Without it every frontend page reported 308
	# against an expected 200, which failed verification on a perfectly healthy
	# release, rolled it back, and then failed the rollback too — because the
	# previous release redirected exactly the same way. A check that cannot
	# pass on any release is not measuring the release.
	code="$(curl -sL -b "$COOKIE_JAR" -o /dev/null -w '%{http_code}' -m "$TIMEOUT" "$url" 2>/dev/null || echo 000)"
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
	body="$(curl -s -b "$COOKIE_JAR" -m "$TIMEOUT" "$url" 2>/dev/null || true)"
	if printf '%s' "$body" | grep -q "$needle"; then
		printf '  ✓ %-28s %s\n' "$name" "$needle"
		pass=$((pass + 1))
	else
		printf '  ✗ %-28s missing %s\n' "$name" "$needle"
		fail=$((fail + 1))
	fi
}

unlock_alpha() {
	if [ -z "${ALPHA_ACCESS_CODE:-}" ]; then
		return
	fi

	chmod 600 "$ALPHA_PAYLOAD"
	printf '{"code":"%s"}' "$ALPHA_ACCESS_CODE" >"$ALPHA_PAYLOAD"

	local code
	code="$(
		curl -s \
			-c "$COOKIE_JAR" \
			-o /dev/null \
			-w '%{http_code}' \
			-m "$TIMEOUT" \
			-H 'Content-Type: application/json' \
			-X POST \
			--data-binary "@${ALPHA_PAYLOAD}" \
			"${BASE_URL}/api/v1/alpha/unlock" 2>/dev/null || echo 000
	)"
	if [ "$code" = "201" ]; then
		printf '  ✓ %-28s %s\n' "alpha unlock" "$code"
		pass=$((pass + 1))
	else
		printf '  ✗ %-28s %s (expected 201)\n' "alpha unlock" "$code"
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
unlock_alpha
if [ -n "${ALPHA_ACCESS_CODE:-}" ]; then
	check_json "alpha session" "${BASE_URL}/api/v1/alpha/session" '"authenticated":true'
fi
check "scores API" "${BASE_URL}/api/v1/scores/top?page_size=1"
check "scoring model" "${BASE_URL}/api/v1/scores/model"
check "token feed" "${BASE_URL}/api/v1/tokens/latest?limit=1"

echo
echo "Frontend"
check "landing" "${FRONTEND_URL}/"
check "command centre" "${FRONTEND_URL}/command"
check "track record" "${FRONTEND_URL}/record"
check "paper wallet" "${FRONTEND_URL}/wallet"
check "strategy lab" "${FRONTEND_URL}/lab"
check "settings" "${FRONTEND_URL}/settings"

echo
echo "${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ] || exit 1
