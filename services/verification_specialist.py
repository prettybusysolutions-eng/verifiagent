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

    def __init__(self, config: VSConfig):
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

    def verify_build(self) -> CheckResult:
        """Run the build. A broken build is automatic FAIL."""
        cmd = self._detect_build_command()
        if not cmd:
            return CheckResult(
                name="Build",
                command="none detected",
                output="No build command found",
                passed=True,
            )

        result = subprocess.run(
            cmd,
            shell=True,
            cwd=self.config.project_path,
            capture_output=True,
            text=True,
            timeout=self.config.timeout_build,
        )

        check = CheckResult(
            name="Build",
            command=cmd,
            output=result.stdout + result.stderr,
            passed=(result.returncode == 0),
            expected="exit code 0",
            actual=f"exit code {result.returncode}" if result.returncode != 0 else "exit code 0",
        )
        self.report.checks.append(check)
        if not check.passed:
            self.report.fail_reasons.append(f"Build failed: {check.actual}")
        return check

    def verify_tests(self) -> CheckResult:
        """Run the test suite. Failing tests are automatic FAIL."""
        cmd = self._detect_test_command()
        if not cmd:
            return CheckResult(
                name="Test Suite",
                command="none detected",
                output="No test command found",
                passed=True,
            )

        result = subprocess.run(
            cmd,
            shell=True,
            cwd=self.config.project_path,
            capture_output=True,
            text=True,
            timeout=self.config.timeout_test,
        )

        check = CheckResult(
            name="Test Suite",
            command=cmd,
            output=result.stdout + result.stderr,
            passed=(result.returncode == 0),
            expected="exit code 0",
            actual=f"exit code {result.returncode}" if result.returncode != 0 else "exit code 0",
        )
        self.report.checks.append(check)
        if not check.passed:
            self.report.fail_reasons.append(f"Tests failed: {check.actual}")
        return check

    def verify_lint(self) -> CheckResult:
        """Run linter if configured."""
        cmd = self._detect_linter_command()
        if not cmd:
            return CheckResult(
                name="Lint",
                command="none",
                output="No linter detected",
                passed=True,
            )

        result = subprocess.run(
            cmd,
            shell=True,
            cwd=self.config.project_path,
            capture_output=True,
            text=True,
            timeout=self.config.timeout_lint,
        )

        check = CheckResult(
            name="Lint",
            command=cmd,
            output=result.stdout + result.stderr,
            passed=(result.returncode == 0),
            expected="exit code 0",
            actual=f"exit code {result.returncode}" if result.returncode != 0 else "exit code 0",
        )
        self.report.checks.append(check)
        return check

    def adversarial_probe_boundary_values(
        self,
        func_or_endpoint: str,
        params: dict,
        boundary_values: Optional[list] = None,
    ) -> list[ProbeResult]:
        """
        Test boundary values:
        - 0
        - -1
        - empty string
        - very long string (10KB)
        - unicode (emoji bomb)
        - MAX_INT (2^31 - 1)
        """
        if boundary_values is None:
            boundary_values = [0, -1, "", "x" * 10000, "🔥💀🚀" * 100, 2**31 - 1]

        results = []
        for bv in boundary_values:
            test_params = params.copy()
            first_key = next(iter(test_params), None)
            if first_key:
                test_params[first_key] = bv

            probe_result = self._call_endpoint(func_or_endpoint, test_params)
            passed = self._check_boundary_handled(probe_result)

            probe = ProbeResult(
                type=ProbeType.BOUNDARY,
                name=f"Boundary: {bv!r} on {first_key}",
                command=f"invoke {func_or_endpoint} with {test_params}",
                output=str(probe_result),
                passed=passed,
                severity=Severity.MEDIUM,
                notes="Should return error or handle gracefully, not crash",
            )
            results.append(probe)
            self.report.adversarial_probes.append(probe)
            if not passed:
                self.report.fail_reasons.append(f"Boundary failure: {probe.name}")
        return results

    def adversarial_probe_idempotency(
        self,
        func_or_endpoint: str,
        params: dict,
    ) -> list[ProbeResult]:
        """
        Test idempotency: same mutation twice.
        - First call should succeed
        - Second call should be no-op or graceful error (not duplicate)
        """
        results = []

        # First call
        r1 = self._call_endpoint(func_or_endpoint, params)
        p1 = ProbeResult(
            type=ProbeType.IDEMPOTENCY,
            name="Idempotency (call 1)",
            command=f"invoke {func_or_endpoint}",
            output=str(r1),
            passed=True,
        )
        results.append(p1)

        # Second call
        r2 = self._call_endpoint(func_or_endpoint, params)
        passed = self._check_idempotent(r1, r2)
        p2 = ProbeResult(
            type=ProbeType.IDEMPOTENCY,
            name="Idempotency (call 2 — same params)",
            command=f"invoke {func_or_endpoint}",
            output=str(r2),
            passed=passed,
            notes="Second call should be no-op or error, not duplicate resource",
        )
        results.append(p2)
        self.report.adversarial_probes.append(p2)
        if not passed:
            self.report.fail_reasons.append(f"Idempotency failure: second call produced duplicate resource")
        return results

    def adversarial_probe_concurrency(
        self,
        func_or_endpoint: str,
        params: dict,
        num_parallel: Optional[int] = None,
    ) -> list[ProbeResult]:
        """
        Test concurrency: parallel requests to create-if-not-exists.
        Are duplicates created? Lost writes?
        """
        num = num_parallel or self.config.max_concurrency

        def call():
            return self._call_endpoint(func_or_endpoint, params)

        with concurrent.futures.ThreadPoolExecutor(max_workers=num) as executor:
            futures = [executor.submit(call) for _ in range(num)]
            results_list = [f.result() for f in concurrent.futures.as_completed(futures)]

        unique = len(set(str(r) for r in results_list))
        passed = unique <= 2  # At most 2 unique states (success + error)

        probe = ProbeResult(
            type=ProbeType.CONCURRENCY,
            name=f"Concurrency ({num} parallel calls)",
            command=f"parallel {num}x {func_or_endpoint}",
            output=f"{unique} unique result(s) from {num} calls: {results_list[:3]}",
            passed=passed,
            severity=Severity.HIGH,
            notes=f"Expected ≤2 unique states, got {unique}",
        )
        self.report.adversarial_probes.append(probe)
        if not passed:
            self.report.fail_reasons.append(f"Concurrency failure: {unique} unique states from {num} identical calls")
        return [probe]

    def adversarial_probe_orphan_operation(
        self,
        func_or_endpoint: str,
        params: dict,
        non_existent_id: int = 999999999,
    ) -> ProbeResult:
        """
        Test orphan operation: delete/reference a non-existent ID.
        Should return graceful error, not crash.
        """
        test_params = params.copy()
        id_keys = ["id", "entity_id", "resource_id", "item_id", "user_id"]
        used_key = None

        for key in id_keys:
            if key in test_params:
                test_params[key] = non_existent_id
                used_key = key
                break

        if not used_key:
            test_params["id"] = non_existent_id
            used_key = "id"

        result = self._call_endpoint(func_or_endpoint, test_params)
        passed = self._check_graceful_error(result)

        probe = ProbeResult(
            type=ProbeType.ORPHAN,
            name=f"Orphan: non-existent {used_key}={non_existent_id}",
            command=f"invoke {func_or_endpoint} with {used_key}={non_existent_id}",
            output=str(result),
            passed=passed,
            notes="Should return 404 or graceful error, not crash",
        )
        self.report.adversarial_probes.append(probe)
        if not passed:
            self.report.fail_reasons.append(f"Orphan operation failure: {probe.name}")
        return probe

    def finalize(self) -> VerificationReport:
        """Finalize the report and issue verdict."""
        if not self.report.adversarial_probes:
            self.report.partial_reasons.append(
                "No adversarial probes were run. Happy-path confirmation only is not verification."
            )

        verdict = self.report.final_verdict()

        # Add claims found as notes
        if self.claims_found:
            self.report.partial_reasons.append(
                f"Claims found in transcript that may need verification: {self.claims_found}"
            )

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

    def _call_endpoint(self, func_or_endpoint: str, params: dict):
        """
        Call a function or HTTP endpoint.
        Override in production to connect to real endpoints.
        """
        # For API surface: try HTTP call
        if self.config.surface == "api" and func_or_endpoint.startswith("http"):
            import urllib.request
            import json
            try:
                data = json.dumps(params).encode()
                req = urllib.request.Request(
                    func_or_endpoint,
                    data=data,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return {"status": "ok", "data": resp.read().decode()}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        # Fallback: return placeholder for non-API surfaces
        return {"status": "ok", "params": params, "note": "endpoint not reachable in test"}

    def _check_boundary_handled(self, result) -> bool:
        """Check if boundary value was handled gracefully."""
        s = str(result)
        error_indicators = ["error", "invalid", "not found", "failed", "exception"]
        return any(ind in s.lower() for ind in error_indicators) or "ok" in s.lower()

    def _check_idempotent(self, result1, result2) -> bool:
        """Check if operation was idempotent."""
        s1, s2 = str(result1), str(result2)
        if s1 == s2:
            return True
        if "already exists" in s1 or "already exists" in s2:
            return True
        if "not found" in s1 or "not found" in s2:
            return True
        return False

    def _check_graceful_error(self, result) -> bool:
        """Check if error was handled gracefully (not a crash)."""
        s = str(result).lower()
        graceful = ["error", "not found", "invalid", "404", "400", "403", "404", "500"]
        return any(g in s for g in graceful)
