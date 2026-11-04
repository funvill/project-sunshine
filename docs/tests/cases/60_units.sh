section "systemd units"
# systemd has no trailing comments: "Key=value # note" is taken as the value and, for a
# setting like TimeoutStartSec, rejected and silently ignored.
check "no comment after a setting" \
  sh -c "! grep -nE '^[A-Za-z]+=.*[[:space:]]#' '$SRC'/systemd/*"
check "capture service timeout is set" grep -qx 'TimeoutStartSec=300' "$SRC/systemd/sunset-capture.service"
