"""Shared sensitive-content detection patterns.

Used by safety policy and audit redaction to avoid duplicating regex definitions.
"""
from __future__ import annotations

import re

# Patterns that detect sensitive payload content (passwords, API keys, card numbers, etc.)
SENSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)\b(?:password|passwd|api[_ -]?key|access[_ -]?token|secret|otp|2fa)"
        r"\s*[:=]\s*\S+"
    ),
    re.compile(r"(?:密码|验证码|支付口令)\s*[:：=]\s*\S+"),
    re.compile(r"(?<!\d)\d{13,19}(?!\d)"),
)

# Patterns for audit log redaction (capture groups preserve structure while hiding value)
AUDIT_REDACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)\b(password|passwd|api[_ -]?key|access[_ -]?token|secret|otp|2fa)"
        r"(\s*[:=]\s*)[^\s,\"}]+"
    ),
    re.compile(r"(密码|验证码|支付口令)(\s*[:：]\s*)[^\s,\"}]+"),
    re.compile(r"(?<!\d)\d{13,19}(?!\d)"),
)

_L3_TARGET_TERMS = (
    "发送", "提交", "发布", "上传", "删除", "移除", "确认订单", "购买",
    "send", "submit", "publish", "upload", "delete", "remove", "place order", "purchase",
)

_L4_TARGET_TERMS = (
    "密码", "支付", "付款", "银行卡", "信用卡", "验证码", "身份认证", "安全设置", "防火墙",
    "password", "passcode", "payment", "credit card", "verification code",
    "two-factor", "security settings", "firewall",
)


def contains_sensitive_text(value: str) -> bool:
    """Check if value contains sensitive patterns (passwords, card numbers, etc.)."""
    return any(pattern.search(value) for pattern in SENSITIVE_PATTERNS)


def redact_sensitive_text(value: str) -> str:
    """Redact sensitive values in text for audit logging."""
    redacted = value
    for pattern in AUDIT_REDACT_PATTERNS[:2]:
        redacted = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[已隐藏]", redacted)
    redacted = AUDIT_REDACT_PATTERNS[2].sub("[数字敏感内容已隐藏]", redacted)
    return redacted


def redact_jsonable(value: object) -> object:
    """Recursively redact sensitive strings in a JSON-serializable structure."""
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {str(key): redact_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [redact_jsonable(item) for item in value]
    return value


def contains_term(value: str, terms: tuple[str, ...]) -> bool:
    """Check if value contains any of the given terms (word-boundary aware for ASCII)."""
    normalized = value.casefold()
    for term in terms:
        candidate = term.casefold()
        if candidate.isascii():
            pattern = rf"(?<![a-z0-9]){re.escape(candidate)}(?![a-z0-9])"
            if re.search(pattern, normalized):
                return True
        elif candidate in normalized:
            return True
    return False


def get_l3_target_terms() -> tuple[str, ...]:
    return _L3_TARGET_TERMS


def get_l4_target_terms() -> tuple[str, ...]:
    return _L4_TARGET_TERMS
