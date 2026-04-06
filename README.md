# VerifiAgent — Adversarial Verification as a Product

**The category-defining product for AI coding tools.**

Every AI coding tool ships bugs that tests don't catch. VerifiAgent is the adversarial verification layer that catches what the implementer missed.

---

## The Problem

AI coding tools (Cursor, Copilot, Claude Code, Codeium) all claim to verify. None of them actually do.

- They run tests written by the **same AI that wrote the bugs** — circular
- They check code quality, not **actual behavior at runtime**
- They miss: boundary failures, idempotency bugs, concurrency races, orphan operations
- No compliance artifact for SOC2, ISO 27001

---

## The Solution

```
PR created
    ↓
SecurityMonitor (pre-action guard)
    ↓ [BLOCK] → don't execute, report why
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
AttributionLedger (70/30 on verified contributions)
```

---

## What We Test

### SecurityMonitor
- **Credential embedding** — API keys hardcoded in diff
- **Force push** — rewriting remote history
- **Production deploy** — bypassing review
- **Blind apply** — `--yes --force` flags
- **External code execution** — `curl | bash`
- **Destructive local** — `rm -rf` without target naming
- **Scope escalation** — action beyond original task
- **Real-world transactions** — financial ops

### VerificationSpecialist — Adversarial Probes

| Probe | What it does |
|-------|-------------|
| **Boundary** | 0, -1, empty, 10KB string, unicode bomb, MAX_INT |
| **Idempotency** | Same mutation twice — duplicate or no-op? |
| **Concurrency** | 10 parallel create-if-not-exists — race condition? |
| **Orphan** | Delete/reference non-existent ID — graceful error? |

---

## Installation

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your credentials
uvicorn app:app --host 127.0.0.1 --port 8003
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/verify/pr` | Trigger full PR verification (async) |
| `POST` | `/verify/local` | Verify local diff (sync) |
| `GET` | `/verify/report/{id}` | Fetch verification report |
| `GET` | `/verify/health` | Liveness probe |
| `GET` | `/verify/ready` | Readiness probe |
| `POST` | `/webhooks/github` | GitHub App webhook receiver |

---

## Verification Report

```json
{
  "id": "uuid",
  "pr_url": "https://github.com/org/repo/pull/1",
  "verdict": "FAIL",
  "security_blocks": [
    {
      "condition": "credential_embed",
      "reason": "BLOCK: Embedding secrets in code...",
      "severity": "HIGH",
      "allowed": false
    }
  ],
  "checks": [
    {
      "name": "Build",
      "command": "npm run build",
      "passed": true
    }
  ],
  "adversarial_probes": [
    {
      "type": "idempotency",
      "name": "Idempotency (call 2 — same params)",
      "passed": false,
      "notes": "Second call produced duplicate resource"
    }
  ],
  "duration_ms": 4723,
  "summary": "FAIL — 2 issue(s)"
}
```

---

## Pricing

| Tier | Price | Verifications/month |
|------|-------|-------------------|
| Free | $0 | 10 |
| Pro | $49/seat | 500 |
| Team | $199 | 2000 + dashboard |
| Enterprise | $999 | Unlimited + compliance + SSO |

Attribution claims paid out at **70/30** (contributor / VerifiAgent) from subscription revenue.

---

## GitHub App Integration

1. Create a GitHub App in your organization settings
2. Set webhook URL to `https://your-domain.com/webhooks/github`
3. Install on repos you want protected
4. On PR open/sync: VerifiAgent runs automatically
5. FAIL verdict → comment posted + merge blocked

---

## Architecture

```
verifiagent/
├── app.py                          # FastAPI app + lifespan
├── config.py                       # Settings
├── routes/
│   ├── verify.py                   # /verify/* endpoints
│   └── webhooks.py                 # /webhooks/* endpoints
├── services/
│   ├── security_monitor.py          # Pre-action guard
│   ├── verification_specialist.py   # Adversarial testing
│   ├── verdict_engine.py           # Orchestrator
│   └── attribution_ledger.py        # Payment tracking
├── models/
│   └── verification.py             # Data models
└── scripts/
    └── github_app.py               # GitHub App setup
```

---

## Built With

- **SecurityMonitor** — from live Code system prompts (5876 tokens)
- **VerificationSpecialist** — from live Code system prompts (2866 tokens)
- **DreamConsolidation** — memory layer for session learning
- **Context Nexus** — persistent memory infrastructure

---

## Status

v0.1 — Core components built
- ✅ SecurityMonitor (14 BLOCK conditions, 6 ALLOW exceptions)
- ✅ VerificationSpecialist (4 adversarial probe types)
- ✅ VerdictEngine (orchestrator)
- ✅ AttributionLedger (70/30 payment tracking)
- ✅ FastAPI with health probes
- ✅ GitHub webhook receiver
- ⏳ GitHub App deployment
- ⏳ Persistence layer (DB)
- ⏳ Pricing/billing integration
- ⏳ Compliance report generation

---

**The verification product the AI coding space needs.**
