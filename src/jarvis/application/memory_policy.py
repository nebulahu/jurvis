"""Memory save policy: sensitive content detection and type-based rules."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # English key=value patterns
    re.compile(
        r"(?i)\b(?:password|passwd|api[_ -]?key|access[_ -]?token|secret[_ -]?key|"
        r"auth[_ -]?token|bearer|otp|2fa[_ -]?code|private[_ -]?key|"
        r"credit[_ -]?card|card[_ -]?number|cvv|ssn)"
        r"\s*[:=]\s*\S+"
    ),
    # Chinese patterns
    re.compile(
        r"(密码|口令|验证码|支付密码|银行卡号|身份证号|社保号|密钥|私钥)"
        r"\s*[:：=]\s*\S+"
    ),
    # Long digit sequences that look like card numbers or IDs
    re.compile(r"(?<!\d)\d{13,19}(?!\d)"),
    # Bearer tokens and JWT
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_.]+"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
)

_PAYMENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:支付宝|微信支付|paypal|stripe|alipay|wechat\s*pay).*\d"),
    re.compile(r"(?:付款|转账|汇款|打款).*\d{3,}"),
)


class SaveDecision(str, Enum):
    ALLOW = "allow"
    REJECT = "reject"
    DOWNGRADE = "downgrade"


@dataclass(frozen=True, slots=True)
class PolicyResult:
    decision: SaveDecision
    adjusted_confidence: float
    reason: str


def contains_secret(text: str) -> bool:
    """Check if text contains secrets, passwords, API keys, or auth tokens."""
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def contains_payment_info(text: str) -> bool:
    """Check if text contains payment or financial information."""
    return any(pattern.search(text) for pattern in _PAYMENT_PATTERNS)


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
