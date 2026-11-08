#!/usr/bin/env python3

"""
Pass-through PTY wrapper around $SHELL with a mux hook.
The shell stays on its own PTY for the life of the wrapper. Ctrl-Space is
only honored when that PTY's foreground process group is the shell itself
(so vim, less, pagers, etc. swallow the key like a normal terminal).
On Ctrl-Space the wrapper toggles a muxed application overlay.
When mux is on and the shell owns the tty, "," is a leader key.
"""

import errno
import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import tty
import bashlex
import json
import time
import subprocess
import config
import threading

from huckle import cli
from typing import Callable, Optional

from haillo import commands as c
from haillo import mux as m
from haillo.voice import voicecontroller as v
from haillo.voice import summary as s
from haillo import agent as a


class ShellWrapper:

    def __init__(self):
        self.su = s.Summary()
        self.vc = v.VoiceController()
        self.ag = a.Agent()

        self.leader_buffer: Optional[bytes] = None
        self.shell_master: Optional[int] = None
        self.mux: Optional[MuxApp] = None
        self.stdin_fd: Optional[int] = None

        self.LEADER_PY: dict[bytes, Callable[[], None]] = {
            b"i": self.ag.proposed_commands,
            b"g": self.ag.run_task_to_completion,
            b"v": self.vc.toggle_voice,
            b"vp": self.vc.pause_voice,
            b"vr": self.vc.resume_voice,
            b"vs": self.su.select_summary_and_stream,
        }

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

    def at_shell_prompt(self, shell_pgrp: int) -> bool:
        pgrp = self.fg_pgrp(self.shell_master)
        return pgrp is not None and pgrp == shell_pgrp

    def paint_text(self, fd: int, text: str) -> None:
        if fd != sys.stdout.fileno() and not text.endswith("\n"):
            text += "\n"
        payload = text.replace("\n", "\r\n").encode()
        try:
            os.write(fd, payload)
            time.sleep(0.1)
        except OSError:
            pass

    def paint_logo(self, fd: int) -> None:
        self.paint_text(fd, c.LOGO)

    def paint_goodbye(self, fd: int) -> None:
        self.paint_text(fd, c.GOODBYE)

    def on_winch(self, signum, frame) -> None:
        if self.stdin_fd is None or self.shell_master is None:
            return
        try:
            raw = self.winsize(self.stdin_fd)
            self.set_winsize(self.shell_master, raw)
            if self.mux and self.mux.master is not None:
                self.set_winsize(self.mux.master, raw)
                if self.mux.pid:
                    try:
                        os.kill(self.mux.pid, signal.SIGWINCH)
                    except OSError:
                        pass
        except OSError:
            pass

    def leader_keys(self) -> set[bytes]:
        return set(c.LEADER_CMDS) | set(self.LEADER_PY)

    def leader_is_prefix(self, value: bytes) -> bool:
        return any(
            key.startswith(value) and key != value
            for key in self.leader_keys()
        )

    def execute_leader(self, value: bytes) -> None:
        py = self.LEADER_PY.get(value)
        if py is not None:
            try:
                py()
            except Exception as e:
                self.paint_text(
                    sys.stdout.fileno(),
                    f"leader py error: {e}\n",
                )
            return

        cmd = c.LEADER_CMDS.get(value)
        if cmd is not None and self.shell_master is not None:
            try:
                os.write(self.shell_master, cmd)
            except OSError:
                pass

    def flush_leader(self) -> None:
        if self.leader_buffer is None:
            return

        value = self.leader_buffer
        self.leader_buffer = None

        if value in self.leader_keys():
            self.execute_leader(value)
        else:
            try:
                os.write(
                    self.shell_master,
                    c.LEADER + value,
                )
            except OSError:
                pass

    def handle_leader(self, data: bytes) -> bytes:
        out = bytearray()
        i = 0
        n = len(data)

        while i < n:
            ch = data[i:i + 1]

            if self.leader_buffer is None:
                if ch == c.LEADER:
                    self.leader_buffer = b""
                else:
                    out += ch
                i += 1
                continue

            candidate = self.leader_buffer + ch

            if (
                candidate in self.leader_keys()
                or self.leader_is_prefix(candidate)
            ):
                self.leader_buffer = candidate
                i += 1

                if (
                    candidate in self.leader_keys()
                    and not self.leader_is_prefix(candidate)
                ):
                    self.execute_leader(candidate)
                    self.leader_buffer = None

                continue

            pending = self.leader_buffer
            self.leader_buffer = None

            if pending in self.leader_keys():
                self.execute_leader(pending)
            else:
                out += c.LEADER + pending

            # Re-process the current byte after resolving the pending
            # leader sequence.
            continue

        return bytes(out)

    def wrap(self) -> int:
        try:
            enabled = self.vc.voice_tag_active()
            if enabled:
                self.vc.voice.set_enabled(True)
            else:
                self.vc.terminate_spawn_voice()
                self.vc.voice.set_enabled(False)
        except Exception:
            pass

        self.stdin_fd = sys.stdin.fileno()
        stdout_fd = sys.stdout.fileno()
        if not os.isatty(self.stdin_fd):
            sys.stderr.write("pty_mux: stdin is not a tty\n")
            return 1

        shell = os.environ.get("SHELL", "/bin/bash")
        shell_pid, shell_master = pty.fork()
        if shell_pid == 0:
            os.execvp(shell, [shell, "-l"])

        self.shell_master = shell_master
        self.ag.set_shell(self.shell_master)
        self.mux = m.MuxApp()

        try:
            self.set_winsize(self.shell_master, self.winsize(self.stdin_fd))
        except OSError:
            pass

        self.paint_logo(stdout_fd)
        shell_pgrp = shell_pid
        self.leader_buffer = None

        signal.signal(signal.SIGWINCH, self.on_winch)
        old = termios.tcgetattr(self.stdin_fd)
        tty.setraw(self.stdin_fd)
        rest = b""

        try:
            while True:
                fds = [self.stdin_fd, self.shell_master]
                if self.mux.master is not None:
                    fds.append(self.mux.master)

                timeout = (
                    c.LEADER_TIMEOUT
                    if self.leader_buffer is not None
                    else None
                )
                r, _, _ = select.select(fds, [], [], timeout)
                if not r:
                    self.flush_leader()
                    continue

                if self.stdin_fd in r:
                    try:
                        data = os.read(self.stdin_fd, 1024)
                    except OSError as e:
                        if e.errno == errno.EINTR:
                            continue
                        break
                    if not data:
                        break
                    data = rest + data
                    rest = b""

                    if c.INVOKE and c.INVOKE in data:
                        self.flush_leader()
                        pre, _, post = data.partition(c.INVOKE)
                        dest = self.mux.master if (self.mux.active and self.mux.master) else self.shell_master
                        if pre:
                            try:
                                os.write(dest, pre)
                            except OSError:
                                pass
                        if self.at_shell_prompt(shell_pgrp):
                            if self.mux.active:
                                self.mux.stop(announce=True)
                            else:
                                self.mux.start(self.shell_master)
                                self.ag.set_shell(self.shell_master)
                        else:
                            try:
                                os.write(dest, c.INVOKE)
                            except OSError:
                                pass
                        rest = post
                        continue

                    dest = self.mux.master if (self.mux.active and self.mux.master) else self.shell_master
                    if self.mux.active and self.at_shell_prompt(shell_pgrp):
                        data = self.handle_leader(data)
                    else:
                        self.flush_leader()
                    if data:
                        try:
                            os.write(dest, data)
                        except OSError:
                            if self.mux.active:
                                self.mux.stop()

                if self.mux.master is not None and self.mux.master in r:
                    try:
                        out = os.read(self.mux.master, 4096)
                    except OSError:
                        out = b""
                    if not out:
                        self.mux.stop()
                    else:
                        try:
                            os.write(stdout_fd, out)
                        except OSError:
                            break

                if self.shell_master in r:
                    try:
                        out = os.read(self.shell_master, 4096)
                    except OSError:
                        break
                    if not out:
                        break
                    out = self.drop_shell_farewell(out)
                    if not out:
                        break
                    try:
                        os.write(stdout_fd, out)
                    except OSError:
                        break
        finally:

            # Summary thread termination
            self.su.summary_stop.set()

            if self.su.summary_thread is not None:
                self.su.summary_thread.join(timeout=1)

            termios.tcsetattr(self.stdin_fd, termios.TCSADRAIN, old)
            self.vc.voice.stop()
            if self.mux:
                self.mux.stop(announce=False)   # <-- no announcement on final exit
            try:
                os.close(self.shell_master)
            except OSError:
                pass
            try:
                os.waitpid(shell_pid, 0)
            except OSError:
                pass
            self.paint_goodbye(stdout_fd)
        return 0


def main() -> int:
    sw = ShellWrapper()
    return sw.wrap()


if __name__ == "__main__":
    raise SystemExit(main())
