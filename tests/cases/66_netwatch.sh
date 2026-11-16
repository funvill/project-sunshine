# sunset-netwatch.sh: brings a hung Wi-Fi dongle back (CM4 outage, 2026-11-13).
# Fake sysfs: wlan0 is interface 1.0 of USB device 1-1.3.
net_env() {
  fresh_env
  export NETWATCH=1 NETWATCH_STATE="$W/run" NETWATCH_LOG="$W/netwatch.log" NETWATCH_SYSFS="$W/sys"
  export NETWATCH_REBOOT_MARK="$W/.netwatch-reboot" NETWATCH_SETTLE_S=0
  unset NETWATCH_IFACE NETWATCH_TARGET STUB_GATEWAY
  export STUB_PING=ok
  mkdir -p "$W/sys/devices/usb1/1-1/1-1.3/1-1.3:1.0" "$W/sys/class/net/wlan0" "$W/sys/bus/usb/drivers/usb"
  # Git Bash copies instead of linking unless asked for a native link; ignored on Linux.
  MSYS=winsymlinks:nativestrict ln -s "$W/sys/devices/usb1/1-1/1-1.3/1-1.3:1.0" "$W/sys/class/net/wlan0/device"
  : > "$W/sys/bus/usb/drivers/usb/unbind"; : > "$W/sys/bus/usb/drivers/usb/bind"
}
netwatch() { NETWATCH_UPTIME="$1" bash "$SRC/sunset-netwatch.sh"; }  # uptime in seconds

section "netwatch: off unless NETWATCH=1"
net_env; export NETWATCH=0 STUB_PING=fail
netwatch 600; netwatch 4000
check "does nothing when off" test ! -s "$STUB_CALLS"
unset NETWATCH; netwatch 4000
check "off by default" test ! -s "$STUB_CALLS"

section "netwatch: network up"
net_env
netwatch 600; rc=$?
check "exits 0" test "$rc" = 0
check "pings the default gateway through wlan0" grep -q 'ping .*-I wlan0.* 192.0.2.1' "$STUB_CALLS"
check "writes nothing to the SD when all is well" test ! -e "$NETWATCH_LOG"

section "netwatch: short outage is left alone"
net_env; export STUB_PING=fail
netwatch 1000; netwatch 1300
check "no reset before 10 minutes" test ! -s "$W/sys/bus/usb/drivers/usb/unbind"
check "no reboot" sh -c "! grep -q reboot '$STUB_CALLS'"
export STUB_PING=ok; netwatch 1400
check "logs the recovery" grep -q 'network back after' "$NETWATCH_LOG"
check "clears its state" test ! -e "$NETWATCH_STATE"

section "netwatch: resets the dongle after 10 minutes"
net_env; export STUB_PING=fail
netwatch 1000; netwatch 1610
check "unbinds the dongle's USB device" grep -qx '1-1.3' "$W/sys/bus/usb/drivers/usb/unbind"
check "binds it again" grep -qx '1-1.3' "$W/sys/bus/usb/drivers/usb/bind"
check "logs the reset" grep -q 'reset the Wi-Fi dongle (USB 1-1.3)' "$NETWATCH_LOG"
: > "$W/sys/bus/usb/drivers/usb/unbind"; netwatch 1730
check "resets only once per outage" test ! -s "$W/sys/bus/usb/drivers/usb/unbind"

section "netwatch: no gateway counts as down"
net_env; export STUB_GATEWAY="" STUB_PING=ok
netwatch 1000; netwatch 1610
check "resets when there is no default route" grep -qx '1-1.3' "$W/sys/bus/usb/drivers/usb/unbind"

section "netwatch: reboots after 30 minutes, at most every 6 hours"
net_env; export STUB_PING=fail
netwatch 4000; netwatch 4000; netwatch 5810
check "reboots" grep -q 'systemctl reboot' "$STUB_CALLS"
check "logs why" grep -q 'rebooting: no network for 30 min' "$NETWATCH_LOG"
check "remembers the reboot on the SD" test -e "$NETWATCH_REBOOT_MARK"
: > "$STUB_CALLS"; rm -rf "$NETWATCH_STATE"
netwatch 4000; netwatch 5810
check "no second reboot within 6 hours" sh -c "! grep -q 'systemctl reboot' '$STUB_CALLS'"
touch -d '7 hours ago' "$NETWATCH_REBOOT_MARK"; netwatch 5900
check "reboots again after 6 hours" grep -q 'systemctl reboot' "$STUB_CALLS"

section "netwatch: units"
check "service runs the script as root" grep -qx 'ExecStart=/home/pi/sunset/sunset-netwatch.sh' "$SRC/systemd/sunset-netwatch.service"
check "service has no User= (needs root)" sh -c "! grep -q '^User=' '$SRC/systemd/sunset-netwatch.service'"
check "service reads sunset.env" grep -qx 'EnvironmentFile=-/home/pi/sunset/sunset.env' "$SRC/systemd/sunset-netwatch.service"
check "service logs next to the frames" grep -qx 'Environment=NETWATCH_LOG=/home/pi/sunset/netwatch.log' "$SRC/systemd/sunset-netwatch.service"
check "timer every 2 minutes" grep -qx 'OnUnitActiveSec=2min' "$SRC/systemd/sunset-netwatch.timer"
check "install.sh installs the units" grep -q 'sunset-netwatch.service sunset-netwatch.timer' "$SRC/install.sh"
check "install.sh enables the timer (the script does nothing without NETWATCH=1)" grep -q 'enable --now sunset-netwatch.timer' "$SRC/install.sh"
unset NETWATCH NETWATCH_STATE NETWATCH_LOG NETWATCH_SYSFS NETWATCH_REBOOT_MARK NETWATCH_SETTLE_S STUB_PING STUB_GATEWAY
