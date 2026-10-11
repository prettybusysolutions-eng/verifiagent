"""Exact-commit, evidence-bound verification with fail-closed worker admission."""
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit
from models.verification import VerificationReport, VerdictType, Evidence
from services.security_monitor import SecurityMonitor
from services.verification_specialist import VerificationSpecialist, VSConfig
from services.isolated_runner import IsolatedRunner
from config import settings


class VerdictEngine:
    def __init__(self, scratch_dir=None, command_runner=None):
        self.scratch_dir = Path(scratch_dir or settings.scratch_dir)
        self.security_monitor = SecurityMonitor()
        self.command_runner = command_runner

    def verify_local(self, diff_text, language='python', surface='api'):
        report = VerificationReport()
        report.security_blocks = self.security_monitor.evaluate_diff(diff_text)
        report.fail_reasons = [b.reason for b in report.security_blocks if b.severity.value == 'HIGH' and not b.allowed]
        report.partial_reasons.append('Static diff scan only; no runtime or target-state verification')
        report.final_verdict()
        return report

    @staticmethod
    def _git(work_dir, *args):
        return subprocess.run(['git', '-C', str(work_dir), *args], capture_output=True,
                              text=True, timeout=60, check=True)

    def verify_pr(self, repo_url, commit_sha, pr_url=None, language='python', surface='api', clone_dir=None, base_sha=None):
        report = VerificationReport(repo=repo_url, commit_sha=commit_sha, pr_url=pr_url)
        start = time.monotonic()
        try:
            if not re.fullmatch(r'[0-9a-f]{40}', commit_sha or ''):
                raise ValueError('Full hexadecimal commit SHA required')
            if base_sha and not re.fullmatch(r'[0-9a-f]{40}', base_sha):
                raise ValueError('Full base SHA required')
            url = urlsplit(repo_url)
            if url.scheme != 'https' or url.netloc != 'github.com' or url.query or url.fragment or not re.fullmatch(r'/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', url.path):
                raise ValueError('Canonical HTTPS GitHub repository URL required')
            if clone_dir is None and repo_url not in settings.allowed_repositories:
                report.partial_reasons.append('Repository not admitted by operator allowlist')
                report.final_verdict()
                return report
            runner = self.command_runner or IsolatedRunner(settings.worker_image)
            if clone_dir is not None:
                work_dir = Path(clone_dir).resolve(strict=True)
            else:
                self.scratch_dir.mkdir(parents=True, exist_ok=True)
                work_dir = self.scratch_dir / ('verify-' + str(report.id))
                subprocess.run(['git', 'clone', '--no-checkout', '--', repo_url, str(work_dir)],
                               capture_output=True, text=True, timeout=60, check=True)
                self._git(work_dir, 'checkout', '--detach', commit_sha)
            actual_sha = self._git(work_dir, 'rev-parse', 'HEAD').stdout.strip()
            if actual_sha != commit_sha:
                raise ValueError('Checkout does not match requested commit')
            if self._git(work_dir, 'status', '--porcelain', '--untracked-files=all').stdout:
                raise ValueError('Dirty checkout cannot verify an exact commit')
            if base_sha:
                diff = self._git(work_dir, 'diff', '--binary', base_sha, commit_sha, '--').stdout
            else:
                diff = self._git(work_dir, 'show', '--format=', '--binary', commit_sha, '--').stdout
                report.partial_reasons.append('No PR base SHA provided: scan covers this commit only')
            report.security_blocks = self.security_monitor.evaluate_diff(diff)
            report.fail_reasons.extend(b.reason for b in report.security_blocks if b.severity.value == 'HIGH' and not b.allowed)
            if not report.fail_reasons:
                specialist = VerificationSpecialist(VSConfig(str(work_dir), language, surface), command_runner=runner)
                specialist.verify_build()
                specialist.verify_tests()
                specialist.verify_lint()
                specialist.finalize()
                report.checks = specialist.report.checks
                report.adversarial_probes = specialist.report.adversarial_probes
                report.fail_reasons.extend(specialist.report.fail_reasons)
                report.partial_reasons.extend(specialist.report.partial_reasons)
        except subprocess.CalledProcessError as exc:
            # Infrastructure/preparation errors do not prove target correctness.
            report.partial_reasons.append('Git preparation/observation failed with exit ' + str(exc.returncode))
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            report.partial_reasons.append('Verification unavailable: ' + str(exc))
        report.duration_ms = int((time.monotonic() - start) * 1000)
        report.final_verdict()
        return report
