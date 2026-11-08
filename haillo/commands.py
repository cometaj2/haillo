import os

INVOKE = bytes.fromhex(os.environ.get("PTY_MUX_INVOKE", "00"))
LEADER = b","
POLL = 1.0
LEADER_TIMEOUT = 0.45

LEADER_CMDS = {
    b"m": b"hai model ls | fzf --prompt='model> ' | xargs -r hai model set\n",
    b"p": b"hai provider ls | fzf --prompt='provider> ' | xargs -r hai provider set\n",
    b"c": b"hai ls | tail -n +2 | tac | fzf --prompt='context> ' | awk '{print $1}' | xargs -r hai set\n",
    b"r": b"gum confirm 'Reset this context?' --default=no && hai reset || echo '\nCancelled\n'\n",
    b"d": b"context=$(hai ls | tail -n +2 | tac | fzf --prompt='context> ' | awk '{print $1}'); if [ -z \"$context\" ]; then echo '\nCancelled\n'; elif gum confirm \"Delete context '$context'?\" --default=no; then hai rm \"$context\"; else echo '\nCancelled\n'; fi\n",
    b"a": (
        b"st=$(hai agent enabled | tr -d '[:space:]'); "
        b"if [ \"$st\" = True ] || [ \"$st\" = true ]; then "
        b"hai agent stop; echo '\nagent off\n'; "
        b"else "
        b"hai agent start; echo '\nagent on\n'; "
        b"fi\n"
    ),
    b"as": (
        b"hai agent skill ls | tail -n +2 | tac | "
        b"fzf --prompt='skill> ' | awk '{print $1}' | "
        b"xargs -r hai agent skill set\n"
    ),
    b"s": b"hai context\n",
    b"sl": (
        b"tmp=$(mktemp); "
        b"trap 'rm -f \"$tmp\"' EXIT; "
        b"hai context > \"$tmp\" || exit; "
        b"printf '\\n'; "
        b"cat \"$tmp\";"
        b"line=$(awk '/^----Assistant/{last=NR} END{print last+0}' \"$tmp\"); "
        b"if [ \"$line\" -gt 0 ]; then "
        b"vim -c \"normal! ${line}Gzt\" \"$tmp\"; "
        b"else "
        b"vim \"$tmp\"; "
        b"fi;\n"
    ),
    b"t": b"hai title auto\n",
    b"w": b"\necho \"$(fc -ln -2 | head -n1 | sed 's/^[ \\t]*#*[ \\t]*//')\" | hai --async\n",
    b",": b"haillo help\n",
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
