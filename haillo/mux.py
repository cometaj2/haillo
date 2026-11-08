import os
import sys
import pty
import signal
import time
import fcntl
import termios
import struct
import tty

from typing import Optional

from haillo import commands as c


class MuxApp:

    def __init__(self) -> None:
        self.active = False

        self.stdin_fd = sys.stdin.fileno()
        self.stdout_fd = sys.stdout.fileno()
        if not os.isatty(self.stdin_fd):
            sys.stderr.write("pty_mux: stdin is not a tty\n")
            exit(1)

        shell = os.environ.get("SHELL", "/bin/bash")
        shell_pid, shell_master = pty.fork()
        if shell_pid == 0:
            os.execvp(shell, [shell, "-l"])
        self.shell_pid = shell_pid
        self.shell_master = shell_master

        try:
            self.set_winsize(self.shell_master, self.winsize(self.stdin_fd))
        except OSError:
            pass

        signal.signal(signal.SIGWINCH, self.on_winch)
        self.old = termios.tcgetattr(self.stdin_fd)
        tty.setraw(self.stdin_fd)

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

    def start(self) -> None:
        self.active = True
        self._announce(b"haillo pty mux on")

    def stop(self, announce: bool = False) -> None:
        termios.tcsetattr(self.stdin_fd, termios.TCSADRAIN, self.old)
        was_active = self.active
        self.active = False
        if announce and was_active:
            self._announce(b"haillo pty mux off")

    def drop_shell_farewell(self, data: bytes) -> bytes:
        for token in c.SHELL_BYE:
            if data.endswith(token):
                return data[: -len(token)]
        return data

    def winsize(self, fd: int) -> bytes:
        return fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\x00" * 8)

    def set_winsize(self, fd: int, raw: bytes) -> None:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, raw)

    def fg_pgrp(self, fd: int) -> Optional[int]:
        try:
            packed = fcntl.ioctl(fd, termios.TIOCGPGRP, struct.pack("i", 0))
            pgrp = struct.unpack("i", packed)[0]
            return pgrp if pgrp > 0 else None
        except OSError:
            return None

    def at_shell_prompt(self) -> bool:
        pgrp = self.fg_pgrp(self.shell_master)
        return pgrp is not None and pgrp == self.shell_pid

    def paint_text(self, fd: int, text: str) -> None:
        if fd != sys.stdout.fileno() and not text.endswith("\n"):
            text += "\n"
        payload = text.replace("\n", "\r\n").encode()
        try:
            os.write(fd, payload)
            time.sleep(0.1)
        except OSError:
            pass

    def paint_logo(self) -> None:
        self.paint_text(self.stdout_fd, c.LOGO)

    def paint_goodbye(self) -> None:
        self.paint_text(self.stdout_fd, c.GOODBYE)

    def on_winch(self, signum, frame) -> None:
        if self.stdin_fd is None or self.shell_master is None:
            return
        try:
            raw = self.winsize(self.stdin_fd)
            self.set_winsize(self.shell_master, raw)
        except OSError:
            pass
