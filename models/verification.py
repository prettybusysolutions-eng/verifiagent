"""
VerifiAgent data models.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4


class VerdictType(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"


class Severity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ProbeType(str, Enum):
    BOUNDARY = "boundary"
    IDEMPOTENCY = "idempotency"
    CONCURRENCY = "concurrency"
    ORPHAN = "orphan"


class SecurityBlock(BaseModel):
    condition: str
    reason: str
    severity: Severity
    allowed: bool = False
    exception: Optional[str] = None


class CheckResult(BaseModel):
    name: str
    command: str
    output: str = ""
    passed: Optional[bool] = None
    expected: Optional[str] = None
    actual: Optional[str] = None
    notes: Optional[str] = None


class ProbeResult(BaseModel):
    type: ProbeType
    name: str
    command: str
    output: str = ""
    passed: Optional[bool] = None
    severity: Severity = Severity.MEDIUM
    notes: Optional[str] = None


class Evidence(BaseModel):
    type: str  # screenshot, output, log
    path: str
    description: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AttributionClaim(BaseModel):
    contributor: str
    amount_cents: int
    verified: bool = False
    verification_report_id: UUID
    paid: bool = False


class VerificationReport(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    pr_url: Optional[str] = None
    commit_sha: Optional[str] = None
    repo: Optional[str] = None
    verdict: VerdictType = VerdictType.PARTIAL
    security_blocks: list[SecurityBlock] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    adversarial_probes: list[ProbeResult] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    duration_ms: int = 0
    session_id: str = ""
    attribution_claims: list[AttributionClaim] = Field(default_factory=list)
    summary: str = ""
    fail_reasons: list[str] = Field(default_factory=list)
    partial_reasons: list[str] = Field(default_factory=list)

    def final_verdict(self) -> VerdictType:
        if self.fail_reasons or any(c.passed is False for c in self.checks + self.adversarial_probes):
            self.verdict = VerdictType.FAIL
            self.summary = f"FAIL — {len(self.fail_reasons)} issue(s)"
        elif self.partial_reasons or any(c.passed is None for c in self.checks + self.adversarial_probes) or not (self.checks or self.adversarial_probes):
            self.verdict = VerdictType.PARTIAL
            self.summary = "PARTIAL — incomplete or unavailable verification evidence"
        else:
            self.verdict = VerdictType.PASS
            self.summary = f"PASS — {len(self.checks)} checks, {len(self.adversarial_probes)} adversarial probes"
        return self.verdict


class VerificationRequest(BaseModel):
    repo_url: str
    commit_sha: str
    base_sha: Optional[str] = None
    diff: Optional[str] = Field(default=None, max_length=1048576)
    pr_url: Optional[str] = None
    language: Optional[str] = "python"
    surface: Optional[str] = None  # api, cli, gui, library


class WebhookPayload(BaseModel):
    action: str
    pull_request: Optional[dict] = None
    repository: Optional[dict] = None
    installation_id: Optional[int] = None

