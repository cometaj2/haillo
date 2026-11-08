import os
import sys
import signal


from typing import Optional


class MuxApp:

    def __init__(self) -> None:
        self.active = False
        self.shell_master: Optional[int] = None

    def _announce(self, line: bytes) -> None:
        try:
            os.write(sys.stdout.fileno(), line)
        except OSError:
            pass
        if self.shell_master is not None:
            try:
                os.write(self.shell_master, b"\n")
            except OSError:
                pass

    def start(self, shell_master: int) -> None:
        self.shell_master = shell_master
        self.active = True
        self._announce(b"haillo pty mux on")

    def stop(self, announce: bool = False) -> None:
        was_active = self.active
        self.active = False
        if announce and was_active:
            self._announce(b"haillo pty mux off")
