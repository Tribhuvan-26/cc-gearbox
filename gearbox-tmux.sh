#!/bin/sh
# Start a tmux session: Claude Code on the left, the shifter in a 42-column pane on the right.
session="${1:-work}"
pane=$(tmux new-session -d -s "$session" -n code -P -F '#{pane_id}' claude) || exit 1
tmux split-window -h -l 42 -t "$pane" "gearbox --target $pane"
tmux select-pane -t "$pane"
exec tmux attach -t "$session"
