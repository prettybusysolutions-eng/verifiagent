"""
VerifiAgent VerificationSpecialist — adversarial testing framework.

Built from: Piebald-AI/claude-code-system-prompts
  - agent-prompt-verification-specialist.md

Key principle: "You are Claude, and you are bad at verification."
The implementer is an LLM too — tests may be circular, heavy on mocks,
or assert what the code does instead of what it should do.

Verification = runtime observation. Build the app, run it, capture what
you see. Nothing else is evidence.
"""

import subprocess
import concurrent.futures
import tempfile
import shutil
import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from models.verification import (
    VerificationReport,
    VerdictType,
    CheckResult,
    ProbeResult,
    Evidence,
    Severity,
    ProbeType,
)


@dataclass
class VSConfig:
    """Configuration for the VerificationSpecialist."""
    project_path: str
    language: str = "python"
    surface: str = "api"  # api | cli | gui | library
    timeout_build: int = 120
    timeout_test: int = 120
    timeout_lint: int = 60
    max_concurrency: int = 10


class VerificationSpecialist:
    """
    Adversarial testing framework for VerifiAgent.

    Runs build, test, linter, then adversarial probes:
    - boundary values (0, -1, empty, long string, unicode, MAX_INT)
    - idempotency (same mutation twice)
    - concurrency (parallel create-if-not-exists)
    - orphan operations (non-existent IDs)

    Usage:
        vs = VerificationSpecialist(config=VSConfig(project_path="/path/to/repo"))
        vs.scan_claims("Tests pass. Verified it works.")
        vs.verify_build()
        vs.verify_tests()
        vs.adversarial_probe_boundary_values(endpoint="POST /users", params={"name": "test"})
        report = vs.finalize()
    """

    def __init__(self, config: VSConfig, target_adapter=None, state_observer=None, probe_oracle=None, command_runner=None):
        self.target_adapter = target_adapter
        self.state_observer = state_observer
        self.probe_oracle = probe_oracle
        self.command_runner = command_runner or (lambda command, path: None)
        self.config = config
        self.report = VerificationReport()
        self.claims_found: list[str] = []
        self.shortcuts_found: list[str] = []

    def scan_claims(self, transcript: str):
        """
        Scan transcript for claims and shortcuts that need
        independent verification.

        Claims like "verified", "tests pass" need running.
        Shortcuts like "should be fine" need extra scrutiny.
        """
        # Find claims needing verification
        claim_patterns = [
            r"(?i)(?:verified?|tested?|confirmed?|checked?).*(?:works?|passes?|correct)",
            r"(?i)(?:all\s+)?(?:tests?\s+)?pass(?:ed)?",
            r"(?i)no\s+errors?",
            r"(?i)(?:success|fine|good)\s+(?:to\s+)?go",
        ]
        for pattern in claim_patterns:
            for match in re.finditer(pattern, transcript):
                self.claims_found.append(match.group())

        # Find shortcuts (rationalizations)
        shortcut_patterns = [
            r"(?i)(?:should\s+be\s+fine|probably|likely|maybe|i\s+think)",
            r"(?i)(?:trivial|simple|just|obviously)",
            r"(?i)(?:not\s+necessary|skip|skipping)",
        ]
        for pattern in shortcut_patterns:
            for match in re.finditer(pattern, transcript):
                self.shortcuts_found.append(match.group())

    def _result(self, name, command, output, passed, probe=False):
        if probe:
            kind = {"Boundary": ProbeType.BOUNDARY, "Idempotency": ProbeType.IDEMPOTENCY, "Concurrency": ProbeType.CONCURRENCY, "Orphan": ProbeType.ORPHAN}.get(name.split()[0], ProbeType.BOUNDARY)
            return ProbeResult(type=kind, name=name, command=command, output=output, passed=passed)
        return CheckResult(name=name, command=command, output=output, passed=passed)

    def _record(self, result, probe=False):
        (self.report.adversarial_probes if probe else self.report.checks).append(result)
        if result.passed is False:
            self.report.fail_reasons.append(result.name + ": observed failure")

    def verify_build(self):
        return self._run_command("Build", self._detect_build_command(), self.config.project_path)

    def verify_tests(self):
        return self._run_command("Test Suite", self._detect_test_command(), self.config.project_path)

    def verify_lint(self):
        return self._run_command("Lint", self._detect_linter_command(), self.config.project_path)


    def _unknown(self, name, command, reason, probe=False):
        self.report.partial_reasons.append(reason)
        result = self._result(name, command, reason, None, probe)
        self._record(result, probe)
        return result

    def _run_command(self, name, command, project_path):
        if not command:
            return self._unknown(name, "none detected", f"{name}: no configured command")
        try:
            result = self.command_runner(command, project_path)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return self._unknown(name, command, project_path + ": " + type(exc).__name__)
        if result is None:
            return self._unknown(name, command, "No isolated command runner configured")
        check = self._result(name, command, result.stdout + result.stderr, result.returncode == 0)
        self._record(check)
        return check

    def _invoke(self, target, params):
        if self.target_adapter is None:
            raise RuntimeError("No real target adapter configured")
        return self.target_adapter(target, params)

    def _probe(self, name, target, params, kind, calls=1, parallel=False):
        # Correctness belongs to a target-specific oracle, never response strings.
        if self.target_adapter is None or self.state_observer is None or self.probe_oracle is None:
            return self._unknown(name, target, "Probe requires a real adapter, independent state observer and oracle", True)
        try:
            before = self.state_observer()
            if parallel:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=calls) as pool:
                    results = list(pool.map(lambda _: self._invoke(target, params.copy()), range(calls)))
            else:
                results = [self._invoke(target, params.copy()) for _ in range(calls)]
            after = self.state_observer()
            passed = self.probe_oracle(kind, params, before, results, after)
            if passed is not True and passed is not False:
                return self._unknown(name, target, "Oracle did not provide a boolean verdict", True)
        except Exception as exc:
            return self._unknown(name, target, "Probe could not obtain evidence: " + type(exc).__name__, True)
        result = self._result(name, target, repr({"before": before, "results": results, "after": after}), passed, True)
        self._record(result, True)
        return result

    def adversarial_probe_boundary_values(self, func_or_endpoint, params, boundary_values=None):
        if not params:
            return [self._unknown("Boundary", func_or_endpoint, "No boundary parameter specified", True)]
        values = boundary_values if boundary_values is not None else [0, -1, "", "x" * 10000, 2**31 - 1]
        key = next(iter(params))
        return [self._probe("Boundary " + repr(value), func_or_endpoint, {**params, key: value}, "boundary") for value in values]

    def adversarial_probe_idempotency(self, func_or_endpoint, params):
        return [self._probe("Idempotency", func_or_endpoint, params, "idempotency", calls=2)]

    def adversarial_probe_concurrency(self, func_or_endpoint, params, num_parallel=5):
        if not 1 <= num_parallel <= 32:
            raise ValueError("Concurrency must be in [1, 32]")
        return [self._probe("Concurrency", func_or_endpoint, params, "concurrency", calls=num_parallel, parallel=True)]

    def adversarial_probe_orphan_operation(self, func_or_endpoint, params, non_existent_id=999999999):
        key = next((key for key in ("id", "entity_id", "resource_id", "item_id", "user_id") if key in params), "id")
        return self._probe("Orphan", func_or_endpoint, {**params, key: non_existent_id}, "orphan")

    def finalize(self):
        if not self.report.adversarial_probes:
            self.report.partial_reasons.append("No target-specific adversarial probes were run")
        self.report.final_verdict()
        return self.report
    def _detect_build_command(self) -> Optional[str]:
        """Detect build command from project files."""
        p = Path(self.config.project_path)
        candidates = [
            ("Makefile", "make"),
            ("CMakeLists.txt", "cmake . && make"),
            ("Cargo.toml", "cargo build"),
            ("pyproject.toml", "python -m build"),
            ("package.json", "npm run build"),
            ("setup.py", "python -m build"),
            ("build.gradle", "gradle build"),
            ("pom.xml", "mvn package"),
        ]
        for file, cmd in candidates:
            if (p / file).exists():
                return cmd
        return None

    def _detect_test_command(self) -> Optional[str]:
        """Detect test command from project files."""
        p = Path(self.config.project_path)
        candidates = [
            ("pytest.ini", "pytest -v"),
            ("pyproject.toml", "pytest -v"),
            ("package.json", "npm test"),
            ("Cargo.toml", "cargo test"),
            ("go.mod", "go test ./..."),
            ("pom.xml", "mvn test"),
        ]
        for file, cmd in candidates:
            if (p / file).exists():
                return cmd
        return None

    def _detect_linter_command(self) -> Optional[str]:
        """Detect linter from project files."""
        p = Path(self.config.project_path)
        candidates = [
            (".eslintrc", "npx eslint ."),
            (".pylintrc", "pylint ."),
            ("mypy.ini", "mypy ."),
            ("pyproject.toml", "ruff check ."),
            (".prettierrc", "prettier --check ."),
            (".ruff.toml", "ruff check ."),
        ]
        for file, cmd in candidates:
            if (p / file).exists():
                return cmd
        return None

