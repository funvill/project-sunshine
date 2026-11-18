section "camera check (tools/camera_check.py)"
check "tests/test_camera_check.py" python3 -I "$HERE/test_camera_check.py"
check "hosts file is git-ignored" grep -qx 'tools/camera_check.hosts' "$SRC/../.gitignore"
