"""Memory save policy: sensitive content detection and type-based rules."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from jarvis.sensitive import contains_payment_info, contains_secret

__all__ = [
    "SaveDecision",
    "PolicyResult",
    "check_memory_save",
    "contains_secret",
    "contains_payment_info",
]


class SaveDecision(str, Enum):
    ALLOW = "allow"
    REJECT = "reject"
    DOWNGRADE = "downgrade"


@dataclass(frozen=True, slots=True)
class PolicyResult:
    decision: SaveDecision
    adjusted_confidence: float
    reason: str


def check_memory_save(
    *,
    title: str,
    content: str,
    memory_type: str,
    confidence: float,
) -> PolicyResult:
    """Evaluate whether a memory should be saved, rejected, or downgraded."""
    combined = f"{title} {content}"

    # Hard reject: secrets
    if contains_secret(combined):
        return PolicyResult(
            decision=SaveDecision.REJECT,
            adjusted_confidence=0.0,
            reason="内容包含密码、密钥、令牌或其他认证秘密，拒绝保存。",
        )

    # Hard reject: payment info
    if contains_payment_info(combined):
        return PolicyResult(
            decision=SaveDecision.REJECT,
            adjusted_confidence=0.0,
            reason="内容包含支付或金融信息，拒绝保存。",
        )

    # Downgrade low-confidence inference
    if confidence < 0.5:
        return PolicyResult(
            decision=SaveDecision.DOWNGRADE,
            adjusted_confidence=max(confidence, 0.3),
            reason=f"置信度 {confidence:.2f} 过低，已降级保存。",
        )

    return PolicyResult(
        decision=SaveDecision.ALLOW,
        adjusted_confidence=confidence,
        reason="",
    )
