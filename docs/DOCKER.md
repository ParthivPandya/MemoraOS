# Running MemoraOS in a container

The image is built from the repository [Dockerfile](../Dockerfile). It installs the `api` and `encryption` extras, runs as a non-root user (uid 10001), keeps all state in the `/data` volume and has a health check on `/v1/health`.

## Quick start

```bash
docker compose build
docker compose run --rm memoraos keys create --tenant default --role admin   # prints the key once; store it
docker compose up -d
curl http://127.0.0.1:8000/v1/health
```

The API refuses to start without at least one key, and `/v1/health` is the only unauthenticated route. The port is published on `127.0.0.1` only; put a TLS reverse proxy in front before exposing it beyond the machine.

## Encrypted data volume

Set a passphrase in your shell before `docker compose up`:

```bash
export MEMORAOS_ENCRYPTION_KEY='a long random passphrase'
```

A new database is then created encrypted (AES-256-GCM, see [SECURITY.md](SECURITY.md#encryption-at-rest)). An existing plain database in the volume is refused rather than silently kept plain; convert it first with `docker compose run --rm memoraos encrypt`. A lost passphrase cannot be recovered.

## What was verified

Run on Docker Desktop with the image built from this repository (the same checks run in CI as `scripts/docker_smoke.sh`, from 0.2.1):

- the container reports `healthy`;
- an unauthenticated request returns 401;
- `remember` then `recall` through the API returns the stored fact;
- the answer is still there after `docker restart` (the volume persists);
- with a passphrase set, the database file on the volume starts with the `MOSENC01` header.

Not verified: other container runtimes, other CPU architectures, and orchestrators.
