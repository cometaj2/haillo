#!/bin/bash

hyprctl dispatch "hl.dsp.exec_cmd('[float; center; size 250 250] alacritty -e /home/jeff/Documents/workspace/hcli/haillo/haillo/voice/ttyspec.sh')"

#hyprctl dispatch 'hl.dsp.exec_cmd("alacritty -e ./ttyspec.sh", { float = true })'

#hyprctl dispatch "hl.dsp.exec_cmd('[float; center; size 250 250] \"alacritty --hold -e ./ttyspec.sh\"')"
#alacritty -e ./ttyspec.sh

sleep 0.3

hyprctl dispatch 'hl.dsp.window.resize({ x = 250, y = 250, relative = false })'
hyprctl dispatch 'hl.dsp.window.move({ direction = "r" })'
hyprctl dispatch 'hl.dsp.window.move({ direction = "t" })'
