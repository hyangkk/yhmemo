"""
Security utilities for the agent system.

Guards for the Claude Code CLI dev-runner:
  - prompt sanitization (length limit + blocked patterns)
  - working-directory validation
"""

import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blocked patterns -- case-insensitive substring match
# ---------------------------------------------------------------------------
BLOCKED_PATTERNS = [
    "rm -rf /", "sudo ", "chmod 777", "curl | bash",
    "wget | sh", "eval(", "exec(", "__import__",
    "os.system", "subprocess.call", "DROP TABLE",
    "DELETE FROM", "; rm ", "&&rm ", "| rm ",
]


def sanitize_dev_prompt(
    prompt: str,
    max_length: int = 10_000,
    blocked: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Sanitize a dev prompt before passing it to Claude Code CLI.

    Returns
    -------
    (clean_prompt, warnings)
        *clean_prompt* is the (possibly truncated) safe prompt, or an empty
        string if the prompt was rejected.
        *warnings* lists any issues found.
    """
    if blocked is None:
        blocked = BLOCKED_PATTERNS

    warnings: list[str] = []

    # 1. Length limit
    if len(prompt) > max_length:
        prompt = prompt[:max_length]
        warnings.append(f"Prompt truncated to {max_length} chars")

    # 2. Blocked-pattern check (case-insensitive)
    prompt_lower = prompt.lower()
    for pattern in blocked:
        if pattern.lower() in prompt_lower:
            warnings.append(f"Blocked pattern detected: {pattern}")
            logger.warning(
                "[security] Prompt REJECTED -- blocked pattern '%s' found",
                pattern,
            )
            return "", warnings  # reject entirely

    return prompt, warnings


def validate_cwd(
    cwd: str,
    allowed_base: str = "/home/user/yhmemo",
) -> bool:
    """Return True if *cwd* is inside *allowed_base* (symlink-safe)."""
    real_cwd = os.path.realpath(cwd)
    real_base = os.path.realpath(allowed_base)
    return real_cwd == real_base or real_cwd.startswith(real_base + os.sep)
