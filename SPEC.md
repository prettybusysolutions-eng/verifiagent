# VerifiAgent — SPEC.md

## What It Is

Adversarial verification as a product. Not a feature — a different category.

```
PR created / webhook received
    ↓
SecurityMonitor (pre-action guard)
    ↓ [BLOCK] → stop + report block reason
    ↓ [ALLOW] → continue
    ↓
Build the app
    ↓
VerificationSpecialist (adversarial testing)
    ↓ → boundary values, idempotency, concurrency, orphan ops
    ↓
VERDICT: PASS | FAIL | PARTIAL
    ↓
Report generated (compliance artifact)
    ↓
DreamConsolidation (memory merge — learns from every session)
    ↓
AttributionLedger (70/30 split on verified contributions)
```

## What We Offer That No One Else Does

1. **Pre-action security guard** — blocks destructive ops before they run
2. **Adversarial probes** — actively tries to break what was built
3. **Runtime observation** — builds and runs, doesn't just read code
4. **Compliance artifact** — verification report for SOC2, ISO 27001
5. **Memory across sessions** — learns from every failure, never misses same bug twice

## Architecture

### Core Components

| Component | File | Purpose |
|-----------|------|---------|
| SecurityMonitor | `services/security_monitor.py` | Pre-action guard — BLOCK/ALLOW evaluation |
| VerificationSpecialist | `services/verification_specialist.py` | Adversarial testing — boundary, idempotency, concurrency |
| DreamConsolidation | `services/dream_consolidation.py` | Memory merge after each verification |
| VerdictEngine | `services/verdict_engine.py` | Orchestrates the full verify → verdict → report flow |
| AttributionLedger | `services/attribution_ledger.py` | Tracks contributions, pays 70/30 on verified claims |

### API Design

```
POST /verify/pr
  GitHub webhook → triggers full verification pipeline
  Returns: verification_report (async, webhook callback)

POST /verify/local
  Upload diff/commits → run verification
  Returns: verification_report (sync)

GET  /verify/report/{report_id}
  Fetch verification report
  Returns: VerificationReport

GET  /verify/health
  Liveness probe

GET  /verify/ready
  Readiness probe (DB + GitHub API connectivity)

POST /webhooks/github
  GitHub App webhook receiver
```

### Data Model

```python
VerificationReport:
  id: UUID
  pr_url: str
  commit_sha: str
  verdict: PASS | FAIL | PARTIAL
  security_blocks: list[SecurityBlock]
  checks: list[CheckResult]
  adversarial_probes: list[ProbeResult]
  evidence: list[Evidence]  # captured screenshots, outputs
  timestamp: datetime
  duration_ms: int
  session_id: str
  attribution_claims: list[AttributionClaim]

SecurityBlock:
  condition: str
  reason: str
  severity: HIGH | MEDIUM | LOW
  allowed: bool (if exception applied)

CheckResult:
  name: str
  command: str
  output: str
  passed: bool
  expected: str
  actual: str

ProbeResult:
  type: boundary | idempotency | concurrency | orphan
  command: str
  output: str
  passed: bool
  severity: HIGH | MEDIUM | LOW

AttributionClaim:
  contributor: str
  amount_cents: int
  verified: bool
  verification_report_id: UUID
```

## Pricing Model

| Tier | Price | Limits |
|------|-------|--------|
| Free | $0 | 10 verifications/month |
| Pro | $49/seat/month | 500 verifications/month |
| Team | $199/month | 2000 verifications/month + team dashboard |
| Enterprise | $999/month | Unlimited + compliance reports + SSO + SLA |

Attribution claims paid out at 70/30 (contributor/VerifiAgent) from subscription revenue.

## GitHub App Integration

1. Install GitHub App to org/repo
2. On PR: send webhook to `/webhooks/github`
3. Clone repo at PR commit
4. Run SecurityMonitor on git diff
5. Run VerificationSpecialist adversarial probes
6. Post verdict comment on PR
7. Block merge if FAIL (via GitHub branch protection)

## Competitive Moat

- **Adversarial probe methodology** from leaked Claude Code VerificationSpecialist
- **SecurityMonitor** pre-action guard (5876 token pattern, ours as Python)
- **Context Nexus memory layer** — learns from every failure
- **Attribution ledger** — 70/30 revenue share
- **Compliance artifacts** — SOC2, ISO 27001 evidence bundles

Competitors need 6-12 months to replicate to our depth.

## Production Readiness Checklist

- [x] SPEC.md written
- [ ] app.py — FastAPI with lifespan, health probes
- [ ] routes/verify.py — verification endpoints
- [ ] routes/webhooks.py — GitHub webhook receiver
- [ ] services/security_monitor.py — BLOCK/ALLOW evaluation
- [ ] services/verification_specialist.py — adversarial probes
- [ ] services/verdict_engine.py — orchestrator
- [ ] services/dream_consolidation.py — memory merge
- [ ] services/attribution_ledger.py — payment tracking
- [ ] models/verification.py — data models
- [ ] scripts/github_app.py — GitHub App setup
- [ ] requirements.txt
- [ ] .env.example
- [ ] README.md
- [ ] Smoke tests passing
- [ ] GitHub App deployed and tested

## Status

v0.1 — SPEC only, building now.
