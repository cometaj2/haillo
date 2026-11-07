import os
import sys

from huckle import cli
from typing import Callable, Optional

from haillo import spinner as s


class Agent():

    def __init__(self):
        self.shell_master: Optional[int] = None

    def set_shell(self, shell_master):
        self.shell_master = shell_master

    def validate_bash_command(self, command_string: str, whitelist) -> bool:
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

    def proposed_commands(self) -> bool:
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
            if self.validate_bash_command(bash_cmd, WHITELIST):
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

    def forward(self, seconds: float, spin: Optional[Spinner] = None) -> bool:
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

    def run_task_to_completion(self) -> None:
        spin = s.Spinner(sys.stdout.fileno())

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
                    if not self.proposed_commands():
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
                if self.forward(ShellWrapper.POLL, spin):
                    break
        finally:
            restore_echo()
