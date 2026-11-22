# needs: 80_frame_age
# Free space on the NAS share (issue #7): homeassistant/sunset_nas_free.sh, under sh and busybox sh.
section "nas free space: whole GB from df -Pk"
W="$(mktemp -d)"; mkdir -p "$W/project_sunshine"
df_stub() { printf '#!/bin/sh\necho "Filesystem 1024-blocks Used Available Capacity Mounted on"\necho "//nas/camera 11000000000 10000000000 %s 91%% /share/camera"\n' "$1" > "$W/df-stub"; }
export FREE_PATH="$W/project_sunshine" DF="sh $W/df-stub"
df_stub 134217728                      # exactly 128 GB in KiB
ha_out "128 GB free" 128 "$HA/sunset_nas_free.sh"
df_stub 135000000                      # 128.7 GB: rounds down, never up
ha_out "rounds down" 128 "$HA/sunset_nas_free.sh"
df_stub 1048575
ha_out "just under 1 GB reads 0" 0 "$HA/sunset_nas_free.sh"
df_stub 11534336000                    # 11,000 GB
ha_out "large shares" 11000 "$HA/sunset_nas_free.sh"

section "nas free space: anything unusable is unknown"
df_stub notanumber
ha_fails "df gives a non-number" "$HA/sunset_nas_free.sh"
printf '#!/bin/sh\nexit 1\n' > "$W/df-stub"
ha_fails "df fails" "$HA/sunset_nas_free.sh"
df_stub 134217728
export FREE_PATH="$W/no-such-folder"
ha_fails "the share folder is missing (unmounted)" "$HA/sunset_nas_free.sh"
unset FREE_PATH DF

section "nas free space: the real df on this machine"
export FREE_PATH="$W/project_sunshine"
for shell in $HA_SHELLS; do
  v="$(ha_run "$shell" "$HA/sunset_nas_free.sh" 2>/dev/null)"
  check "a number from the real df [$shell]" bash -c "[[ '$v' =~ ^[0-9]+\$ ]]"
done
unset FREE_PATH
