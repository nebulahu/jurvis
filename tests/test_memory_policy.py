"""Tests for memory save policy and sensitive content detection."""
from __future__ import annotations

from pathlib import Path

from jarvis.ports.memory_policy import (
    SaveDecision,
    check_memory_save,
    contains_payment_info,
    contains_secret,
)
from jarvis.adapters.storage.sqlite import SQLiteStore


def test_contains_secret_detects_password() -> None:
    assert contains_secret("password=hunter2")
    assert contains_secret("密码：abc123")
    assert contains_secret("api_key: sk-1234567890")


def test_contains_secret_detects_bearer_token() -> None:
    assert contains_secret("Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc")
    assert contains_secret("bearer abcdefghijklmnop")


def test_contains_secret_detects_card_number() -> None:
    assert contains_secret("卡号 6222021234567890123")


def test_contains_secret_clean_text() -> None:
    assert not contains_secret("今天天气不错")
    assert not contains_secret("用户喜欢深色主题")


def test_contains_payment_info_detects() -> None:
    assert contains_payment_info("支付宝转账 50000")
    assert contains_payment_info("付款 12345 元")


def test_contains_payment_info_clean() -> None:
    assert not contains_payment_info("用户偏好简洁界面")


def test_check_memory_save_rejects_secret() -> None:
    result = check_memory_save(
        title="密码记录",
        content="password=abc123",
        memory_type="fact",
        confidence=1.0,
    )
    assert result.decision == SaveDecision.REJECT
    assert "秘密" in result.reason


def test_check_memory_save_rejects_payment() -> None:
    result = check_memory_save(
        title="支付",
        content="支付宝转账 99999",
        memory_type="fact",
        confidence=1.0,
    )
    assert result.decision == SaveDecision.REJECT
    assert "支付" in result.reason


def test_check_memory_save_downgrades_low_confidence() -> None:
    result = check_memory_save(
        title="推测",
        content="用户可能喜欢咖啡",
        memory_type="fact",
        confidence=0.3,
    )
    assert result.decision == SaveDecision.DOWNGRADE
    assert result.adjusted_confidence == 0.3


def test_check_memory_save_allows_normal() -> None:
    result = check_memory_save(
        title="偏好",
        content="用户喜欢深色主题",
        memory_type="preference",
        confidence=0.8,
    )
    assert result.decision == SaveDecision.ALLOW
    assert result.adjusted_confidence == 0.8


def test_sqlite_remember_rejects_secret(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "jarvis.db")
    try:
        store.remember("密码", "api_key=sk-1234567890", "项目")
        assert False, "should have raised"
    except ValueError as exc:
        assert "秘密" in str(exc)


def test_sqlite_save_summary_rejects_secret(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "jarvis.db")
    try:
        store.save_summary(
            conversation_start="2026-07-29T10:00:00+08:00",
            conversation_end="2026-07-29T10:30:00+08:00",
            summary_text="用户密码 password=hunter2",
        )
        assert False, "should have raised"
    except ValueError as exc:
        assert "秘密" in str(exc)
