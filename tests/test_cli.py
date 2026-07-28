from types import SimpleNamespace

import jarvis.interfaces.cli as cli


def test_show_status_reports_audit_metrics(capsys) -> None:
    class FakeProvider:
        def health_check(self):
            return SimpleNamespace(ok=True, latency_ms=12, message="ok")

    class FakeMemory:
        def latest_model_request(self):
            return {
                "status": "success",
                "latency_ms": 20,
                "input_tokens": 3,
                "output_tokens": 4,
            }

        def audit_metrics(self):
            return {
                "total": 5,
                "success_rate": 0.4,
                "timeout_rate": 0.2,
                "ambiguous_rate": 0.2,
                "user_rejection_rate": 0.2,
            }

    agent = SimpleNamespace(
        provider=FakeProvider(),
        history=[],
        memory=FakeMemory(),
    )
    settings = SimpleNamespace(
        model="fake-model",
        api_mode="chat_completions",
        base_url=None,
        request_timeout_seconds=60,
        max_retries=2,
        max_history_items=120,
    )

    cli._show_status(agent, settings)

    output = capsys.readouterr().out
    assert "工具审计：总数=5" in output
    assert "成功率=40%" in output
    assert "超时率=20%" in output
