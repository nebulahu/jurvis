"""Shared sensitive-content detection patterns.

Used by safety policy, memory policy, and audit redaction to avoid duplicating
regex definitions across the codebase.
"""
from __future__ import annotations

import re

# --- Secret detection (passwords, API keys, tokens, JWT, etc.) ---

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
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
    # Long digit sequences (card numbers, IDs)
    re.compile(r"(?<!\d)\d{13,19}(?!\d)"),
    # Bearer tokens and JWT
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_.]+"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
)

# --- Payment / financial information detection ---

PAYMENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:支付宝|微信支付|paypal|stripe|alipay|wechat\s*pay).*\d"),
    re.compile(r"(?:付款|转账|汇款|打款).*\d{3,}"),
)

# --- Patterns for audit log redaction (capture groups hide value, preserve key) ---

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


def contains_secret(text: str) -> bool:
    """Check if text contains secrets, passwords, API keys, or auth tokens."""
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def contains_payment_info(text: str) -> bool:
    """Check if text contains payment or financial information."""
    return any(pattern.search(text) for pattern in PAYMENT_PATTERNS)


# Backward-compatible alias (used by safety.py and desktop adapter)
contains_sensitive_text = contains_secret


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
