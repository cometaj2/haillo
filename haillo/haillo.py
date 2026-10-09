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
from huckle import cli
from typing import Callable, Optional


class Spinner:
    """One character at the cursor. Cleared before real output."""

    SPIN = "|/-\\"

    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.frame = 0
        self.on = False

    def tick(self) -> None:
        ch = Spinner.SPIN[self.frame % len(Spinner.SPIN)].encode()
        self.frame += 1
        try:
            if self.on:
                os.write(self.fd, b"\x08" + ch)
            else:
                os.write(self.fd, b"\x1b[?25l" + ch)
                self.on = True
        except OSError:
            pass

    def clear(self) -> None:
        if not self.on:
            return
        try:
            os.write(self.fd, b"\x08 \x08\x1b[?25h")
        except OSError:
            pass
        self.on = False


class MuxApp:

    def __init__(self) -> None:
        self.pid: Optional[int] = None
        self.master: Optional[int] = None
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

    def spawn(self, shell_master: int) -> None:
        self.shell_master = shell_master
        self.active = True
        self._announce(b"haillo pty mux on")

    def close(self, announce: bool = False) -> None:
        if self.master is not None:
            try:
                os.close(self.master)
            except OSError:
                pass
        if self.pid is not None:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except OSError:
                pass
            try:
                os.waitpid(self.pid, os.WNOHANG)
            except OSError:
                pass
        self.pid = None
        self.master = None
        was_active = self.active
        self.active = False
        if announce and was_active:
            self._announce(b"haillo pty mux off")


class ShellWrapper:

    INVOKE = bytes.fromhex(os.environ.get("PTY_MUX_INVOKE", "00"))
    LEADER = b","
    POLL = 1.0
    LEADER_TIMEOUT = 0.45

    LEADER_CMDS = {
        b"m": b"hai model ls | fzf --prompt='model> ' | xargs -r hai model set\n",
        b"p": b"hai provider ls | fzf --prompt='provider> ' | xargs -r hai provider set\n",
        b"c": b"hai ls | tail -n +2 | tac | fzf --prompt='context> ' | awk '{print $1}' | xargs -r hai set\n",
        b"r": b"gum confirm 'Reset this context?' --default=no && hai reset || echo '\nCancelled\n'\n",
        b"v": (
            b"st=$(hai voice enabled | tr -d '[:space:]'); "
            b"if [ \"$st\" = True ] || [ \"$st\" = true ]; then "
            b"hai voice stop; echo '\nvoice assist off\n'; "
            b"else "
            b"hai voice start; echo '\nvoice assist on\n'; "
            b"fi\n"
        ),
        b"a": (
            b"st=$(hai agent enabled | tr -d '[:space:]'); "
            b"if [ \"$st\" = True ] || [ \"$st\" = true ]; then "
            b"hai agent stop; echo '\nagent off\n'; "
            b"else "
            b"hai agent start; echo '\nagent on\n'; "
            b"fi\n"
        ),
        b"s": b"hai context\n",
        b"t": b"hai title auto\n",
        b"w": b"\necho \"$(fc -ln -2 | head -n1 | sed 's/^[ \\t]*#*[ \\t]*//')\" | hai --async\n",
    }

    LOGO = r"""
  _           _ _ _
 | |__   __ _(_) | | ___
 | '_ \ / _` | | | |/ _ \
 | | | | (_| | | | | (_) |
 |_| |_|\__,_|_|_|_|\___/
        hello halo
     ctrl-space to hop

""".lstrip("\n")

    GOODBYE = r"""
  _           _ _ _
 | |__   __ _(_) | | ___
 | '_ \ / _` | | | |/ _ \
 | | | | (_| | | | | (_) |
 |_| |_|\__,_|_|_|_|\___/
       hello goodbye

""".lstrip("\n")

    SHELL_BYE = (
        b"exit\r\n",
        b"exit\n",
        b"logout\r\n",
        b"logout\n",
    )

    def __init__(self):
        self.leader_armed = False
        self.shell_master: Optional[int] = None
        self.mux: Optional[MuxApp] = None
        self.stdin_fd: Optional[int] = None

        self.LEADER_PY: dict[bytes, Callable[[], None]] = {
            b"i": self.__proposed_commands,
            b"g": self.__run_task_to_completion,
        }

    def drop_shell_farewell(self, data: bytes) -> bytes:
        for token in ShellWrapper.SHELL_BYE:
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
        self.paint_text(fd, ShellWrapper.LOGO)

    def paint_goodbye(self, fd: int) -> None:
        self.paint_text(fd, ShellWrapper.GOODBYE)

    def __validate_bash_command(self, command_string: str, whitelist) -> bool:
        def check_node(node):
            if node.kind == 'command':
                parts = node.parts
                if parts and parts[0].kind == 'word':
                    command_name = parts[0].word
                    if command_name not in whitelist:
                        raise ValueError(f"unauthorized command detected: {command_name}")
            if hasattr(node, 'parts'):
                for part in node.parts:
                    check_node(part)

        try:
            trees = bashlex.parse(command_string)
        except bashlex.errors.ParsingError:
            return False

        try:
            for tree in trees:
                check_node(tree)
            return True
        except ValueError:
            return False

    def __proposed_commands(self) -> bool:
        try:
            chunks = cli("hai agent task")
            task_str = b"".join(c for d, c in chunks if d == "stdout")
            task = json.loads(task_str)
        except Exception:
            return False
        if not isinstance(task, dict):
            return False

        bash_cmd = (task.get("bash") or "").strip()
        goal = task.get("goal", "")
        why = task.get("why", "")
        WHITELIST = frozenset({
            "pwd", "ls", "echo", "grep", "curl", "cat", "head", "tail", "wc",
            "man", "hat", "huckle", "ddgr", "git",
        })

        lines = ["# --- hai agent task ---"]
        if goal:
            lines.append(f"# goal: {goal}")
        if why:
            lines.append(f"# why:  {why}")
        lines.append(f"# command: {bash_cmd or '(none)'}")

        allowed = False
        if bash_cmd:
            if self.__validate_bash_command(bash_cmd, WHITELIST):
                lines.append("# status: authorized (whitelisted)")
                allowed = True
            else:
                lines.append("# status: BLOCKED (not in whitelist)")
        else:
            lines.append("# status: no command proposed")

        printf_args = " ".join(f'"{line}"' for line in lines)
        gum_cmd = (
            f'gum style --border rounded --width $(tput cols) '
            f'--padding "0 1" "$(printf \'%s\\n\' {printf_args})";'
        ).encode()

        try:
            os.write(self.shell_master, b"stty -echo\n" + gum_cmd + b"stty echo\n")
            if allowed:
                os.write(self.shell_master, (bash_cmd + " | perl -pe 's/\\x1b\\[[0-9;]*[a-zA-Z]//g' | hai agent next\n").encode("utf-8"))
        except OSError:
            return False
        return allowed

    def __forward(self, seconds: float, spin: Optional[Spinner] = None) -> bool:
        stdin_fd = self.stdin_fd
        stdout_fd = sys.stdout.fileno()
        end = time.monotonic() + seconds
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                return False
            if spin is not None:
                spin.tick()
            try:
                ready, _, _ = select.select([stdin_fd, self.shell_master], [], [], min(0.1, remaining))
            except (InterruptedError, select.error):
                continue
            if not ready:
                continue
            if stdin_fd in ready:
                try:
                    data = os.read(stdin_fd, 1024)
                except OSError:
                    return True
                if not data or b"\x03" in data:
                    return True
                try:
                    os.write(self.shell_master, data)
                except OSError:
                    pass
            if self.shell_master in ready:
                try:
                    out = os.read(self.shell_master, 4096)
                except OSError:
                    return True
                if not out:
                    return True
                if spin is not None:
                    spin.clear()
                try:
                    os.write(stdout_fd, out)
                except OSError:
                    return True

    def __run_task_to_completion(self) -> None:
        spin = Spinner(sys.stdout.fileno())

        def restore_echo():
            spin.clear()
            try:
                os.write(self.shell_master, b"stty echo\n")
            except OSError:
                pass

        try:
            while True:
                spin.tick()
                chunks = cli("hai agent status")
                status = b"".join(c for d, c in chunks if d == "stdout").decode().strip()
                if status == "next":
                    spin.clear()
                    if not self.__proposed_commands():
                        break
                elif status in ("inactive", "done", "blocked"):
                    gum_cmd = (
                        f'gum style --border rounded --width $(tput cols) '
                        f'--padding "0 1" "# agent {status}";'
                    ).encode()
                    combined = b"stty -echo\n" + gum_cmd + b"stty echo\n"
                    try:
                        os.write(self.shell_master, combined)
                    except OSError:
                        pass
                    break
                if self.__forward(ShellWrapper.POLL, spin):
                    break
        finally:
            restore_echo()

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

    def flush_leader(self) -> None:
        if self.leader_armed and self.shell_master is not None:
            try:
                os.write(self.shell_master, ShellWrapper.LEADER)
            except OSError:
                pass
            self.leader_armed = False

    def handle_leader(self, data: bytes) -> bytes:
        out = bytearray()
        i = 0
        n = len(data)
        while i < n:
            ch = data[i:i + 1]
            if self.leader_armed:
                self.leader_armed = False
                py = self.LEADER_PY.get(ch)
                if py is not None:
                    try:
                        py()
                    except Exception as e:
                        self.paint_text(sys.stdout.fileno(), f"leader py error: {e}\n")
                else:
                    cmd = ShellWrapper.LEADER_CMDS.get(ch)
                    if cmd is not None and self.shell_master is not None:
                        try:
                            os.write(self.shell_master, cmd)
                        except OSError:
                            pass
                    else:
                        out += ShellWrapper.LEADER + ch
                i += 1
                continue
            if ch == ShellWrapper.LEADER:
                self.leader_armed = True
                i += 1
                continue
            out += ch
            i += 1
        return bytes(out)

    def wrap(self) -> int:
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
        self.mux = MuxApp()

        try:
            self.set_winsize(self.shell_master, self.winsize(self.stdin_fd))
        except OSError:
            pass

        self.paint_logo(stdout_fd)
        shell_pgrp = shell_pid
        self.leader_armed = False

        signal.signal(signal.SIGWINCH, self.on_winch)
        old = termios.tcgetattr(self.stdin_fd)
        tty.setraw(self.stdin_fd)
        rest = b""

        try:
            while True:
                fds = [self.stdin_fd, self.shell_master]
                if self.mux.master is not None:
                    fds.append(self.mux.master)

                timeout = ShellWrapper.LEADER_TIMEOUT if self.leader_armed else None
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

                    if ShellWrapper.INVOKE and ShellWrapper.INVOKE in data:
                        self.flush_leader()
                        pre, _, post = data.partition(ShellWrapper.INVOKE)
                        dest = self.mux.master if (self.mux.active and self.mux.master) else self.shell_master
                        if pre:
                            try:
                                os.write(dest, pre)
                            except OSError:
                                pass
                        if self.at_shell_prompt(shell_pgrp):
                            if self.mux.active:
                                self.mux.close(announce=True)
                            else:
                                self.mux.spawn(self.shell_master)
                        else:
                            try:
                                os.write(dest, ShellWrapper.INVOKE)
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
                                self.mux.close()

                if self.mux.master is not None and self.mux.master in r:
                    try:
                        out = os.read(self.mux.master, 4096)
                    except OSError:
                        out = b""
                    if not out:
                        self.mux.close()
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
            termios.tcsetattr(self.stdin_fd, termios.TCSADRAIN, old)
            if self.mux:
                self.mux.close(announce=False)   # <-- no announcement on final exit
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
