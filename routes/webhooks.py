"""
VerifiAgent webhook routes — GitHub App event handling.
"""

import hmac
import hashlib
import json
from fastapi import APIRouter, Request, HTTPException, Header, Depends
from typing import Optional

from config import settings
from models.verification import WebhookPayload, VerificationReport
from services.verdict_engine import VerdictEngine
from services import github_app_client as gh_app

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def verify_github_signature(
    payload: bytes,
    signature: str,
    secret: str = settings.github_webhook_secret,
) -> bool:
    """Verify GitHub webhook signature."""
    if not signature:
        return False
    expected = "sha256=" + hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def verify_github_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None),
    x_hub_signature: Optional[str] = Header(None),
    x_github_event: Optional[str] = Header(None),
):
    """Dependency to verify GitHub webhook signature."""
    if settings.github_webhook_secret == "development-secret-change-me":
        # Skip verification in development
        return True

    payload = await request.body()
    signature = x_hub_signature_256 or x_hub_signature

    if not signature:
        raise HTTPException(status_code=401, detail="Missing signature")

    if not verify_github_signature(payload, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    return True


@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: Optional[str] = Header(None),
    _: bool = Depends(verify_github_webhook),
):
    """
    Handle GitHub App webhook events.

    Triggers on:
    - pull_request (opened, synchronize)
    - check_run (completed)
    - installation (created, deleted)
    """
    event = x_github_event or "unknown"
    payload = await request.json()

    if event == "pull_request":
        action = payload.get("action")
        pr = payload.get("pull_request", {})
        repo = payload.get("repository", {})
        installation = payload.get("installation", {})

        if action in ("opened", "synchronize", "reopened"):
            pr_url = pr.get("html_url")
            commit_sha = pr.get("head", {}).get("sha", "")
            repo_url = repo.get("html_url", "")
            repo_full = repo.get("full_name", "")

            # Queue verification (in production: use a task queue)
            # For now: run synchronously with timeout
            try:
                engine = VerdictEngine()
                report = engine.verify_pr(
                    repo_url=repo_url,
                    commit_sha=commit_sha,
                    pr_url=pr_url,
                )

                # Post GitHub Check Run if we have installation context
                installation_id = installation.get("id") if installation else None
                if installation_id and commit_sha and repo_full:
                    try:
                        gh_app.create_check_run(
                            repo_full=repo_full,
                            commit_sha=commit_sha,
                            installation_id=int(installation_id),
                            verdict=report.verdict.value,
                            summary=report.summary,
                            report_id=str(report.id),
                        )
                    except Exception as check_err:
                        pass  # Don't fail the webhook if Check Run post fails

                return {
                    "status": "verification_complete",
                    "report_id": str(report.id),
                    "verdict": report.verdict.value,
                    "summary": report.summary,
                }
            except Exception as e:
                return {
                    "status": "verification_failed",
                    "error": str(e),
                }

    elif event == "installation":
        # GitHub App installed/uninstalled
        action = payload.get("action")
        installation_id = payload.get("installation", {}).get("id")
        return {
            "status": "installation_event",
            "action": action,
            "installation_id": installation_id,
        }

    return {"status": "event_received", "event": event}


@router.post("/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    # For future: handle payment events
    return {"status": "received"}
