"""macOS LaunchAgent-автозапуск LogistAI."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from xml.sax.saxutils import escape


class MacOSLaunchAgentAutostart:
    """AutostartManager через ~/Library/LaunchAgents."""

    def __init__(
        self,
        *,
        label: str = "app.logistai.LogistAI",
        executable: str | None = None,
        args: tuple[str, ...] | None = None,
        launch_agents_dir: Path | None = None,
    ) -> None:
        self._label = label
        self._executable = executable if executable is not None else sys.executable
        self._args = args if args is not None else tuple(sys.argv)
        self._dir = (
            launch_agents_dir
            if launch_agents_dir is not None
            else Path.home() / "Library" / "LaunchAgents"
        )

    @property
    def path(self) -> Path:
        """Путь plist-файла LaunchAgent."""
        return self._dir / f"{self._label}.plist"

    def is_enabled(self) -> bool:
        """Включён ли автозапуск сейчас."""
        return self.path.exists()

    def enable(self) -> None:
        """Включить автозапуск."""
        self._dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self._plist(), encoding="utf-8")

    def disable(self) -> None:
        """Выключить автозапуск."""
        if self.path.exists():
            self.path.unlink()

    def _plist(self) -> str:
        program_arguments = [self._executable, *self._effective_args()]
        arguments_xml = "\n".join(
            f"        <string>{escape(argument)}</string>" for argument in program_arguments
        )
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{escape(self._label)}</string>
    <key>ProgramArguments</key>
    <array>
{arguments_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>WorkingDirectory</key>
    <string>{escape(os.getcwd())}</string>
</dict>
</plist>
"""

    def _effective_args(self) -> tuple[str, ...]:
        if not self._args:
            return ()
        return tuple(arg for arg in self._args if arg not in ("--demo", "--demo-ati"))
