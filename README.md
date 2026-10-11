# VerifiAgent

An operator-only verification pilot. Static diff scanning and configured command checks are distinct from target-specific adversarial verification.

## Evidence contract

- `FAIL`: a configured check or target-specific state oracle observed a failure.
- `PARTIAL`: missing commands, adapters, observations, interrupted jobs, preparation failures or incomplete coverage.
- `PASS`: all requested evidence exists and no failure/unknown condition remains.

Identical responses do not prove idempotency. A probe requires a real target adapter, an independently observed before/after state, and an explicit boolean correctness oracle. The hosted PR path has no automatic target oracle and therefore does not claim complete adversarial verification.

## Local evaluation

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
uvicorn app:app --host 127.0.0.1 --port 8003
```

`GET /verify/health` is liveness. `GET /verify/ready` returns 503 until the durable store, authentication, allowlist and local worker image are available. Health does not establish readiness.

Configure `API_KEY_HASH` as the SHA256 hexadecimal digest of a private operator key. Send that key in `X-API-Key`. `/verify/local`, `/verify/pr`, and report retrieval fail closed without configured authentication. Reports are stored under `REPORT_DB_PATH` (default `./state/reports.sqlite`) and scoped to the authenticated operator fingerprint.

The store is a single-process pilot. At startup, queued/running jobs become `PARTIAL` with an interruption reason; they are never silently retried. Multiple API instances must not share this recovery model until a lease-based worker queue exists.

## Isolated PR commands

Configure `ALLOWED_REPOSITORIES` as a JSON array of canonical HTTPS GitHub URLs and `WORKER_IMAGE` as an already-local image pinned with `@sha256:<digest>`. Supply full `commit_sha`, `base_sha` and `pr_url`. Docker commands have no network, no host credentials, read-only source/root filesystem, a non-root user, dropped capabilities, bounded memory/CPU/PIDs and temporary writable storage. Missing Docker/image configuration never falls back to host execution. Select an image containing the tested project's dependencies; dependencies cannot be fetched during isolated commands.

This worker adapter is not an independently audited hostile-code sandbox. Dedicated worker hosts and durable leases are required before untrusted multi-tenant deployment. Resource controls do not eliminate kernel/runtime vulnerabilities. This change's tests validate admission, verdicts, ownership, restart handling and command construction; an actual Docker execution trial is a separate deployment gate.

GitHub webhooks require a configured signing secret. Automatic webhook-triggered execution returns 503 until durable admission is integrated. Stripe webhook processing returns 501; it does not falsely acknowledge fulfillment.

## Boundaries

No production deployment, security certification, billing, compliance certification, contributor payout, independent review or performance advantage is established by these tests. Pricing is not a delivered billing contract. See [RELEASING.md](RELEASING.md) for artifact gates.
