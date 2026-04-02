"""
GitHub App client — JWT auth + Check Run API.
"""
import os, time, json, requests
import jwt as pyjwt
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

APP_ID   = os.getenv("GITHUB_APP_ID", "")
PEM_PATH = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", "")
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")


def _app_jwt() -> str:
    """Generate a short-lived JWT for GitHub App authentication."""
    with open(PEM_PATH) as f:
        key = f.read()
    now = int(time.time())
    token = pyjwt.encode(
        {"iat": now - 60, "exp": now + 600, "iss": APP_ID},
        key, algorithm="RS256"
    )
    return token if isinstance(token, str) else token.decode()


def _installation_token(installation_id: int) -> str:
    """Exchange JWT for an installation access token."""
    jwt = _app_jwt()
    resp = requests.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/vnd.github.v3+json",
        }
    )
    resp.raise_for_status()
    return resp.json()["token"]


def create_check_run(
    repo_full: str,
    commit_sha: str,
    installation_id: int,
    verdict: str,
    summary: str,
    report_id: str = "",
) -> dict:
    """
    Create a GitHub Check Run on a commit.
    verdict: PASS | FAIL | PARTIAL | BLOCKED
    """
    token = _installation_token(installation_id)

    conclusion_map = {
        "PASS":    "success",
        "FAIL":    "failure",
        "PARTIAL": "neutral",
        "BLOCKED": "action_required",
    }
    conclusion = conclusion_map.get(verdict.upper(), "neutral")

    body = {
        "name": "VerifiAgent Security Scan",
        "head_sha": commit_sha,
        "status": "completed",
        "conclusion": conclusion,
        "output": {
            "title": f"VerifiAgent: {verdict}",
            "summary": summary,
            "text": (
                f"Report ID: `{report_id}`\n\n"
                f"Verdict: **{verdict}**\n\n"
                f"{summary}\n\n"
                f"---\n*Powered by [VerifiAgent](https://github.com/prettybusysolutions-eng/verifiagent) × AION*"
            ),
        },
    }

    resp = requests.post(
        f"https://api.github.com/repos/{repo_full}/check-runs",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        },
        json=body,
    )
    if resp.status_code not in (200, 201):
        return {"error": resp.text, "status_code": resp.status_code}
    return resp.json()
