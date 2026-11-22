"""Frame file names, shared by the tools: <cam>_<YYYYMMDDTHHMMSSZ>[_night|_ev0|_ev-2].jpg

The time in the name is UTC. kind is None for a regular or dense frame, 'night' for the night
frame of a dark slot, and 'ev0' or 'ev-2' for the sunset bracket (BRACKET=1). nas/sunset-daily.py
keeps its own copy, since it runs on its own.
"""
import re
from datetime import datetime, timezone

NAME = re.compile(r"^(?P<cam>[A-Za-z0-9-]+)_(?P<t>\d{8}T\d{6}Z)(?:_(?P<kind>night|ev0|ev-2))?\.jpg$")


def parse_time(text):
    """'20261112T001500Z' -> that time as an aware UTC datetime."""
    return datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def parse(name):
    """(camera, UTC datetime, kind) for a frame's JPEG file name, or None if it isn't one."""
    m = NAME.match(name)
    if not m:
        return None
    return m.group("cam"), parse_time(m.group("t")), m.group("kind")
