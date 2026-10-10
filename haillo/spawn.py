import subprocess
import os

import subprocess
import os

def spawn():
    # Get a usable window selector (address in 0x form)
    result = subprocess.run(
        ["hyprctl", "repl",
         "string.format('address:0x%x', hl.get_active_window().address)"],
        env=os.environ,
        capture_output=True,
        text=True
    )
    window_selector = result.stdout.strip()

    # Run your script
    subprocess.run(
        ["/bin/bash", "/home/jeff/Documents/workspace/hcli/haillo/haillo/scripts/spawn_voice.sh"],
        env=os.environ,
        capture_output=True,
        text=True
    )

    # Refocus using the selector
    subprocess.run(
        ["hyprctl", "dispatch",
         f'hl.dsp.focus({{ window = "{window_selector}" }})'],
        env=os.environ,
        capture_output=True,
        text=True
    )

spawn()




