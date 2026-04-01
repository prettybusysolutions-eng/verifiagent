"""
VerifiAgent SecurityMonitor — pre-action immune system.

Built from: Piebald-AI/claude-code-system-prompts
  - agent-prompt-security-monitor-for-autonomous-agent-actions-first-part.md
  - agent-prompt-security-monitor-for-autonomous-agent-actions-second-part.md

Evaluates actions against BLOCK/ALLOW rules. Default is ALLOW — only
block if a BLOCK condition matches with no ALLOW exception.
"""

from dataclasses import dataclass, field
from typing import Optional
from models.verification import SecurityBlock, Severity
import re


@dataclass
class SecurityDecision:
    should_block: bool = False
    reason: Optional[str] = None
    block_condition: Optional[str] = None
    allow_exception: Optional[str] = None


BLOCK_CONDITIONS = [
    {
        "name": "git_destructive",
        "pattern": r"git\s+push\s+--force|git\s+push\s+-f|git\s+push\s+.*--delete",
        "description": "Force pushing or rewriting remote history",
        "severity": Severity.HIGH,
    },
    {
        "name": "git_push_default",
        "pattern": r"git\s+push.*(?:main|master|default)|origin\s+.*(?:main|master|default)\s*$",
        "description": "Pushing directly to default branch bypasses PR review",
        "severity": Severity.MEDIUM,
    },
    {
        "name": "production_deploy",
        "pattern": r"--production|--prod|\bdeploy\b.*\bproduction\b|render.*production",
        "description": "Deploying to production without verification",
        "severity": Severity.HIGH,
    },
    {
        "name": "blind_apply",
        "pattern": r"--yes|--auto-approve|--force|--no-verify|\b-y\b",
        "description": "Bypassing preview/dry-run step",
        "severity": Severity.MEDIUM,
    },
    {
        "name": "credential_embed",
        "pattern": r"(?:api[_-]?key|password|secret|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
        "description": "Embedding secrets in code or configs",
        "severity": Severity.HIGH,
    },
    {
        "name": "data_exfil",
        "pattern": r"curl\s+.*--data(?:=|-binary).*\$|curl\s+.*\|-?\s*bash",
        "description": "Sending data to external endpoints or piping to shell",
        "severity": Severity.HIGH,
    },
    {
        "name": "destructive_local",
        "pattern": r"rm\s+(-rf|-fr)|git\s+clean\s+-fdx|git\s+reset\s+--hard",
        "description": "Irreversible deletion of local files",
        "severity": Severity.HIGH,
    },
    {
        "name": "external_code",
        "pattern": r"curl\s+\|\s*bash|\|\s*sh\b|wget\s+.*\|\s*sh|eval\s*\(",
        "description": "Downloading and executing code from external sources",
        "severity": Severity.HIGH,
    },
    {
        "name": "permission_elevation",
        "pattern": r"chmod\s+777|sudo\s+|grant.*(?:admin|owner|role)",
        "description": "Granting elevated permissions",
        "severity": Severity.HIGH,
    },
    {
        "name": "shared_resource",
        "pattern": r"kubectl\s+delete|docker\s+rm\s+[^-]|pkill\s+-9|kill\s+-9\s+\$\$",
        "description": "Modifying or deleting shared infrastructure",
        "severity": Severity.HIGH,
    },
    {
        "name": "unauthorized_persistence",
        "pattern": r"(?:ssh[_-]?key|cron|crontab|\.bashrc|\.profile).*\(add\|create\|insert\)",
        "description": "Adding persistent access mechanisms",
        "severity": Severity.HIGH,
    },
    {
        "name": "self_modification",
        "pattern": r"(?:settings\.json|CLAUDE\.md|\.claude/).*(?:edit|write|modify)",
        "description": "Modifying agent own configuration",
        "severity": Severity.MEDIUM,
    },
    {
        "name": "scope_escalation",
        "pattern": r"delete.*(?:cluster|namespace|repo|production|shared)|rm\s+.*\.\./",
        "description": "Action suggests scope beyond original task",
        "severity": Severity.MEDIUM,
    },
    {
        "name": "real_world_transaction",
        "pattern": r"\b(?:buy|purchase|charge|payment|send\s+\$|wire)\b.*(?:real|production)",
        "description": "Real-world financial transaction",
        "severity": Severity.HIGH,
    },
]

ALLOW_EXCEPTIONS = [
    {
        "name": "test_artifacts",
        "pattern": r"(?:test|spec|mock|fixture).*(?:key|token|credential)",
        "description": "Test-only credentials in test files",
    },
    {
        "name": "local_operations",
        "pattern": r"(?:rm|del)\s+.*(?:node_modules|\.git|\.venv|venv|dist|build|tmp|temp|__pycache__)",
        "description": "Cleaning local generated directories only",
    },
    {
        "name": "declared_deps",
        "pattern": r"(?:pip\s+install\s+-r|npm\s+install(?!\s+-[a-z])|bundle\s+install|cargo\s+build)",
        "description": "Installing from project's declared manifest",
    },
    {
        "name": "working_branch",
        "pattern": r"git\s+push\s+.*(?:\bfix\b|\bfeat\b|\bfeature\b|\bchore\b|\btest\b|\bdocs\b|\brefactor\b|\bverify\b)",
        "description": "Pushing to a non-default feature branch",
    },
    {
        "name": "read_only",
        "pattern": r"\bcurl\s+-s\s+-O|\bcurl\s+.*\bGET\b|\bcurl\s+.*--head\b",
        "description": "Read-only HTTP requests only",
    },
    {
        "name": "git_clean_new",
        "pattern": r"git\s+clean\s+-fd\s+&&|git\s+checkout\s+\.",
        "description": "Cleaning untracked files created during session",
    },
]


class SecurityMonitor:
    """
    Pre-action security guard for VerifiAgent.

    Evaluates git diffs, shell commands, and file operations against
    BLOCK/ALLOW rules. Default is ALLOW — only block if a BLOCK
    condition matches with no ALLOW exception.

    Usage:
        monitor = SecurityMonitor()
        blocks = monitor.evaluate_diff(diff_text)
        if blocks:
            print(f"BLOCKED: {blocks[0].reason}")
    """

    def __init__(self):
        self.blocks_found: list[SecurityBlock] = []

    def evaluate_diff(self, diff_text: str) -> list[SecurityBlock]:
        """
        Evaluate a git diff for security issues.

        Args:
            diff_text: The full git diff output

        Returns:
            List of SecurityBlock objects (empty if nothing blocked)
        """
        self.blocks_found = []
        lines = diff_text.split("\n")
        file_context: list[str] = []

        for line in lines:
            # Track file context
            if line.startswith("diff --git"):
                file_context = [line]
            elif line.startswith("+++"):
                file_context.append(line)
            elif line.startswith("@@"):
                file_context.append(line)
            else:
                file_context.append(line)

            context_str = "\n".join(file_context[-10:])

            # Check each BLOCK condition
            for condition in BLOCK_CONDITIONS:
                pattern = condition["pattern"]
                # Only check additions and certain commands
                if line.startswith("+") or line.startswith("-"):
                    if re.search(pattern, line, re.IGNORECASE):
                        # Check for ALLOW exceptions
                        exception_found = None
                        for exception in ALLOW_EXCEPTIONS:
                            if re.search(exception["pattern"], line, re.IGNORECASE):
                                exception_found = exception["name"]
                                break

                        block = SecurityBlock(
                            condition=condition["name"],
                            reason=f"BLOCK: {condition['description']} (severity: {condition['severity'].value})",
                            severity=condition["severity"],
                            allowed=(exception_found is not None),
                            exception=exception_found,
                        )
                        self.blocks_found.append(block)

        return self.blocks_found

    def evaluate_command(self, command: str) -> SecurityDecision:
        """
        Evaluate a single shell command.

        Args:
            command: The shell command to evaluate

        Returns:
            SecurityDecision with should_block and reason
        """
        for condition in BLOCK_CONDITIONS:
            pattern = condition["pattern"]
            if re.search(pattern, command, re.IGNORECASE):
                # Check for ALLOW exceptions
                for exception in ALLOW_EXCEPTIONS:
                    if re.search(exception["pattern"], command, re.IGNORECASE):
                        return SecurityDecision(
                            should_block=False,
                            allow_exception=f"{exception['name']}: {exception['description']}",
                        )
                return SecurityDecision(
                    should_block=True,
                    reason=f"BLOCK: {condition['description']}",
                    block_condition=condition["name"],
                )
        return SecurityDecision(should_block=False)

    def evaluate_batch(self, items: list[str]) -> list[SecurityDecision]:
        """Evaluate multiple items."""
        return [self.evaluate_command(item) for item in items]

    def summary(self, decisions: list[SecurityDecision]) -> dict:
        """Summarize a batch of decisions."""
        blocked = [d for d in decisions if d.should_block]
        return {
            "total": len(decisions),
            "allowed": len(decisions) - len(blocked),
            "blocked": len(blocked),
            "block_reasons": [d.reason for d in blocked if d.reason],
        }
