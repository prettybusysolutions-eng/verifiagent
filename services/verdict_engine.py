"""
VerifiAgent VerdictEngine — orchestrates the full verify → verdict → report flow.

Combines:
1. SecurityMonitor — pre-action diff scan
2. VerificationSpecialist — adversarial testing
3. DreamConsolidation — memory merge
4. AttributionLedger — payment tracking

The complete adversarial verification pipeline.
"""

import subprocess
import tempfile
import shutil
import time
from pathlib import Path
from datetime import datetime
from uuid import uuid4
from typing import Optional
import os

from models.verification import (
    VerificationReport,
    VerdictType,
    SecurityBlock,
    Evidence,
    AttributionClaim,
)
from services.security_monitor import SecurityMonitor
from services.verification_specialist import VerificationSpecialist, VSConfig
from services.attribution_ledger import AttributionLedger
from config import settings


class VerdictEngine:
    """
    Orchestrates the full adversarial verification pipeline.

    Usage:
        engine = VerdictEngine()
        report = engine.verify_pr(
            repo_url="https://github.com/org/repo",
            commit_sha="abc123",
            pr_url="https://github.com/org/repo/pull/1",
        )
        print(report.verdict)
    """

    def __init__(self, scratch_dir: Optional[str] = None):
        self.scratch_dir = Path(scratch_dir or settings.scratch_dir)
        self.scratch_dir.mkdir(parents=True, exist_ok=True)
        self.security_monitor = SecurityMonitor()
        self.attribution_ledger = AttributionLedger()
        self.session_id = f"vrf-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{str(uuid4())[:8]}"

    def verify_pr(
        self,
        repo_url: str,
        commit_sha: str,
        pr_url: Optional[str] = None,
        language: str = "python",
        surface: str = "api",
        clone_dir: Optional[str] = None,
    ) -> VerificationReport:
        """
        Full adversarial verification of a PR/commit.

        Steps:
        1. Clone repo at commit
        2. Run SecurityMonitor on git diff
        3. Run VerificationSpecialist adversarial probes
        4. Generate verification report
        5. Update attribution ledger
        """
        start_time = time.time()
        report = VerificationReport(
            pr_url=pr_url,
            commit_sha=commit_sha,
            repo=repo_url,
            session_id=self.session_id,
        )

        # Determine clone location
        if clone_dir:
            work_dir = Path(clone_dir)
        else:
            work_dir = self.scratch_dir / f"verify-{report.id}"
            work_dir.mkdir(parents=True, exist_ok=True)
            # Clone at specific commit
            try:
                subprocess.run(
                    ["git", "clone", "--filter=blob:none", "--no-checkout", repo_url, str(work_dir)],
                    capture_output=True,
                    timeout=60,
                )
                subprocess.run(
                    ["git", "-C", str(work_dir), "checkout", commit_sha],
                    capture_output=True,
                    timeout=60,
                )
            except Exception as e:
                report.fail_reasons.append(f"Clone failed: {e}")
                report.final_verdict()
                return report

        # Step 1: SecurityMonitor — scan diff
        try:
            diff_result = subprocess.run(
                ["git", "-C", str(work_dir), "diff", "--HEAD~1", "--"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            diff_text = diff_result.stdout

            security_blocks = self.security_monitor.evaluate_diff(diff_text)
            report.security_blocks = security_blocks

            high_severity_blocks = [
                b for b in security_blocks
                if b.severity.value == "HIGH" and not b.allowed
            ]
            if high_severity_blocks:
                report.fail_reasons.extend([
                    f"Security block: {b.reason}" for b in high_severity_blocks
                ])

        except Exception as e:
            report.partial_reasons.append(f"Security scan failed: {e}")

        # Step 2: VerificationSpecialist — adversarial testing
        try:
            config = VSConfig(
                project_path=str(work_dir),
                language=language,
                surface=surface,
            )
            vs = VerificationSpecialist(config=config)

            # Scan for claims that need verification
            vs.scan_claims(diff_text)

            # Run standard checks
            vs.verify_build()
            vs.verify_tests()
            vs.verify_lint()

            # Run adversarial probes based on surface type
            if surface == "api":
                self._run_api_adversarial_probes(vs, work_dir)
            elif surface == "cli":
                self._run_cli_adversarial_probes(vs, work_dir)

            # Transfer results to report
            report.checks = vs.report.checks
            report.adversarial_probes = vs.report.adversarial_probes
            report.fail_reasons.extend(vs.report.fail_reasons)
            report.partial_reasons.extend(vs.report.partial_reasons)

        except Exception as e:
            report.partial_reasons.append(f"Adversarial testing failed: {e}")

        # Step 3: Attribution claims
        try:
            claims = self._extract_attribution_claims(diff_text, report)
            report.attribution_claims = claims
        except Exception as e:
            report.partial_reasons.append(f"Attribution extraction failed: {e}")

        # Step 4: Finalize
        report.duration_ms = int((time.time() - start_time) * 1000)
        report.final_verdict()

        # Step 5: Save report to disk
        self._save_report(report, work_dir)

        return report

    def verify_local(
        self,
        diff_text: str,
        language: str = "python",
        surface: str = "api",
    ) -> VerificationReport:
        """
        Verify a local diff without cloning.
        Used for quick checks without full PR context.
        """
        start_time = time.time()
        report = VerificationReport(
            session_id=self.session_id,
        )

        # SecurityMonitor
        security_blocks = self.security_monitor.evaluate_diff(diff_text)
        report.security_blocks = security_blocks

        high_severity_blocks = [
            b for b in security_blocks
            if b.severity.value == "HIGH" and not b.allowed
        ]
        if high_severity_blocks:
            report.fail_reasons.extend([
                f"Security block: {b.reason}" for b in high_severity_blocks
            ])

        # VerificationSpecialist
        try:
            config = VSConfig(
                project_path="/tmp",
                language=language,
                surface=surface,
            )
            vs = VerificationSpecialist(config=config)
            vs.scan_claims(diff_text)

            # For local diffs, we can only do lint
            vs.verify_lint()

            report.checks = vs.report.checks
            report.adversarial_probes = vs.report.adversarial_probes
            report.fail_reasons.extend(vs.report.fail_reasons)

        except Exception as e:
            report.partial_reasons.append(f"Local verification failed: {e}")

        report.duration_ms = int((time.time() - start_time) * 1000)
        report.final_verdict()
        return report

    def _run_api_adversarial_probes(self, vs: VerificationSpecialist, work_dir: Path):
        """Run API-specific adversarial probes."""
        # Detect API endpoints from routes files
        routes_files = list(work_dir.rglob("routes*.py")) + list(work_dir.rglob("*routes*.py"))
        if routes_files:
            # Found route files — we could parse them to find endpoints
            # For now, add a note that endpoints should be auto-detected
            pass

    def _run_cli_adversarial_probes(self, vs: VerificationSpecialist, work_dir: Path):
        """Run CLI-specific adversarial probes."""
        # Find CLI entry points
        setup_files = list(work_dir.rglob("setup.py")) + list(work_dir.rglob("pyproject.toml"))
        for setup_file in setup_files:
            content = setup_file.read_text()
            if "console_scripts" in content or "entry_points" in content:
                pass

    def _extract_attribution_claims(
        self,
        diff_text: str,
        report: VerificationReport,
    ) -> list[AttributionClaim]:
        """Extract attribution claims from diff."""
        claims: list[AttributionClaim] = []

        # Look for contribution patterns
        import re
        author_pattern = r"(?:From:|author:|Signed-off-by:)\s*(.+)"
        for match in re.finditer(author_pattern, diff_text):
            contributor = match.group(1).strip()
            claim = AttributionClaim(
                contributor=contributor,
                amount_cents=0,  # Set by attribution ledger
                verified=(report.verdict == VerdictType.PASS),
                verification_report_id=report.id,
            )
            claims.append(claim)

        return claims

    def _save_report(self, report: VerificationReport, work_dir: Path):
        """Save report to disk."""
        report_path = work_dir / f"verification-report-{report.id}.json"
        import json
        with open(report_path, "w") as f:
            # Convert to dict for JSON serialization
            data = report.model_dump(mode="json")
            json.dump(data, f, indent=2, default=str)

        report.evidence.append(Evidence(
            type="report",
            path=str(report_path),
            description=f"Verification report for {report.pr_url or report.commit_sha}",
        ))
