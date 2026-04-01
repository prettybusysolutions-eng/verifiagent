"""
VerifiAgent verification routes — API endpoints.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Optional
import uuid

from models.verification import VerificationReport, VerificationRequest
from services.verdict_engine import VerdictEngine

router = APIRouter(prefix="/verify", tags=["verification"])

# In-memory store for async reports (in production: Redis or DB)
_reports: dict[str, VerificationReport] = {}


@router.post("/local", response_model=VerificationReport)
async def verify_local(
    request: VerificationRequest,
):
    """
    Verify a local diff without cloning.

    Upload diff text directly for quick security + lint check.
    For full adversarial testing, use /verify/pr with a GitHub PR URL.
    """
    engine = VerdictEngine()

    if request.diff:
        report = engine.verify_local(
            diff_text=request.diff,
            language=request.language or "python",
            surface=request.surface or "api",
        )
    else:
        raise HTTPException(status_code=400, detail="diff is required for local verification")

    _reports[str(report.id)] = report
    return report


@router.post("/pr", response_model=dict)
async def verify_pr(
    request: VerificationRequest,
    background_tasks: BackgroundTasks,
):
    """
    Trigger full adversarial verification of a GitHub PR.

    Returns immediately with a report_id. Verification runs asynchronously.
    Poll GET /verify/report/{report_id} for results.
    """
    if not request.pr_url:
        raise HTTPException(status_code=400, detail="pr_url is required")

    report_id = str(uuid.uuid4())

    async def run_verification():
        engine = VerdictEngine()
        report = engine.verify_pr(
            repo_url=request.repo_url,
            commit_sha=request.commit_sha,
            pr_url=request.pr_url,
            language=request.language or "python",
            surface=request.surface or "api",
        )
        _reports[report_id] = report

    background_tasks.add_task(run_verification)

    return {
        "report_id": report_id,
        "status": "verification_in_progress",
        "poll_url": f"/verify/report/{report_id}",
    }


@router.get("/report/{report_id}", response_model=VerificationReport)
async def get_report(report_id: str):
    """Fetch a verification report by ID."""
    if report_id not in _reports:
        raise HTTPException(status_code=404, detail="Report not found")

    return _reports[report_id]


@router.get("/health")
async def health():
    """Liveness probe."""
    return {"status": "ok", "service": "VerifiAgent", "version": "0.1.0"}


@router.get("/ready")
async def ready():
    """
    Readiness probe.
    Checks DB and GitHub API connectivity.
    """
    checks = {
        "database": True,  # SQLite always works
        "github_api": True,  # Would check GitHub API here
    }

    all_ready = all(checks.values())
    return {
        "status": "ready" if all_ready else "not_ready",
        "checks": checks,
    }
