import subprocess
import sys


def test_compatibility_modules_forward_to_new_boundaries() -> None:
    from jarvis.adapters.desktop import WindowsDesktopObserver
    from jarvis.application.assistant import JarvisAgent as CompatAgent
    from jarvis.application.assistant import JarvisAgent
    from jarvis.interfaces.cli import main as compat_main
    from jarvis.interfaces.cli import main
    from jarvis.ports.audio import AudioClip as PortAudioClip
    from jarvis.adapters.audio.voice import AudioClip

    assert CompatAgent is JarvisAgent
    assert compat_main is main
    assert AudioClip is PortAudioClip
    assert WindowsDesktopObserver.__name__ == "WindowsDesktopObserver"


def test_ports_can_be_imported_before_application_services() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from jarvis.ports.desktop import ApplicationLauncher, "
                "DesktopController, DesktopSnapshot, WindowRef; "
                "import jarvis.ports.model"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
