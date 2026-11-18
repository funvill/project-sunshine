section "reports (tools/build_reports.py)"
check "tests/test_build_reports.py" python3 -I "$HERE/test_build_reports.py"
check "no NAS path or LAN address in reports/" sh -c "! grep -rqE '//[A-Za-z0-9_.-]+/camera|192\.168\.|nas\.local' '$SRC/../reports'"
