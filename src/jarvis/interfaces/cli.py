from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Callable

from jarvis.adapters.audio.voice import StreamingSpeechPlayer, build_voice_runtime
from jarvis.adapters.audio.wake import WakeCancelled, build_wake_runtime
from jarvis.application.assistant import JarvisAgent
from jarvis.application.voice_session import VoiceSession
from jarvis.bootstrap import build_agent
from jarvis.config import Settings
from jarvis.ports.audio import VoiceError
from jarvis.safety import RiskLevel


def _confirm(tool_name: str, risk: RiskLevel, arguments: dict[str, object]) -> bool:
    print(f"\n[需要确认] {tool_name}（L{int(risk)}）")
    print(json.dumps(arguments, ensure_ascii=False, indent=2))
    while True:
        answer = input("允许执行？[y/N] ").strip().lower()
        if answer in {"y", "yes", "是"}:
            return True
        if answer in {"", "n", "no", "否"}:
            return False
        print("请输入 y 或 n。")


def _show_status(agent: JarvisAgent, settings: Settings) -> None:
    print("正在检查模型服务……")
    status = agent.provider.health_check()
    print(f"服务：{'正常' if status.ok else '异常'}（{status.latency_ms} ms）")
    print(f"模型：{settings.model}")
    print(f"接口：{settings.api_mode}")
    print(f"地址：{settings.base_url or 'SDK 默认地址'}")
    print(f"超时/重试：{settings.request_timeout_seconds:g}s / {settings.max_retries} 次")
    print(f"上下文项：{len(agent.history)} / {settings.max_history_items}")
    print(f"详情：{status.message}")
    latest = agent.memory.latest_model_request()
    if latest:
        print(
            "最近请求："
            f"{latest['status']}，{latest['latency_ms']} ms，"
            f"输入/输出 Token={latest['input_tokens']}/{latest['output_tokens']}"
        )
    audit_metrics = agent.memory.audit_metrics()
    if audit_metrics["total"]:
        print(
            "工具审计："
            f"总数={audit_metrics['total']}，"
            f"成功率={audit_metrics['success_rate']:.0%}，"
            f"超时率={audit_metrics['timeout_rate']:.0%}，"
            f"歧义率={audit_metrics['ambiguous_rate']:.0%}，"
            f"拒绝率={audit_metrics['user_rejection_rate']:.0%}"
        )


def _chat_with_stream(
    agent: JarvisAgent,
    assistant_name: str,
    text: str,
    on_text_delta: Callable[[str], None] | None = None,
) -> str:
    started = False

    def write_delta(delta: str) -> None:
        nonlocal started
        if not started:
            print(f"\n{assistant_name}> ", end="", flush=True)
            started = True
        print(delta, end="", flush=True)
        if on_text_delta is not None:
            on_text_delta(delta)

    try:
        answer = agent.chat(text, on_text_delta=write_delta)
        if started:
            print()
        else:
            print(f"\n{assistant_name}> {answer}")
        return answer
    except Exception:
        if started:
            print()
        raise


def _wait_for_recording_stop(limit_reached) -> bool:
    """Return True when recording stopped because its configured limit was reached."""
    if sys.platform != "win32":
        input()
        return False
    import msvcrt

    while not limit_reached.wait(0.05):
        while msvcrt.kbhit():
            if msvcrt.getwch() in {"\r", "\n"}:
                return False
        time.sleep(0.01)
    return True


def _watch_for_speech_interrupt(
    stop_event: threading.Event,
    on_interrupt: Callable[[], None],
) -> None:
    if sys.platform != "win32":
        return
    import msvcrt

    while not stop_event.wait(0.05):
        while msvcrt.kbhit():
            if msvcrt.getwch() == "\x1b":
                on_interrupt()
                return


def _console_escape_pressed() -> bool:
    if sys.platform != "win32":
        return False
    import msvcrt

    pressed = False
    while msvcrt.kbhit():
        if msvcrt.getwch() == "\x1b":
            pressed = True
    return pressed


def _run_voice_response(
    agent: JarvisAgent,
    settings: Settings,
    session: VoiceSession,
    transcript: str,
    speaker,
) -> None:
    print("[思考中]", flush=True)
    if not settings.tts_enabled:
        _chat_with_stream(agent, settings.assistant_name, transcript)
        session.complete_turn()
        return

    player = StreamingSpeechPlayer(
        speaker,
        on_speaking=session.mark_speaking,
    )
    watcher_stop = threading.Event()

    def interrupt_speech() -> None:
        agent.cancel_pending_actions()
        player.interrupt()
        session.interrupt()

    watcher = threading.Thread(
        target=_watch_for_speech_interrupt,
        args=(watcher_stop, interrupt_speech),
        name="jarvis-escape-watcher",
        daemon=True,
    )
    watcher.start()
    try:
        answer = _chat_with_stream(
            agent,
            settings.assistant_name,
            transcript,
            on_text_delta=player.feed,
        )
    except Exception:
        player.interrupt()
        try:
            player.finish(timeout=2)
        except VoiceError:
            pass
        raise
    else:
        try:
            player.finish(fallback_text=answer)
        except VoiceError as exc:
            print(f"[朗读失败] {exc}", file=sys.stderr)
    finally:
        watcher_stop.set()
        watcher.join(timeout=1)

    if player.interrupted:
        session.interrupt()
        print("[朗读已打断]")
    session.complete_turn()


def _voice_mode(agent: JarvisAgent, settings: Settings) -> None:
    try:
        runtime = build_voice_runtime(settings.voice_settings, settings.model_settings)
    except VoiceError as exc:
        print(f"无法启动语音模式：{exc}")
        return
    session = VoiceSession(runtime.recorder, runtime.transcriber)

    print(
        "\n已进入语音模式。按 Enter 开始录音，输入 q 返回文字模式；"
        "回答播放时按 Esc 打断。"
    )
    while True:
        try:
            action = input("\n[语音] Enter=开始，q=返回> ").strip().lower()
            if action in {"q", "quit", "back", "/back"}:
                print("已返回文字模式。")
                return
            if action:
                print("请输入 q 返回，或直接按 Enter 开始录音。")
                continue

            session.start_recording()
            print("[录音中] 请说话，按 Enter 停止……", flush=True)
            limited = _wait_for_recording_stop(runtime.recorder.limit_reached)
            print("[转写中]", flush=True)
            clip, transcript = session.stop_and_transcribe()
            suffix = "（已达到时长上限）" if limited else ""
            print(f"[录音完成] {clip.duration_seconds:.1f} 秒{suffix}")
            print(f"你> {transcript}")
            _run_voice_response(
                agent,
                settings,
                session,
                transcript,
                runtime.speaker,
            )
        except (EOFError, KeyboardInterrupt):
            session.cancel()
            print("\n已返回文字模式。")
            return
        except VoiceError as exc:
            session.fail()
            print(f"[语音失败] {exc}", file=sys.stderr)
        except Exception as exc:
            session.fail()
            print(f"[语音请求失败] {type(exc).__name__}: {exc}", file=sys.stderr)


def _wake_mode(agent: JarvisAgent, settings: Settings) -> None:
    try:
        voice_runtime = build_voice_runtime(settings.voice_settings, settings.model_settings)
        wake_runtime = build_wake_runtime(settings.wake_settings)
        wake_runtime.listener.prepare()
    except VoiceError as exc:
        print(f"无法启动唤醒模式：{exc}")
        return
    session = VoiceSession(voice_runtime.recorder, voice_runtime.transcriber)

    print(
        f"\n已进入唤醒模式。说出 {settings.wake_model!r} 后直接讲话；"
        "等待或录音时按 Esc 返回文字模式。"
    )
    while True:
        try:
            session.start_listening()
            print("\n[等待唤醒]", flush=True)
            wake_runtime.listener.wait_for_wake(_console_escape_pressed)
            session.wake_detected()
            print("[已唤醒] 请说话……", flush=True)
            clip = wake_runtime.endpoint_recorder.capture(_console_escape_pressed)
            print(f"[自动录音完成] {clip.duration_seconds:.1f} 秒")
            print("[转写中]", flush=True)
            transcript = session.transcribe_clip(clip)
            print(f"你> {transcript}")
            _run_voice_response(
                agent,
                settings,
                session,
                transcript,
                voice_runtime.speaker,
            )
        except WakeCancelled:
            session.cancel()
            print("\n已返回文字模式。")
            return
        except (EOFError, KeyboardInterrupt):
            session.cancel()
            print("\n已返回文字模式。")
            return
        except VoiceError as exc:
            session.fail()
            print(f"[唤醒模式失败] {exc}", file=sys.stderr)
        except Exception as exc:
            session.fail()
            print(f"[唤醒请求失败] {type(exc).__name__}: {exc}", file=sys.stderr)


def main() -> None:
    try:
        settings = Settings.load()
        agent = build_agent(settings, _confirm)
    except Exception as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"{settings.assistant_name} 已启动。输入 /help 查看命令，/quit 退出。")
    while True:
        try:
            text = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            return
        if not text:
            continue
        if text.lower() in {"/quit", "/exit"}:
            print("再见。")
            return
        if text == "/help":
            print(
                "/help 显示帮助；/status 检查服务；/clear 清空当前上下文；"
                "/mem 关键词 搜索记忆；/voice 按键语音；/wake 唤醒词模式；/quit 退出。"
            )
            continue
        if text == "/status":
            _show_status(agent, settings)
            continue
        if text == "/clear":
            agent.clear_history()
            print("当前会话上下文已清空，长期记忆不受影响。")
            continue
        if text.startswith("/mem "):
            records = agent.memory.search(text[5:].strip())
            if not records:
                print("没有找到相关记忆。")
            for record in records:
                print(f"- [{record.category}] {record.title}: {record.content}")
            continue
        if text == "/voice":
            _voice_mode(agent, settings)
            continue
        if text == "/wake":
            _wake_mode(agent, settings)
            continue
        try:
            _chat_with_stream(agent, settings.assistant_name, text)
        except Exception as exc:
            print(f"\n请求失败：{type(exc).__name__}: {exc}", file=sys.stderr)
