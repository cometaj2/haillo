#!/usr/bin/env python3
"""
Pass-through PTY wrapper around $SHELL with a mux hook.
The shell stays on its own PTY for the life of the wrapper. Ctrl-Space is
only honored when that PTY's foreground process group is the shell itself
(so vim, less, pagers, etc. swallow the key like a normal terminal).
On Ctrl-Space the wrapper toggles a muxed application overlay.
When mux is on and the shell owns the tty, "," is a leader key.
See LEADER_CMDS and LEADER_PY
"""
from __future__ import annotations
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
from huckle import cli, stdin
from typing import Callable, Optional
# Ctrl-Space is NUL (0x00) in most terminals. Override with hex, e.g. "00".
INVOKE = bytes.fromhex(os.environ.get("PTY_MUX_INVOKE", "00"))
LEADER = b","
LEADER_TIMEOUT = 0.45
POLL = 1.0
SPIN = "|/-\\"
LEADER_CMDS = {
    b"m": (
        b"hai model ls | fzf --prompt='model> ' | xargs -r hai model set\n"
    ),
    b"p": (
        b"hai provider ls | fzf --prompt='provider> ' | xargs -r hai provider set\n"
    ),
    b"c": (
        b"hai ls | tail -n +2 | tac | fzf --prompt='context> ' | awk '{print $1}' | xargs -r hai set\n"
    ),
    b"r": (
        b"gum confirm 'Reset this context?' --default=no && hai reset || echo 'Cancelled'\n"
    ),
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
    b"s": (
        b"hai context\n"
    ),
    b"t": (
        b"hai title auto\n"
    ),
}


class Spinner:
    """One character at the cursor. Cleared before real output."""

    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.frame = 0
        self.on = False

    def tick(self) -> None:
        ch = SPIN[self.frame % len(SPIN)].encode()
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


def __validate_bash_command(command_string, whitelist):
    try:
        # Parse the string into a Bash AST
        trees = bashlex.parse(command_string)
    except bashlex.errors.ParsingError:
        return False  # Invalid Bash syntax
    def check_node(node):
        # If the node represents an executed command
        if node.kind == 'command':
            # Extract the base command name (e.g., 'git' from 'git commit')
            parts = node.parts
            if parts and parts[0].kind == 'word':
                command_name = parts[0].word
                if command_name not in whitelist:
                    fd = sys.stdout.fileno()
                    raise ValueError(f"unauthorized command detected: {command_name}")
        # Recursively check sub-commands (like inside pipes or subshells)
        if hasattr(node, 'parts'):
            for part in node.parts:
                check_node(part)
    try:
        for tree in trees:
            check_node(tree)
        return True
    except ValueError:
        return False
"""Fetch task from hai, show it to the user, and inject the command if allowed."""
def __proposed_commands(shell_master: int) -> bool:
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
    authz_lines = []
    lines = ["# --- hai agent task ---"]
    if goal:
        lines.append(f"# goal: {goal}")
    if why:
        lines.append(f"# why:  {why}")
    lines.append(f"# command: {bash_cmd or '(none)'}")
    allowed = False
    if bash_cmd:
        if __validate_bash_command(bash_cmd, WHITELIST):
            authz_lines.append("# status: authorized (whitelisted)")
            allowed = True
        else:
            authz_lines.append("# status: BLOCKED (not in whitelist)")
    else:
        lines.append("# status: no command proposed")
    # Build a single-line printf command (no newlines in the shell command itself)
    printf_authz_args = " ".join(f'"{line}"' for line in authz_lines)
    printf_args = " ".join(f'"{line}"' for line in lines)
    gum_lines = (
        f'gum style --border rounded --width $(tput cols) '
        f'--padding "0 1" "$(printf \'%s\\n\' {printf_args})";'
    )
    gum_authz_lines = (
        f'gum style --border rounded --width $(tput cols) '
        f'--padding "0 1" "$(printf \'%s\\n\' {printf_authz_args})";'
    )
    # Combine into a single command so no prompt appears between them
    combined_cmd = (
        b""
        + gum_lines.encode("utf-8")
        + gum_authz_lines.encode("utf-8")
        + b"stty echo\n"
    )
    try:
        os.write(shell_master, b"stty -echo\n")
        os.write(shell_master, combined_cmd)
        if allowed:
            os.write(shell_master, (bash_cmd + " | hai agent next && hai agent next mark\n").encode("utf-8"))
    except OSError:
        return False
    return allowed
def __forward(shell_master: int, seconds: float, spin: Optional[Spinner] = None) -> bool:
    """Wait, but keep the shell tty alive. True means the user hit Ctrl-C."""
    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    end = time.monotonic() + seconds
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return False
        if spin is not None:
            spin.tick()
        try:
            ready, _, _ = select.select([stdin_fd, shell_master], [], [], min(0.1, remaining))
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
                os.write(shell_master, data)
            except OSError:
                pass
        if shell_master in ready:
            try:
                out = os.read(shell_master, 4096)
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
def __run_task_to_completion(shell_master: int) -> None:
    """Poll hai agent status once a second and inject a command when it is next.
    The wait forwards shell output, so the wrapper select loop being paused
    does not freeze the tty. Ctrl-C leaves the loop.
    """
    spin = Spinner(sys.stdout.fileno())
    def restore_echo():
        spin.clear()
        try:
            os.write(shell_master, b"stty echo\n")
        except OSError:
            pass
    try:
        while True:
            spin.tick()
            chunks = cli("hai agent status")
            status = b"".join(c for d, c in chunks if d == "stdout").decode().strip()
            if status == "next":
                spin.clear()
                if not __proposed_commands(shell_master):
                    break
            elif status in ("done", "blocked"):
                break
            if __forward(shell_master, POLL, spin):
                break
    finally:
        restore_echo()
LEADER_PY: dict[bytes, Callable[[int], None]] = {
    b"i": __proposed_commands,
    b"g": __run_task_to_completion,
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
def paint_text(fd: int, text: str) -> None:
    if fd != sys.stdout.fileno() and not text.endswith("\n"):
        text += "\n"
    payload = text.replace("\n", "\r\n").encode()
    try:
        os.write(fd, payload)
        time.sleep(0.1)
    except OSError:
        pass
def paint_logo(fd: int) -> None:
    paint_text(fd, LOGO)
def paint_goodbye(fd: int) -> None:
    paint_text(fd, GOODBYE)
_SHELL_BYE = (
    b"exit\r\n",
    b"exit\n",
    b"logout\r\n",
    b"logout\n",
)
def drop_shell_farewell(data: bytes) -> bytes:
    for token in _SHELL_BYE:
        if data.endswith(token):
            return data[: -len(token)]
    return data
def winsize(fd: int) -> bytes:
    return fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\x00" * 8)
def set_winsize(fd: int, raw: bytes) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, raw)
def fg_pgrp(master: int) -> Optional[int]:
    try:
        packed = fcntl.ioctl(master, termios.TIOCGPGRP, struct.pack("i", 0))
        pgrp = struct.unpack("i", packed)[0]
        return pgrp if pgrp > 0 else None
    except OSError:
        return None
def at_shell_prompt(master: int, shell_pgrp: int) -> bool:
    pgrp = fg_pgrp(master)
    return pgrp is not None and pgrp == shell_pgrp
class MuxApp:
    def __init__(self) -> None:
        self.pid: Optional[int] = None
        self.master: Optional[int] = None
        self.active = False
    def _announce(self, line: bytes, shell_master: int) -> None:
        try:
            os.write(sys.stdout.fileno(), line)
        except OSError:
            pass
        try:
            os.write(shell_master, b"\n")
        except OSError:
            pass
    def spawn(self, tty_fd: int, shell_master: int) -> None:
        self.active = True
        self._announce(b"haillo pty mux on", shell_master)
    def close(self, shell_master: Optional[int] = None) -> None:
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
        self.active = False
        if shell_master is not None:
            self._announce(b"haillo pty mux off", shell_master)
def wrap_shell() -> int:
    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    if not os.isatty(stdin_fd):
        sys.stderr.write("pty_mux: stdin is not a tty\n")
        return 1
    shell = os.environ.get("SHELL", "/bin/bash")
    shell_pid, shell_master = pty.fork()
    if shell_pid == 0:
        os.execvp(shell, [shell, "-l"])
    try:
        set_winsize(shell_master, winsize(stdin_fd))
    except OSError:
        pass
    paint_logo(stdout_fd)
    shell_pgrp = shell_pid
    mux = MuxApp()
    leader_armed = False
    def on_winch(_signum, _frame) -> None:
        raw = winsize(stdin_fd)
        try:
            set_winsize(shell_master, raw)
        except OSError:
            pass
        if mux.master is not None:
            try:
                set_winsize(mux.master, raw)
            except OSError:
                pass
            if mux.pid:
                try:
                    os.kill(mux.pid, signal.SIGWINCH)
                except OSError:
                    pass
    signal.signal(signal.SIGWINCH, on_winch)
    old = termios.tcgetattr(stdin_fd)
    tty.setraw(stdin_fd)
    rest = b""
    def flush_leader() -> None:
        nonlocal leader_armed
        if leader_armed:
            try:
                os.write(shell_master, LEADER)
            except OSError:
                pass
            leader_armed = False
    def handle_leader(data: bytes) -> bytes:
        """Consume mux-mode leader sequences. Return leftover bytes."""
        nonlocal leader_armed
        out = bytearray()
        i = 0
        n = len(data)
        while i < n:
            ch = data[i : i + 1]
            if leader_armed:
                leader_armed = False
                py = LEADER_PY.get(ch)
                if py is not None:
                    try:
                        py(shell_master)
                    except Exception as e:
                        paint_text(stdout_fd, f"leader py error: {e}\n")
                else:
                    cmd = LEADER_CMDS.get(ch)
                    if cmd is not None:
                        try:
                            os.write(shell_master, cmd)
                        except OSError:
                            pass
                    else:
                        out += LEADER + ch
                i += 1
                continue
            if ch == LEADER:
                leader_armed = True
                i += 1
                continue
            out += ch
            i += 1
        return bytes(out)
    try:
        while True:
            fds = [stdin_fd, shell_master]
            if mux.master is not None:
                fds.append(mux.master)
            timeout = LEADER_TIMEOUT if leader_armed else None
            r, _, _ = select.select(fds, [], [], timeout)
            if not r:
                flush_leader()
                continue
            if stdin_fd in r:
                try:
                    data = os.read(stdin_fd, 1024)
                except OSError as e:
                    if e.errno == errno.EINTR:
                        continue
                    break
                if not data:
                    break
                data = rest + data
                rest = b""
                if INVOKE and INVOKE in data:
                    flush_leader()
                    pre, _, post = data.partition(INVOKE)
                    dest = mux.master if (mux.active and mux.master) else shell_master
                    if pre:
                        try:
                            os.write(dest, pre)
                        except OSError:
                            pass
                    if at_shell_prompt(shell_master, shell_pgrp):
                        if mux.active:
                            mux.close(shell_master)
                        else:
                            mux.spawn(stdin_fd, shell_master)
                    else:
                        try:
                            os.write(dest, INVOKE)
                        except OSError:
                            pass
                    rest = post
                    continue
                dest = mux.master if (mux.active and mux.master) else shell_master
                if mux.active and at_shell_prompt(shell_master, shell_pgrp):
                    data = handle_leader(data)
                else:
                    flush_leader()
                if not data:
                    continue
                try:
                    os.write(dest, data)
                except OSError:
                    if mux.active:
                        mux.close(shell_master)
            if mux.master is not None and mux.master in r:
                try:
                    out = os.read(mux.master, 4096)
                except OSError:
                    out = b""
                if not out:
                    mux.close(shell_master)
                else:
                    try:
                        os.write(stdout_fd, out)
                    except OSError:
                        break
            if shell_master in r:
                try:
                    out = os.read(shell_master, 4096)
                except OSError:
                    break
                if not out:
                    break
                out = drop_shell_farewell(out)
                if not out:
                    break
                try:
                    os.write(stdout_fd, out)
                except OSError:
                    break
    finally:
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old)
        mux.close()
        try:
            os.close(shell_master)
        except OSError:
            pass
        try:
            os.waitpid(shell_pid, 0)
        except OSError:
            pass
        paint_goodbye(stdout_fd)
    return 0
def main() -> int:
    return wrap_shell()
if __name__ == "__main__":
    raise SystemExit(main())
