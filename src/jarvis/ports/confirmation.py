from __future__ import annotations

from typing import Protocol


class ConfirmationPort(Protocol):
    def confirm(
        self,
        tool_name: str,
        risk_level: int,
        arguments: dict[str, object],
    ) -> bool: ...
