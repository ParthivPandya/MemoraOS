#!/usr/bin/env bash
# Builds the image and checks: healthy, 401 without a key, remember+recall through the API,
# persistence across restart, and an encrypted database file. Run from the repository root.
set -euo pipefail

IMAGE=memoraos:ci
NAME=mos-smoke
VOL=mos-smoke-data
PORT=18000
PASS=docker-smoke-pass

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; docker volume rm "$VOL" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

docker build -q -t "$IMAGE" .
KEY=$(docker run --rm -v "$VOL":/data -e MEMORAOS_ENCRYPTION_KEY="$PASS" "$IMAGE" keys create --tenant default --role admin | grep -E '^\S{20,}$' | tail -n 1)
docker run -d --name "$NAME" -p 127.0.0.1:$PORT:8000 -v "$VOL":/data -e MEMORAOS_ENCRYPTION_KEY="$PASS" "$IMAGE" >/dev/null

wait_healthy() {
  for _ in $(seq 1 30); do
    curl -fs "http://127.0.0.1:$PORT/v1/health" >/dev/null 2>&1 && return 0
    sleep 1
  done
  docker logs "$NAME"; return 1
}
recall() {
  curl -fs -X POST "http://127.0.0.1:$PORT/v1/recall" -H "Authorization: Bearer $KEY" \
    -H "Content-Type: application/json" -d '{"user_id":"u1","query":"Where does Alice work?"}'
}

wait_healthy
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/v1/recall" -H "Content-Type: application/json" -d '{}' || true)
[ "$code" = "401" ] || { echo "expected 401 without a key, got $code"; exit 1; }

curl -fs -X POST "http://127.0.0.1:$PORT/v1/memories" -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" -d '{"user_id":"u1","text":"Alice works at Initech."}' >/dev/null
out=$(recall); echo "$out" | grep -q '"answered"'; echo "$out" | grep -q Initech

docker restart "$NAME" >/dev/null
wait_healthy
out=$(recall); echo "$out" | grep -q Initech

header=$(docker run --rm -v "$VOL":/data --entrypoint python "$IMAGE" -c "print(open('/data/memoraos.db','rb').read(16)[:6])")
echo "db header: $header"
echo "$header" | grep -q 'SQLite' && { echo "database is not encrypted"; exit 1; }
echo "docker smoke test passed"
