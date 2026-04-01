"""
VerifiAgent AttributionLedger — tracks verified contributions and pays out.

Based on DenialNet's attribution ledger pattern:
- All changes attributed to a session or user
- Attribution claims verified by VerificationSpecialist
- Revenue split 70/30 (contributor / VerifiAgent)
- Claims paid after verification report passes
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4
from enum import Enum
import json
from pathlib import Path


class ClaimStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    PAID = "paid"
    REJECTED = "rejected"


@dataclass
class AttributionClaim:
    contributor: str
    repo: str
    commit_sha: str
    amount_cents: int
    id: UUID = field(default_factory=uuid4)
    status: ClaimStatus = ClaimStatus.PENDING
    verification_report_id: Optional[UUID] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    verified_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    payout_transaction_id: Optional[str] = None


class AttributionLedger:
    """
    Tracks attribution claims and manages payouts.

    Usage:
        ledger = AttributionLedger(db_path="/path/to/ledger.json")
        ledger.add_claim(contributor="alice", repo="org/repo", amount_cents=75)
        claims = ledger.verify_claims([claim_id], report_id)
        ledger.mark_paid([claim_id], tx_id="stripe_pi_xxx")
    """

    def __init__(self, db_path: str = "~/.verifiagent/attribution_ledger.json"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_db()

    def _ensure_db(self):
        if not self.db_path.exists():
            self.db_path.write_text(json.dumps({"claims": [], "payouts": []}))

    def _read_db(self) -> dict:
        return json.loads(self.db_path.read_text())

    def _write_db(self, data: dict):
        self.db_path.write_text(json.dumps(data, indent=2, default=str))

    def add_claim(
        self,
        contributor: str,
        repo: str,
        commit_sha: str,
        amount_cents: int,
    ) -> AttributionClaim:
        """Add a new attribution claim."""
        claim = AttributionClaim(
            contributor=contributor,
            repo=repo,
            commit_sha=commit_sha,
            amount_cents=amount_cents,
        )
        data = self._read_db()
        data["claims"].append({
            "contributor": claim.contributor,
            "repo": claim.repo,
            "commit_sha": claim.commit_sha,
            "amount_cents": claim.amount_cents,
            "id": str(claim.id),
            "status": claim.status.value,
            "verification_report_id": None,
            "created_at": claim.created_at.isoformat(),
            "verified_at": None,
            "paid_at": None,
        })
        self._write_db(data)
        return claim

    def verify_claims(
        self,
        claim_ids: list[UUID],
        verification_report_id: UUID,
        verified: bool = True,
    ) -> list[AttributionClaim]:
        """Mark claims as verified (or rejected) by a verification report."""
        data = self._read_db()
        updated = []

        for claim_data in data["claims"]:
            if UUID(claim_data["id"]) in claim_ids:
                claim_data["status"] = ClaimStatus.VERIFIED.value if verified else ClaimStatus.REJECTED.value
                claim_data["verification_report_id"] = str(verification_report_id)
                claim_data["verified_at"] = datetime.utcnow().isoformat()
                updated.append(self._dict_to_claim(claim_data))

        self._write_db(data)
        return updated

    def mark_paid(
        self,
        claim_ids: list[UUID],
        payout_transaction_id: str,
    ) -> list[AttributionClaim]:
        """Mark verified claims as paid out."""
        data = self._read_db()
        updated = []

        for claim_data in data["claims"]:
            if UUID(claim_data["id"]) in claim_ids:
                if claim_data["status"] != ClaimStatus.VERIFIED.value:
                    continue  # Can only pay verified claims
                claim_data["status"] = ClaimStatus.PAID.value
                claim_data["paid_at"] = datetime.utcnow().isoformat()
                claim_data["payout_transaction_id"] = payout_transaction_id
                updated.append(self._dict_to_claim(claim_data))

        self._write_db(data)

        # Record payout
        payout_record = {
            "id": payout_transaction_id,
            "claim_ids": [str(c) for c in claim_ids],
            "total_cents": sum(c.amount_cents for c in updated),
            "paid_at": datetime.utcnow().isoformat(),
        }
        data["payouts"].append(payout_record)
        self._write_db(data)

        return updated

    def get_claims_by_repo(self, repo: str) -> list[AttributionClaim]:
        """Get all claims for a repository."""
        data = self._read_db()
        return [
            self._dict_to_claim(c)
            for c in data["claims"]
            if c["repo"] == repo
        ]

    def get_unpaid_verified(self) -> list[AttributionClaim]:
        """Get all verified but unpaid claims."""
        data = self._read_db()
        return [
            self._dict_to_claim(c)
            for c in data["claims"]
            if c["status"] == ClaimStatus.VERIFIED.value
        ]

    def calculate_payout(self, claim_ids: list[UUID]) -> dict:
        """Calculate payout amount for a set of claims (70/30 split)."""
        data = self._read_db()
        total = 0
        for claim_data in data["claims"]:
            if UUID(claim_data["id"]) in claim_ids and claim_data["status"] == ClaimStatus.VERIFIED.value:
                total += claim_data["amount_cents"]

        contributor_share = int(total * 0.70)
        platform_share = total - contributor_share

        return {
            "total_cents": total,
            "contributor_share_cents": contributor_share,
            "platform_share_cents": platform_share,
            "claim_count": len(claim_ids),
        }

    def _dict_to_claim(self, d: dict) -> AttributionClaim:
        """Convert dict back to AttributionClaim."""
        # Handle status enum
        if isinstance(d.get("status"), str):
            d["status"] = ClaimStatus(d["status"])
        d["id"] = UUID(d["id"])
        if d.get("verification_report_id"):
            d["verification_report_id"] = UUID(d["verification_report_id"])
        # Remove payout_transaction_id if None
        if d.get("payout_transaction_id") is None:
            pass  # Optional fields with None are fine
        return AttributionClaim(**d)
