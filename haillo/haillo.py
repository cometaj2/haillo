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
import select
import signal
import sys
import config

from huckle import cli
from typing import Callable, Optional

from haillo import commands as c
from haillo import mux as m
from haillo.agent import agent as a
from haillo.voice import voicecontroller as v
from haillo.voice import summary as s


class ShellWrapper:

    def __init__(self):
        self.su = s.Summary()
        self.vc = v.VoiceController()
        self.ag = a.Agent()

        self.mux: Optional[m.MuxApp] = None

        self.leader_buffer: Optional[bytes] = None

        self.LEADER_PY: dict[bytes, Callable[[], None]] = {
            b"i": self.ag.proposed_commands,
            b"g": self.ag.run_task_to_completion,
            b"v": self.vc.toggle_voice,
            b"vp": self.vc.pause_voice,
            b"vr": self.vc.resume_voice,
            b"vs": self.su.select_summary_and_stream,
        }

    def leader_keys(self) -> set[bytes]:
        return set(c.LEADER_BASH_COMMANDS) | set(self.LEADER_PY)

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

        cmd = c.LEADER_BASH_COMMANDS.get(value)
        if cmd is not None and self.mux.shell_master is not None:
            try:
                os.write(self.mux.shell_master, cmd)
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
                os.write(self.mux.shell_master, c.LEADER + value)
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

        self.mux = m.MuxApp()
        self.mux.paint_logo()

        self.ag.set_shell(self.mux.shell_master, self.mux.stdin_fd)

        self.leader_buffer = None

        rest = b""
        try:
            while True:
                fds = [self.mux.stdin_fd, self.mux.shell_master]

                timeout = (
                    c.LEADER_TIMEOUT
                    if self.leader_buffer is not None
                    else None
                )
                r, _, _ = select.select(fds, [], [], timeout)
                if not r:
                    self.flush_leader()
                    continue

                if self.mux.stdin_fd in r:
                    try:
                        data = os.read(self.mux.stdin_fd, 1024)
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
                        if pre:
                            try:
                                os.write(self.mux.shell_master, pre)
                            except OSError:
                                pass
                        if self.mux.at_shell_prompt():
                            if self.mux.active:
                                self.mux.stop(announce=True)
                            else:
                                self.mux.start()
                        else:
                            try:
                                os.write(self.mux.shell_master, c.INVOKE)
                            except OSError:
                                pass
                        rest = post
                        continue

                    if self.mux.active and self.mux.at_shell_prompt():
                        data = self.handle_leader(data)
                    else:
                        self.flush_leader()
                    if data:
                        try:
                            os.write(self.mux.shell_master, data)
                        except OSError:
                            if self.mux.active:
                                self.mux.stop()

                if self.mux.shell_master in r:
                    try:
                        out = os.read(self.mux.shell_master, 4096)
                    except OSError:
                        break
                    if not out:
                        break
                    out = self.mux.drop_shell_farewell(out)
                    if not out:
                        break
                    try:
                        os.write(self.mux.stdout_fd, out)
                    except OSError:
                        break
        finally:

            # Summary thread termination
            self.su.summary_stop.set()
            if self.su.summary_thread is not None:
                self.su.summary_thread.join(timeout=1)

            self.vc.voice.stop()

            if self.mux:
                self.mux.stop(announce=False)   # <-- no announcement on final exit
            try:
                os.close(self.mux.shell_master)
            except OSError:
                pass
            try:
                os.waitpid(self.mux.shell_pid, 0)
            except OSError:
                pass

            self.mux.paint_goodbye()
        return 0

def main() -> int:
    sw = ShellWrapper()
    return sw.wrap()

if __name__ == "__main__":
    raise SystemExit(main())
