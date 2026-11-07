import os
import threading
import subprocess

from typing import Callable, Optional
from haillo.voice import voicecontroller as v
from huckle import cli, stdin


class Summary():

    def __init__(self):

        # Latest summary id monitoring
        self.summary_stop = threading.Event()
        self.summary_thread: Optional[threading.Thread] = None
        self.summary_latest: Optional[str] = None

        self.summary_latest = self.latest_summary_id()
        self.summary_thread = threading.Thread(
            target=self.monitor_summaries,
            name="summary-monitor",
            daemon=True,
        )
        self.summary_thread.start()

        self.vc = v.VoiceController()

    def select_summary_and_stream(self) -> bool:
        """
        Run the summary selector in Bash, capture the selected summary ID,
        then pull and speak that summary from Python.
        """
        command = r"""
            hai summary ls |
            tail -n +2 |
            tac |
            fzf --prompt='summary> ' |
            awk '{print $1}'
        """

        tty_fd = None

        try:
            # Use the wrapper's controlling terminal for fzf's UI.
            tty_fd = os.open("/dev/tty", os.O_RDWR)

            result = subprocess.run(
                ["/bin/bash", "-c", command],
                stdin=tty_fd,
                stdout=subprocess.PIPE,
                stderr=tty_fd,
                text=True,
                env=os.environ,
                check=False,
            )

        except (OSError, subprocess.SubprocessError):
            return False

        finally:
            if tty_fd is not None:
                try:
                    os.close(tty_fd)
                except OSError:
                    pass

        if result.returncode != 0:
            # Usually means the user pressed Escape or Ctrl-C in fzf.
            return False

        summary_id = result.stdout.strip()

        if not summary_id:
            return False

        # Keep the captured value constrained to an ID-like value.
        if not all(c.isalnum() or c in "_-" for c in summary_id):
            return False

        return self.vc.stream_voice(summary_id)

    def latest_summary_id(self) -> Optional[str]:
        try:
            chunks = cli("hai summary ls")
            text = b"".join(
                chunk
                for direction, chunk in chunks
                if direction == "stdout"
            ).decode("utf-8", errors="replace")
        except Exception:
            return None

        ids = []

        for line in text.splitlines():
            fields = line.split()
            if not fields:
                continue

            summary_id = fields[0]

            if summary_id.lower() in {"id", "summary", "name"}:
                continue

            if all(char.isalnum() or char in "_-" for char in summary_id):
                ids.append(summary_id)

        return ids[-1] if ids else None

    def monitor_summaries(self) -> None:
        while not self.summary_stop.wait(5):
            latest = self.latest_summary_id()

            if latest is None:
                continue

            if self.summary_latest is None:
                # Establish the initial baseline without speaking it.
                self.summary_latest = latest
                continue

            if latest == self.summary_latest:
                continue

            self.summary_latest = latest

            if self.vc.voice.is_enabled():
                self.vc.stream_voice(latest)
