"""Draws docs/system-diagram.svg, the power and data wiring of Project Sunset, used in README.md.

Hand-placed boxes and wires, no dependencies: edit the coordinates and run
    python tools/system_diagram.py
whenever the wiring changes (for example when the UPS goes in, issue #29).
"""
import os
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "system-diagram.svg")
W, H = 900, 850
FONT = "font-family:ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif"
POWER, DATA = "#BA7517", "#898781"
NEUTRAL = ("#F1EFE8", "#5F5E5A", "#444441", "#5F5E5A")
GROUPS = {
    "ups": ("#EEEDFE", "#534AB7", "#3C3489", "#534AB7"),
    "carrier": ("#E1F5EE", "#0F6E56", "#085041", "#0F6E56"),
    "pi3": ("#FAEEDA", "#854F0B", "#633806", "#854F0B"),
    "nas": ("#E6F1FB", "#185FA5", "#0C447C", "#185FA5"),
}
out = []


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def box(x, y, w, h, title, sub="", colours=NEUTRAL, rx=8, dashed=False, title_y=None, sub_y=None, foot=None, tx=None):
    fill, stroke, tcol, scol = colours
    dash = ' stroke-dasharray="4 3"' if dashed else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="0.75"{dash}/>')
    cx = tx if tx is not None else x + w / 2
    ty = title_y if title_y is not None else (y + h / 2 - (9 if sub else 0))
    out.append(f'<text x="{cx}" y="{ty}" text-anchor="middle" dominant-baseline="central" fill="{tcol}" style="{FONT};font-size:14px;font-weight:600">{esc(title)}</text>')
    if sub:
        sy = sub_y if sub_y is not None else ty + 20
        out.append(f'<text x="{cx}" y="{sy}" text-anchor="middle" dominant-baseline="central" fill="{scol}" style="{FONT};font-size:12px">{esc(sub)}</text>')
    if foot:
        out.append(f'<text x="{cx}" y="{y + h - 18}" text-anchor="middle" dominant-baseline="central" fill="{scol}" style="{FONT};font-size:12px">{esc(foot)}</text>')


def wire(points, kind, both=False, label=None, label_at=None, anchor="start"):
    col = POWER if kind == "power" else DATA
    dash = "" if kind == "power" else ' stroke-dasharray="5 4"'
    pts = " ".join(f"{x},{y}" for x, y in points)
    start = ' marker-start="url(#a-%s)"' % kind if both else ""
    out.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.6"{dash} marker-end="url(#a-{kind})"{start}/>')
    if label:
        lx, ly = label_at
        out.append(f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" dominant-baseline="central" fill="#5F5E5A" style="{FONT};font-size:11px">{esc(label)}</text>')


# Sources
box(360, 70, 180, 56, "Mains", "Wall outlet")
box(60, 160, 200, 56, "DC adapter", "15-19 V, 2 A or more (to choose)", dashed=True)
box(660, 160, 200, 56, "5 V USB supply", "Replaced 2026-11-08")
wire([(450, 126), (450, 143), (160, 143), (160, 158)], "power")
wire([(450, 143), (760, 143), (760, 158)], "power")

# UPS (planned)
box(40, 250, 400, 150, "Mini-Box OpenUPS2", "Planned, issue #29 · USB 04D8:D005", GROUPS["ups"], rx=18,
    dashed=True, title_y=272, sub_y=291, foot="P1 in · P2 out 12-24 V · P3 USB · P8 SMBus")
box(70, 308, 340, 50, "3x 18650-34T in series", "Charger, balancer, cell thermistors", title_y=324, sub_y=342)
wire([(160, 216), (160, 248)], "power", label="P1", label_at=(168, 232))

# Carrier and CM4
box(40, 440, 400, 160, "MyPi XT carrier", "9-28 V DC in, RTC, external watchdog", GROUPS["carrier"], rx=18,
    title_y=462, sub_y=481)
box(60, 505, 175, 70, "CM4 sunshine", "capture, sync, netwatch", title_y=530, sub_y=550)
box(250, 505, 170, 70, "USB 2.0 ports", "UPS status, Wi-Fi dongle", title_y=530, sub_y=550)
wire([(160, 400), (160, 438)], "power", label="P2, 12-24 V", label_at=(168, 419))
wire([(400, 400), (400, 503)], "data", label="P3 USB HID", label_at=(392, 413), anchor="end")
out.append(f'<text x="392" y="427" text-anchor="end" dominant-baseline="central" fill="#5F5E5A" style="{FONT};font-size:11px">mains lost, charge %</text>')
wire([(250, 540), (237, 540)], "data", both=True)

# CM4 peripherals
box(40, 640, 190, 56, "Camera cm4wide", "IMX477, 3.2 mm lens, CAM0")
box(250, 640, 190, 56, "USB Wi-Fi dongle", "Buffalo, 2.4 GHz, ~2.4 Mbit/s")
wire([(135, 640), (135, 577)], "data", label="ribbon", label_at=(143, 610))
wire([(335, 577), (335, 638)], "data", label="USB", label_at=(343, 608))

# timelaps
box(480, 250, 390, 220, "Raspberry Pi 3 B+ timelaps", "Not on the UPS", GROUPS["pi3"], rx=18, title_y=272, sub_y=291, tx=610)
box(560, 315, 260, 56, "Pi 3 B+ timelaps", "capture, sync, built-in Wi-Fi")
box(500, 400, 170, 56, "Camera wide", "UC-517 IMX477, 6 mm lens")
box(690, 400, 160, 56, "Heatsink to fit", "SoC near its 60 °C limit", dashed=True)
wire([(760, 216), (760, 313)], "power", label="5 V USB", label_at=(768, 233))
wire([(585, 400), (585, 373)], "data", label="ribbon", label_at=(593, 388))

# Network and NAS
box(480, 510, 390, 56, "Home Wi-Fi network", "UniFi router and access point")
wire([(440, 668), (460, 668), (460, 538), (478, 538)], "data", both=True)
wire([(822, 343), (880, 343), (880, 538), (872, 538)], "data", both=True, label="Wi-Fi", label_at=(874, 490), anchor="end")
box(480, 605, 390, 175, "NAS", "SMB share //camera", GROUPS["nas"], rx=18, title_y=627, sub_y=646)
box(500, 668, 170, 56, "project_sunshine/", "frames, experiments, config")
box(690, 668, 160, 56, "Daily video job", "Docker on the NAS")
wire([(675, 566), (675, 603)], "data", label="rsync to the share", label_at=(683, 585))
wire([(672, 696), (688, 696)], "data", both=True)
box(500, 790, 170, 50, "Home Assistant", "frame-age, NAS alerts", title_y=806, sub_y=824)
box(700, 790, 150, 50, "Phone", "notifications", title_y=806, sub_y=824)
wire([(585, 724), (585, 788)], "data", label="reads the share", label_at=(593, 756))
wire([(670, 815), (698, 815)], "data")

# Legend
out.append(f'<line x1="40" y1="790" x2="80" y2="790" stroke="{POWER}" stroke-width="1.6"/>')
out.append(f'<text x="88" y="790" dominant-baseline="central" fill="#5F5E5A" style="{FONT};font-size:12px">Power</text>')
out.append(f'<line x1="40" y1="814" x2="80" y2="814" stroke="{DATA}" stroke-width="1.6" stroke-dasharray="5 4"/>')
out.append(f'<text x="88" y="814" dominant-baseline="central" fill="#5F5E5A" style="{FONT};font-size:12px">Data</text>')
out.append(f'<rect x="160" y="780" width="40" height="20" rx="4" fill="#F1EFE8" stroke="#5F5E5A" stroke-width="0.75" stroke-dasharray="4 3"/>')
out.append(f'<text x="208" y="790" dominant-baseline="central" fill="#5F5E5A" style="{FONT};font-size:12px">Planned, not fitted yet</text>')
out.append(f'<text x="40" y="34" fill="#2C2C2A" style="{FONT};font-size:18px;font-weight:600">Project Sunset: power and data</text>')
out.append(f'<text x="40" y="56" fill="#5F5E5A" style="{FONT};font-size:12px">Both cameras look west through the same window. Frames go to the NAS; nothing is posted yet.</text>')

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img">
<title>Project Sunset power and data diagram</title>
<desc>Mains feeds a DC adapter into the planned OpenUPS2 with three 18650 cells; its output powers the MyPi XT carrier with the CM4 sunshine, and its USB port reports status to the CM4. The CM4 drives camera cm4wide and reaches the Wi-Fi network through a USB dongle. The Pi 3 B+ timelaps is on its own 5 V supply with camera wide and built-in Wi-Fi. Both sync frames to the NAS, where the daily video job runs and Home Assistant reads the share and notifies the phone.</desc>
<defs>
<marker id="a-power" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" stroke="{POWER}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker>
<marker id="a-data" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" stroke="{DATA}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker>
</defs>
<rect x="0" y="0" width="{W}" height="{H}" rx="14" fill="#FFFFFF"/>
''' + "\n".join(out) + "\n</svg>\n"
open(OUT, "w", encoding="utf-8", newline="\n").write(svg)
