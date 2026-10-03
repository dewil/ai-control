# shellcheck shell=bash
# Source-only installer helper. Never runs the retired operator or removes data.
# Callers supply OS_KIND, BIN_DIR, UNIT_DIR and optional DRY_RUN.
retire_canon_maintainer() {
  local name=claude-agent-canon-maintainer unit state load proof path present=0
  local -a absent_units=() units=("$name.timer" "$name.service")
  if [[ "$OS_KIND" == linux ]]; then
    [[ ! -e "$BIN_DIR/$name" && ! -L "$BIN_DIR/$name" ]] || present=1
    for unit in "${units[@]}"; do
      if [[ -e "$UNIT_DIR/$unit" || -L "$UNIT_DIR/$unit" ]]; then
        present=1
      fi
      for path in "$UNIT_DIR"/*.wants/"$unit" "$UNIT_DIR"/*.requires/"$unit"; do
        [[ ! -e "$path" && ! -L "$path" ]] || present=1
      done
    done
    # User manager can retain a loaded unit after its on-disk file is gone.
    # With no owned files, an unavailable manager is harmless: nothing is removed.
    if [[ $present -eq 0 ]]; then
      for unit in "${units[@]}"; do
        if proof=$(systemctl --user show "$unit" --property=LoadState,ActiveState 2>/dev/null); then
          load=$(printf '%s\n' "$proof" | sed -n 's/^LoadState=//p')
          state=$(printf '%s\n' "$proof" | sed -n 's/^ActiveState=//p')
          if [[ -n "$load" && -n "$state" && "$load:$state" != not-found:inactive ]]; then
            present=1
          fi
        fi
      done
    fi
    if [[ $present -eq 1 ]]; then
      if [[ ${DRY_RUN:-0} -eq 1 ]]; then
        printf 'DRY: retire %s timer/service after verified stop; daemon-reload\n' "$name"
      else
        # Stop the timer first so it cannot launch another service during cleanup.
        for unit in "${units[@]}"; do
          if ! proof=$(systemctl --user show "$unit" --property=LoadState,ActiveState); then
            echo "ERROR: cannot inspect retired unit $unit; files preserved" >&2
            return 1
          fi
          load=$(printf '%s\n' "$proof" | sed -n 's/^LoadState=//p')
          state=$(printf '%s\n' "$proof" | sed -n 's/^ActiveState=//p')
          if [[ -z "$load" || -z "$state" ]]; then
            echo "ERROR: incomplete retired unit state for $unit; files preserved" >&2
            return 1
          fi
          if [[ "$load:$state" == not-found:inactive ]]; then
            absent_units+=("$unit")
          else
            if ! systemctl --user stop "$unit"; then
              echo "ERROR: cannot stop retired unit $unit; files preserved" >&2
              return 1
            fi
          fi
          if ! proof=$(systemctl --user show "$unit" --property=LoadState,ActiveState); then
            echo "ERROR: cannot verify retired unit $unit stopped; files preserved" >&2
            return 1
          fi
          load=$(printf '%s\n' "$proof" | sed -n 's/^LoadState=//p')
          state=$(printf '%s\n' "$proof" | sed -n 's/^ActiveState=//p')
          case "$load:$state" in
            loaded:inactive|loaded:failed|masked:inactive|not-found:inactive) ;;
            *) echo "ERROR: retired unit $unit not confirmed stopped ($load/$state)" >&2; return 1 ;;
          esac
        done
        for unit in "${units[@]}"; do
          # disable rejects masked or missing units on some systemd versions.
          # Their owned enable links are removed explicitly below.
          if [[ ! -e "$UNIT_DIR/$unit" && ! -L "$UNIT_DIR/$unit" ]]; then
            continue
          fi
          if [[ -L "$UNIT_DIR/$unit" && $(readlink "$UNIT_DIR/$unit") == /dev/null ]]; then
            continue
          fi
          if [[ " ${absent_units[*]} " == *" $unit "* ]]; then
            continue
          fi
          systemctl --user disable "$unit" || return 1
        done
        for unit in "${units[@]}"; do
          rm -f "$UNIT_DIR/$unit" || return 1
          for path in "$UNIT_DIR"/*.wants/"$unit" "$UNIT_DIR"/*.requires/"$unit"; do
            [[ -e "$path" || -L "$path" ]] || continue
            rm -f "$path" || return 1
          done
        done
        systemctl --user daemon-reload || return 1
      fi
    fi
  fi
  if [[ -e "$BIN_DIR/$name" || -L "$BIN_DIR/$name" ]]; then
    if [[ ${DRY_RUN:-0} -eq 1 ]]; then
      printf 'DRY: rm -f %q\n' "$BIN_DIR/$name"
    else
      rm -f "$BIN_DIR/$name" || return 1
    fi
  fi
}
