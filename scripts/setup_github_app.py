#!/usr/bin/env python3
"""
VerifiAgent GitHub App Setup Script

Creates and registers a GitHub App for VerifiAgent.
Run once to set up the GitHub App, then install it on repos.

Usage:
    python scripts/setup_github_app.py [--configure]
    python scripts/setup_github_app.py [--register]
    python scripts/setup_github_app.py [--install]
"""

import argparse
import json
import os
import sys
import subprocess
import webbrowser
from pathlib import Path
from uuid import uuid4


GITHUB_APP_MANIFEST = {
    "name": "VerifiAgent",
    "url": "https://github.com/marketplace/verifiagent",
    "description": "Adversarial verification for AI coding — catch what tests miss",
    "primary_category": "Developer Tools",
    "secondary_categories": ["Code Review", "Security"],
    "installation_url": "https://github.com/apps/verifiagent/installations/selector",
    "redirect_url": "https://verifiagent.ai/github/callback",
    "callback_urls": ["https://verifiagent.ai/github/callback"],
    "request_oauth_on_install": True,
    "setup_url": "https://verifiagent.ai/github/setup",
    "setup_on_update": True,
    "oauth_callback_url": "https://verifiagent.ai/github/oauth/callback",
    "default_permissions": {
        "contents": "read",
        "pull_requests": "read",
        "commit_statuses": "write",
        "checks": "write",
        "metadata": "read",
        "webhooks": "write",
        "emails": "read",
    },
    "default_events": [
        "push",
        "pull_request",
        "pull_request_review",
        "pull_request_review_comment",
        "check_run",
        "check_suite",
        "installation",
        "installation_repositories",
    ],
    "public": False,
}


def get_github_token():
    """Get GitHub token from gh CLI."""
    result = subprocess.run(
        ["gh", "auth", "token"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("Not authenticated with GitHub. Run: gh auth login")
    return result.stdout.strip()


def register_github_app(manifest: dict) -> dict:
    """Register a GitHub App from manifest."""
    import urllib.request
    import urllib.error

    # Create the manifest
    manifest_str = json.dumps(manifest)
    manifest_b64 = __import__("base64").b64encode(manifest_str.encode()).decode()

    # Use GitHub's App registration endpoint
    url = "https://api.github.com/app-manifests/verifiagent/conversions"

    data = json.dumps({"manifest": manifest_str}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"token {get_github_token()}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github.v3+json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            print(f"✅ GitHub App registered!")
            print(f"   App name: {result.get('name')}")
            print(f"   App ID: {result.get('id')}")
            print(f"   Client ID: {result.get('client_id')}")
            print(f"   Setup URL: {result.get('html_url')}")
            return result
    except urllib.error.HTTPError as e:
        error_body = json.loads(e.read().decode())
        raise RuntimeError(f"Failed to register: {error_body.get('message', str(e))}")


def create_github_app_via_api(name: str, token: str) -> dict:
    """Create GitHub App via API (alternative to manifest)."""
    import urllib.request
    import urllib.error

    permissions = {
        "contents": "read",
        "pull_requests": "read",
        "commit_statuses": "write",
        "checks": "write",
        "metadata": "read",
        "webhooks": "write",
    }

    webhook_active = True

    # Generate a random RSA key
    import cryptography.hazmat.primitives.asymmetric.rsa as rsa
    import cryptography.hazmat.primitives.serialization as serialization
    import base64

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_base64 = base64.b64encode(pem).decode()

    payload = {
        "name": name,
        "url": "https://verifiagent.ai",
        "description": "Adversarial verification for AI coding — catch what tests miss",
        "public": False,
        "permissions": permissions,
        "events": [
            "push",
            "pull_request",
            "check_run",
            "check_suite",
            "installation",
        ],
        "webhook_active": webhook_active,
        "webhook_secret": os.environ.get("GITHUB_WEBHOOK_SECRET", "change-me"),
    }

    url = "https://api.github.com/app"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github.v3+json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            # Save the private key to a file
            key_path = Path.home() / ".verifiagent" / "github-app-private-key.pem"
            key_path.parent.mkdir(exist_ok=True)
            key_path.write_bytes(pem)
            key_path.chmod(0o600)
            print(f"✅ GitHub App created: {result['name']}")
            print(f"   App ID: {result['id']}")
            print(f"   Private key saved to: {key_path}")
            return result
    except urllib.error.HTTPError as e:
        error_body = json.loads(e.read().decode())
        raise RuntimeError(f"Failed to create: {error_body.get('message', str(e))}")


def install_github_app(app_slug: str):
    """Open browser to install GitHub App."""
    install_url = f"https://github.com/apps/{app_slug}/installations/new"
    print(f"Opening browser to install GitHub App...")
    print(f"URL: {install_url}")
    webbrowser.open(install_url)


def write_env_file(app_id: int, client_id: str, webhook_secret: str):
    """Write configuration to .env file."""
    env_path = Path(__file__).parent.parent / ".env"
    content = f"""# VerifiAgent Configuration
# Generated by setup_github_app.py

# App
APP_NAME=VerifiAgent
VERSION=0.1.0
HOST=127.0.0.1
PORT=8003

# Database
DATABASE_URL=sqlite:///./verifiagent.db

# GitHub App
GITHUB_APP_ID={app_id}
GITHUB_WEBHOOK_SECRET={webhook_secret}
# Private key path (set during app creation)
GITHUB_APP_PRIVATE_KEY_PATH=~/.verifiagent/github-app-private-key.pem

# API Keys
ADMIN_KEY=change-me-in-production
API_KEY_HEADER=X-API-Key

# Attribution (70/30 split)
ATTRIBUTION_SPLIT=0.70

# Paths
MEMORY_DIR=~/.openclaw/workspace-aurex/memory
SCRATCH_DIR=/tmp/verifiagent-scratch
"""
    Path(env_path).write_text(content)
    print(f"✅ Configuration written to: {env_path}")


def generate_webhook_secret() -> str:
    """Generate a random webhook secret."""
    import secrets
    return secrets.token_hex(32)


def main():
    parser = argparse.ArgumentParser(description="VerifiAgent GitHub App Setup")
    parser.add_argument("--register", action="store_true", help="Register GitHub App")
    parser.add_argument("--install", action="store_true", help="Open install URL")
    parser.add_argument("--configure", action="store_true", help="Configure .env file")
    args = parser.parse_args()

    if not any(vars(args).values()):
        parser.print_help()
        print("\n--- Setup Steps ---")
        print("1. Run: python scripts/setup_github_app.py --register")
        print("   This creates the GitHub App and saves credentials")
        print("2. Run: python scripts/setup_github_app.py --install")
        print("   This opens the browser to install on your org/repos")
        print("3. Start server: uvicorn app:app --port 8003")
        print("4. Set webhook URL in GitHub App settings:")
        print("   https://your-domain.com/webhooks/github")
        return

    token = get_github_token()
    print(f"Authenticated as: {subprocess.run(['gh', 'api', 'user', '--jq', '.login'], capture_output=True, text=True).stdout.strip()}")

    if args.register:
        webhook_secret = generate_webhook_secret()
        app = create_github_app_via_api("VerifiAgent", token)
        write_env_file(app["id"], app["client_id"], webhook_secret)
        print(f"\nNext: python scripts/setup_github_app.py --install")

    elif args.install:
        install_github_app("verifiagent")

    elif args.configure:
        webhook_secret = generate_webhook_secret()
        app_id = input("Enter GitHub App ID: ").strip()
        client_id = input("Enter GitHub Client ID: ").strip()
        write_env_file(app_id, client_id, webhook_secret)


if __name__ == "__main__":
    main()
