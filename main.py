#!/usr/bin/env python3
"""
network-documentr — Cisco 'show running-config' → DOCX generator
"""

import re
import os
import sys
from datetime import date
from pathlib import Path

from docx import Document
from docx.shared import Pt, Mm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ── Colours ───────────────────────────────────────────────────────────────────
C_DARK_BLUE   = "1A2B4A"
C_MID_BLUE    = "2C4A7C"
C_ACCENT_BLUE = "3B6BA5"
C_LIGHT_BLUE  = "E8EFF8"
C_ROW_ALT     = "F5F8FC"
C_PO_ROW      = "EEF2FF"
C_VLAN_ROW    = "F0FDF4"
C_VLAN_DEAD   = "ECECEC"
C_BORDER      = "CBD5E1"
C_WHITE       = "FFFFFF"

RGB_WHITE      = RGBColor(0xFF, 0xFF, 0xFF)
RGB_DARK_TEXT  = RGBColor(0x1E, 0x29, 0x3B)
RGB_GREY_LABEL = RGBColor(0x94, 0xA3, 0xB8)
RGB_AMBER      = RGBColor(0xB4, 0x53, 0x09)
RGB_DEAD_TEXT  = RGBColor(0xB0, 0xB0, 0xB0)

# A4 portrait with 14 mm margins → 182 mm usable width
USABLE_MM = 182.0

# ── Interface classification ──────────────────────────────────────────────────
PHYSICAL_PREFIXES = (
    "GigabitEthernet", "FastEthernet", "TenGigabitEthernet",
    "TwentyFiveGigE", "FortyGigabitEthernet", "HundredGigE", "Management",
)
LOGICAL_PREFIXES = ("Port-channel", "port-channel", "Vlan", "Loopback")

# ═════════════════════════════════════════════════════════════════════════════
#  PARSER
# ═════════════════════════════════════════════════════════════════════════════

def read_file_safe(path: str) -> str:
    for enc in ("utf-8", "cp1251", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def short_iface(name: str) -> str:
    """GigabitEthernet1/0/1 → Gi1/0/1, etc."""
    for long, short in [
        ("GigabitEthernet",     "Gi"),
        ("FastEthernet",        "Fa"),
        ("TenGigabitEthernet",  "Te"),
        ("TwentyFiveGigE",      "Twe"),
        ("FortyGigabitEthernet","Fo"),
        ("HundredGigE",         "Hu"),
        ("Port-channel",        "Po"),
        ("port-channel",        "Po"),
        ("Vlan",                "Vlan"),
        ("Loopback",            "Lo"),
        ("Management",          "Mgmt"),
    ]:
        if name.startswith(long):
            return short + name[len(long):]
    return name


def _collect_used_vlans(interfaces: list) -> tuple:
    """Return (used_ids: set[str], all_used: bool).
    used_ids — VLAN IDs referenced on any interface.
    all_used  — True if any trunk allows 'all' or an unexpandable wide range.
    """
    used = set()
    all_used = False
    for iface in interfaces:
        for field in ("access_vlan", "native_vlan", "voice_vlan"):
            val = iface.get(field, "")
            if val:
                used.add(val)
        trunk = iface.get("trunk_vlans", "")
        if trunk:
            for part in trunk.split(","):
                part = part.strip()
                if not part or part.lower() == "none":
                    continue
                if part.lower() == "all":
                    all_used = True
                    continue
                m = re.match(r"^(\d+)-(\d+)$", part)
                if m:
                    lo, hi = int(m.group(1)), int(m.group(2))
                    if hi - lo <= 1000:
                        used.update(str(i) for i in range(lo, hi + 1))
                    else:
                        all_used = True
                elif re.match(r"^\d+$", part):
                    used.add(part)
    return used, all_used


def parse_showrun(text: str) -> dict:
    result = {"hostname": "", "mgmt_ip": "", "interfaces": []}

    m = re.search(r"^hostname\s+(\S+)", text, re.MULTILINE)
    if m:
        result["hostname"] = m.group(1)

    m = re.search(r"^ip ssh source-interface\s+(\S+)", text, re.MULTILINE)
    result["ssh_source_iface"] = m.group(1) if m else ""

    iface_blocks = re.split(r"(?=^interface\s)", text, flags=re.MULTILINE)

    for block in iface_blocks:
        if not block.strip().startswith("interface"):
            continue

        lines = block.strip().splitlines()
        iface_name = lines[0].split(None, 1)[1].strip()

        iface = {
            "name":            iface_name,
            "description":     "",
            "mode":            "",
            "access_vlan":     "",
            "native_vlan":     "",
            "trunk_vlans":     "",
            "ip_address":      "",
            "shutdown":        False,
            "notes":           "",
            "iface_class":     "physical",
            "voice_vlan":              "",
            "stp_portfast":            False,
            "stp_rootguard":           False,
            "stp_bpduguard":           False,
            "port_security":           False,
            "port_security_max":       "",
            "port_security_violation": "",
            "port_security_macs":      [],
            "port_security_sticky":    False,
        }

        for line in lines[1:]:
            line = line.strip()

            if line.startswith("description "):
                iface["description"] = line[len("description "):].strip()

            elif line == "switchport mode access":
                iface["mode"] = "access"

            elif line == "switchport mode trunk":
                iface["mode"] = "trunk"

            elif re.match(r"no switchport", line):
                iface["mode"] = "routed"

            elif re.match(r"switchport access vlan (\d+)", line):
                iface["access_vlan"] = re.search(r"\d+", line).group()

            elif re.match(r"switchport trunk native vlan (\d+)", line):
                iface["native_vlan"] = re.search(r"\d+", line).group()

            elif re.match(r"switchport trunk allowed vlan", line):
                vlans = re.sub(r"switchport trunk allowed vlan\s*(add\s*)?", "", line).strip()
                if iface["trunk_vlans"]:
                    iface["trunk_vlans"] += "," + vlans
                else:
                    iface["trunk_vlans"] = vlans

            elif re.match(r"ip address ", line):
                iface["ip_address"] = line[len("ip address "):].strip()

            elif line == "shutdown":
                iface["shutdown"] = True

            elif re.match(r"channel-group (\d+)", line):
                po_num = re.search(r"channel-group (\d+)", line).group(1)
                iface["notes"] = f"Po{po_num} member"

            elif re.match(r"switchport voice vlan (\d+)", line):
                iface["voice_vlan"] = re.search(r"switchport voice vlan (\d+)", line).group(1)

            elif re.match(r"spanning-tree portfast", line):
                iface["stp_portfast"] = True

            elif line == "spanning-tree guard root":
                iface["stp_rootguard"] = True

            elif line == "spanning-tree bpduguard enable":
                iface["stp_bpduguard"] = True

            elif re.match(r"switchport port-security maximum (\d+)", line):
                iface["port_security_max"] = re.search(r"switchport port-security maximum (\d+)", line).group(1)
                iface["port_security"] = True

            elif re.match(r"switchport port-security violation (\S+)", line):
                iface["port_security_violation"] = re.search(r"switchport port-security violation (\S+)", line).group(1)
                iface["port_security"] = True

            elif re.match(r"switchport port-security mac-address sticky", line):
                iface["port_security_sticky"] = True
                iface["port_security"] = True
                m_sticky = re.search(r"switchport port-security mac-address sticky\s+(\S+)", line)
                if m_sticky:
                    iface["port_security_macs"].append(m_sticky.group(1))

            elif re.match(r"switchport port-security mac-address (\S+)", line):
                mac = re.search(r"switchport port-security mac-address (\S+)", line).group(1)
                iface["port_security_macs"].append(mac)
                iface["port_security"] = True

            elif line == "switchport port-security":
                iface["port_security"] = True

        # Build notes: Po member → Voice:X → PortFast → RootGuard → BPDUGuard → PortSec … → shutdown
        notes_parts = [iface["notes"]] if iface["notes"] else []
        if iface["voice_vlan"]:   notes_parts.append(f"Voice:{iface['voice_vlan']}")
        if iface["stp_portfast"]: notes_parts.append("PortFast")
        if iface["stp_rootguard"]:notes_parts.append("RootGuard")
        if iface["stp_bpduguard"]:notes_parts.append("BPDUGuard")
        if iface["port_security"]:
            ps_parts = ["PortSec"]
            if iface["port_security_max"]:       ps_parts.append(f"max:{iface['port_security_max']}")
            if iface["port_security_violation"]: ps_parts.append(f"violation:{iface['port_security_violation']}")
            if iface["port_security_sticky"]:    ps_parts.append("sticky")
            notes_parts.append(" ".join(ps_parts))
            for mac in iface["port_security_macs"]:
                notes_parts.append(f"MAC:{mac}")
        if iface["shutdown"]:     notes_parts.append("shutdown")
        iface["notes"] = "\n".join(notes_parts)

        # Mode fallback
        if not iface["mode"]:
            if iface["ip_address"] or iface_name.lower().startswith("vlan"):
                iface["mode"] = "routed"
            elif any(iface_name.lower().startswith(p.lower())
                     for p in ("port-channel",)):
                iface["mode"] = "trunk"

        # Classify physical vs logical
        if any(iface_name.startswith(p) for p in PHYSICAL_PREFIXES):
            iface["iface_class"] = "physical"
        elif any(iface_name.startswith(p) for p in LOGICAL_PREFIXES):
            iface["iface_class"] = "logical"
        else:
            iface["iface_class"] = "physical"

        result["interfaces"].append(iface)

    # Parse VLAN definitions (single-VID blocks only; skip ranges, "vlan database")
    result["vlans"] = []
    vlan_blocks = re.split(r"(?=^vlan\s)", text, flags=re.MULTILINE)
    for vblock in vlan_blocks:
        lines_v = vblock.strip().splitlines()
        if not lines_v:
            continue
        m_vid = re.match(r"^vlan\s+(\d+)$", lines_v[0].strip())
        if not m_vid:
            continue
        vlan_name = ""
        for vl in lines_v[1:]:
            if vl.strip().startswith("name "):
                vlan_name = vl.strip()[len("name "):].strip()
                break
        result["vlans"].append({"id": m_vid.group(1), "name": vlan_name})

    # Mark each VLAN as used (referenced on any port) or dead
    used_ids, trunk_all = _collect_used_vlans(result["interfaces"])
    for vlan in result["vlans"]:
        vlan["used"] = trunk_all or vlan["id"] in used_ids
    result["vlans"].sort(key=lambda v: int(v["id"]))

    # Resolve MGMT IP: prefer SSH source-interface, fallback to first IP found
    ssh_src = result.get("ssh_source_iface", "")
    for iface in result["interfaces"]:
        if ssh_src and iface["name"] == ssh_src and iface["ip_address"]:
            result["mgmt_ip"] = iface["ip_address"].split()[0]
            break
    if not result["mgmt_ip"]:
        for iface in result["interfaces"]:
            if iface["ip_address"]:
                result["mgmt_ip"] = iface["ip_address"].split()[0]
                break

    return result


def parse_version_inventory(text: str) -> dict:
    """Extract model and serial from show inventory / show version blocks."""
    model = ""
    serial = ""

    # Priority 1: show inventory — first PID line (chassis / main unit)
    m = re.search(r"^PID:\s*(\S+)\s*,.*SN:\s*(\S+)", text, re.MULTILINE)
    if m:
        model = m.group(1)
        serial = m.group(2)

    # Priority 2: show version — Model number
    if not model:
        m = re.search(r"^Model [Nn]umber\s*:\s*(\S+)", text, re.MULTILINE)
        if m:
            model = m.group(1)

    # Priority 3: show version — System serial number
    if not serial:
        m = re.search(r"^System [Ss]erial [Nn]umber\s*:\s*(\S+)", text, re.MULTILINE)
        if m:
            serial = m.group(1)

    # Priority 4: show version — Processor board ID (older platforms e.g. 3750)
    if not serial:
        m = re.search(r"^Processor board ID\s+(\S+)", text, re.MULTILINE)
        if m:
            serial = m.group(1)

    return {"model": model, "serial": serial}


def classify_interfaces(interfaces: list):
    physical = [i for i in interfaces if i["iface_class"] == "physical"]
    logical  = [i for i in interfaces if i["iface_class"] == "logical"]
    return physical, logical


def format_load_status(parsed: dict) -> str:
    """Build status bar string shown after a config file is loaded."""
    physical, logical = classify_interfaces(parsed["interfaces"])
    po    = sum(1 for i in logical if i["name"].lower().startswith("port-channel"))
    vlans = sum(1 for i in logical if i["name"].startswith("Vlan"))
    loops = sum(1 for i in logical if i["name"].startswith("Loopback"))
    parts = []
    if parsed.get("mgmt_ip"):
        parts.append(f"MGMT: {parsed['mgmt_ip']}")
    parts.append(f"Порти: {len(physical)}")
    if po:    parts.append(f"Po: {po}")
    if vlans: parts.append(f"VLAN: {vlans}")
    if loops: parts.append(f"Lo: {loops}")
    return "  ·  ".join(parts)


# ═════════════════════════════════════════════════════════════════════════════
#  XML HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def set_cell_bg(cell, hex_color: str):
    """Apply solid background fill to a table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    for el in tcPr.findall(qn("w:shd")):
        tcPr.remove(el)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"),   "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"),  hex_color)
    tcPr.append(shd)


def set_table_borders(table, color_hex: str = "CBD5E1",
                      sz: str = "4", val: str = "single"):
    """Set all table borders."""
    tblPr = table._tbl.tblPr
    for el in tblPr.findall(qn("w:tblBorders")):
        tblPr.remove(el)
    tblBorders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b = OxmlElement(f"w:{side}")
        b.set(qn("w:val"),   val)
        b.set(qn("w:sz"),    sz)
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), color_hex)
        tblBorders.append(b)
    tblPr.append(tblBorders)


def set_table_fixed_layout(table):
    """Force fixed column widths (no autofit)."""
    tblPr = table._tbl.tblPr
    for el in tblPr.findall(qn("w:tblLayout")):
        tblPr.remove(el)
    el = OxmlElement("w:tblLayout")
    el.set(qn("w:type"), "fixed")
    tblPr.append(el)


def set_table_width(table, width_mm: float):
    """Set total table width."""
    tblPr = table._tbl.tblPr
    for el in tblPr.findall(qn("w:tblW")):
        tblPr.remove(el)
    el = OxmlElement("w:tblW")
    el.set(qn("w:w"),    str(int(width_mm * 56.7)))
    el.set(qn("w:type"), "dxa")
    tblPr.append(el)


def set_cell_margins_table(table, top=40, left=60, bottom=40, right=60):
    """Set default cell padding for the whole table (twips)."""
    tblPr = table._tbl.tblPr
    for el in tblPr.findall(qn("w:tblCellMar")):
        tblPr.remove(el)
    mar = OxmlElement("w:tblCellMar")
    for side, val in [("top", top), ("left", left),
                      ("bottom", bottom), ("right", right)]:
        n = OxmlElement(f"w:{side}")
        n.set(qn("w:w"),    str(val))
        n.set(qn("w:type"), "dxa")
        mar.append(n)
    tblPr.append(mar)


def set_cell_margins(cell, top=60, left=80, bottom=60, right=60):
    """Set padding on a single cell (twips)."""
    tcPr  = cell._tc.get_or_add_tcPr()
    for el in tcPr.findall(qn("w:tcMar")):
        tcPr.remove(el)
    mar = OxmlElement("w:tcMar")
    for side, val in [("top", top), ("left", left),
                      ("bottom", bottom), ("right", right)]:
        n = OxmlElement(f"w:{side}")
        n.set(qn("w:w"),    str(val))
        n.set(qn("w:type"), "dxa")
        mar.append(n)
    tcPr.append(mar)


def set_repeat_header_row(row):
    """Mark row to repeat as header on each page."""
    trPr = row._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:tblHeader"))


def set_row_min_height(row, height_twips: int = 240):
    """Set minimum row height (240 twips ≈ 4.2 mm)."""
    trPr = row._tr.get_or_add_trPr()
    for el in trPr.findall(qn("w:trHeight")):
        trPr.remove(el)
    el = OxmlElement("w:trHeight")
    el.set(qn("w:val"),   str(height_twips))
    el.set(qn("w:hRule"), "atLeast")
    trPr.append(el)


def _set_run_font(run, font_name: str = "Calibri"):
    """Set font with full Cyrillic support (w:cs attribute)."""
    rPr    = run._r.get_or_add_rPr()
    rFonts = OxmlElement("w:rFonts")
    rFonts.set(qn("w:ascii"),    font_name)
    rFonts.set(qn("w:hAnsi"),    font_name)
    rFonts.set(qn("w:cs"),       font_name)
    rFonts.set(qn("w:eastAsia"), font_name)
    existing = rPr.find(qn("w:rFonts"))
    if existing is not None:
        rPr.remove(existing)
    rPr.insert(0, rFonts)


def _write_cell(cell, text: str, bold: bool = False,
                color: RGBColor = None, font_size: float = 7,
                align=WD_ALIGN_PARAGRAPH.LEFT):
    """Write text into the first paragraph of a cell with full styling.
    '\\n' in text produces in-cell line breaks (w:br)."""
    para = cell.paragraphs[0]
    para.clear()
    para.paragraph_format.space_before = Pt(0)
    para.paragraph_format.space_after  = Pt(0)
    para.alignment = align
    parts = (text or "").split("\n")
    for i, part in enumerate(parts):
        run = para.add_run(part)
        run.bold = bold
        run.font.size = Pt(font_size)
        if color:
            run.font.color.rgb = color
        _set_run_font(run)
        if i < len(parts) - 1:
            br = OxmlElement("w:br")
            run._r.append(br)


# ═════════════════════════════════════════════════════════════════════════════
#  DOCX BUILDERS
# ═════════════════════════════════════════════════════════════════════════════

def _add_header_block(doc, hostname: str):
    """Dark-blue banner with hostname."""
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_table_fixed_layout(tbl)
    set_table_width(tbl, USABLE_MM)
    set_table_borders(tbl, val="none")

    cell = tbl.cell(0, 0)
    cell.width = Mm(USABLE_MM)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    set_cell_bg(cell, C_DARK_BLUE)
    set_cell_margins(cell, top=120, left=120, bottom=120, right=120)
    _write_cell(cell, hostname, bold=True, color=RGB_WHITE, font_size=16)

    sp = doc.add_paragraph()
    sp.paragraph_format.space_before = Pt(0)
    sp.paragraph_format.space_after  = Pt(2)


def _add_info_block(doc, model: str, serial: str, mgmt_ip: str, updated: str):
    """Light-blue info row: Model | Serial | MGMT IP | Updated."""
    COL_W  = USABLE_MM / 4
    labels = ["МОДЕЛЬ / ВЕНДОР", "СЕРІЙНИЙ НОМЕР", "MGMT IP-АДРЕСА", "ОНОВЛЕНО"]
    values = [model or "—", serial or "—", mgmt_ip or "—", updated]

    tbl = doc.add_table(rows=1, cols=4)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_table_fixed_layout(tbl)
    set_table_width(tbl, USABLE_MM)
    set_table_borders(tbl, color_hex=C_BORDER, sz="4")

    for ci, (lbl, val) in enumerate(zip(labels, values)):
        cell = tbl.cell(0, ci)
        cell.width = Mm(COL_W)
        set_cell_bg(cell, C_LIGHT_BLUE)
        set_cell_margins(cell, top=60, left=80, bottom=60, right=40)

        # label — first paragraph already present in cell
        lp = cell.paragraphs[0]
        lp.clear()
        lp.paragraph_format.space_before = Pt(0)
        lp.paragraph_format.space_after  = Pt(1)
        lr = lp.add_run(lbl)
        lr.font.size = Pt(8)
        lr.font.color.rgb = RGB_GREY_LABEL
        _set_run_font(lr)

        # value — second paragraph
        vp = cell.add_paragraph()
        vp.paragraph_format.space_before = Pt(0)
        vp.paragraph_format.space_after  = Pt(0)
        vr = vp.add_run(val)
        vr.bold = True
        vr.font.size = Pt(10)
        vr.font.color.rgb = RGB_DARK_TEXT
        _set_run_font(vr)

    sp = doc.add_paragraph()
    sp.paragraph_format.space_before = Pt(0)
    sp.paragraph_format.space_after  = Pt(2)


def _add_section_header(doc, text: str):
    """Mid-blue section label bar."""
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_table_fixed_layout(tbl)
    set_table_width(tbl, USABLE_MM)
    set_table_borders(tbl, val="none")

    cell = tbl.cell(0, 0)
    cell.width = Mm(USABLE_MM)
    set_cell_bg(cell, C_MID_BLUE)
    set_cell_margins(cell, top=60, left=100, bottom=60, right=60)
    _write_cell(cell, text, bold=True, color=RGB_WHITE, font_size=10)


def _add_interface_table(doc, interfaces: list, logical: bool = False):
    """
    Compact interface table.
    Physical (logical=False): ПОРТ | ОПИС | РЕЖИМ | ACC/NAT VLAN | TRUNK VLANs | ПРИМІТКА
    Logical  (logical=True):  ПОРТ | ОПИС | РЕЖИМ | IP-АДРЕСА | ПРИМІТКА
    """
    if not interfaces:
        sp = doc.add_paragraph("(немає інтерфейсів)")
        sp.paragraph_format.space_before = Pt(2)
        sp.paragraph_format.space_after  = Pt(4)
        return

    if logical:
        # 5 cols, sum = 182 mm
        COL_W_MM = [18, 82, 22, 37, 23]
        COL_HDR  = ["ПОРТ", "ОПИС / ПРИЗНАЧЕННЯ", "РЕЖИМ", "IP-АДРЕСА", "ПРИМІТКА"]
        CENTER   = {0, 2, 3, 4}
    else:
        # 6 cols, sum = 182 mm
        COL_W_MM = [18, 45, 22, 32, 42, 23]
        COL_HDR  = ["ПОРТ", "ОПИС / ПРИЗНАЧЕННЯ", "РЕЖИМ",
                    "ACC/NAT VLAN", "TRUNK VLANs", "ПРИМІТКА"]
        CENTER   = {0, 2, 3, 4, 5}

    n_cols = len(COL_W_MM)
    tbl = doc.add_table(rows=1, cols=n_cols)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_table_fixed_layout(tbl)
    set_table_width(tbl, USABLE_MM)
    set_table_borders(tbl, color_hex=C_BORDER, sz="4")
    set_cell_margins_table(tbl, top=15, left=60, bottom=15, right=40)

    # ── Header row ────────────────────────────────────────────────────────
    hdr = tbl.rows[0]
    set_repeat_header_row(hdr)
    set_row_min_height(hdr, 400)

    for ci, (h, w) in enumerate(zip(COL_HDR, COL_W_MM)):
        c = hdr.cells[ci]
        c.width = Mm(w)
        set_cell_bg(c, C_ACCENT_BLUE)
        _write_cell(c, h, bold=True, color=RGB_WHITE, font_size=10,
                    align=WD_ALIGN_PARAGRAPH.CENTER if ci in CENTER
                    else WD_ALIGN_PARAGRAPH.LEFT)

    # ── Data rows ─────────────────────────────────────────────────────────
    for ri, iface in enumerate(interfaces):
        short = short_iface(iface["name"])

        if short.startswith("Po"):
            bg = C_PO_ROW
        elif short.startswith("Vlan") or short.startswith("Lo"):
            bg = C_VLAN_ROW
        elif ri % 2 == 0:
            bg = C_WHITE
        else:
            bg = C_ROW_ALT

        mode  = iface["mode"]        or "—"
        desc  = iface["description"] or "—"
        notes = iface["notes"]       or "—"

        if logical:
            ip         = iface["ip_address"].split()[0] if iface["ip_address"] else "—"
            cells_data = [short, desc, mode, ip, notes]
        else:
            acc_nat    = iface["access_vlan"] or iface["native_vlan"] or "—"
            trunk      = iface["trunk_vlans"] or "—"
            cells_data = [short, desc, mode, acc_nat, trunk, notes]

        row = tbl.add_row()
        set_row_min_height(row, 360)

        for ci, (txt, w) in enumerate(zip(cells_data, COL_W_MM)):
            c = row.cells[ci]
            c.width = Mm(w)
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            set_cell_bg(c, bg)

            align = (WD_ALIGN_PARAGRAPH.CENTER if ci in CENTER
                     else WD_ALIGN_PARAGRAPH.LEFT)
            color = RGB_AMBER if (ci == 2 and iface["shutdown"]) else RGB_DARK_TEXT
            _write_cell(c, txt, bold=(ci == 0), color=color,
                        font_size=10, align=align)

    sp = doc.add_paragraph()
    sp.paragraph_format.space_before = Pt(0)
    sp.paragraph_format.space_after  = Pt(4)


def _add_vlan_table(doc, vlans: list):
    """Three-column VLAN table: VLAN ID | НАЗВА | СТАТУС (активний / мертвий)."""
    if not vlans:
        return

    # 22 + 130 + 30 = 182 mm
    COL_W_MM = [22, 130, 30]
    COL_HDR  = ["VLAN", "НАЗВА", "СТАТУС"]

    tbl = doc.add_table(rows=1, cols=3)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_table_fixed_layout(tbl)
    set_table_width(tbl, USABLE_MM)
    set_table_borders(tbl, color_hex=C_BORDER, sz="4")
    set_cell_margins_table(tbl, top=15, left=60, bottom=15, right=40)

    hdr = tbl.rows[0]
    set_repeat_header_row(hdr)
    set_row_min_height(hdr, 400)

    for ci, (h, w) in enumerate(zip(COL_HDR, COL_W_MM)):
        c = hdr.cells[ci]
        c.width = Mm(w)
        set_cell_bg(c, C_ACCENT_BLUE)
        _write_cell(c, h, bold=True, color=RGB_WHITE, font_size=10,
                    align=WD_ALIGN_PARAGRAPH.CENTER)

    for ri, vlan in enumerate(vlans):
        is_used = vlan.get("used", True)
        if is_used:
            bg         = C_WHITE if ri % 2 == 0 else C_ROW_ALT
            text_color = RGB_DARK_TEXT
            status     = "активний"
        else:
            bg         = C_VLAN_DEAD
            text_color = RGB_DEAD_TEXT
            status     = "—"

        row = tbl.add_row()
        set_row_min_height(row, 360)

        c0 = row.cells[0]
        c0.width = Mm(COL_W_MM[0])
        c0.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        set_cell_bg(c0, bg)
        _write_cell(c0, str(vlan["id"]), bold=True, color=text_color,
                    font_size=10, align=WD_ALIGN_PARAGRAPH.CENTER)

        c1 = row.cells[1]
        c1.width = Mm(COL_W_MM[1])
        c1.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        set_cell_bg(c1, bg)
        _write_cell(c1, vlan["name"] or "—", color=text_color,
                    font_size=10, align=WD_ALIGN_PARAGRAPH.LEFT)

        c2 = row.cells[2]
        c2.width = Mm(COL_W_MM[2])
        c2.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        set_cell_bg(c2, bg)
        _write_cell(c2, status, color=text_color,
                    font_size=10, align=WD_ALIGN_PARAGRAPH.CENTER)

    sp = doc.add_paragraph()
    sp.paragraph_format.space_before = Pt(0)
    sp.paragraph_format.space_after  = Pt(4)


def build_docx(parsed: dict, user_inputs: dict, output_path: str):
    doc = Document()

    # Calibri as default — full Cyrillic support on any Windows
    doc.styles["Normal"].font.name = "Calibri"

    section = doc.sections[0]
    section.page_width    = Mm(210)
    section.page_height   = Mm(297)
    section.left_margin   = Mm(14)
    section.right_margin  = Mm(14)
    section.top_margin    = Mm(14)
    section.bottom_margin = Mm(14)

    # Remove the default empty paragraph that python-docx inserts
    if doc.paragraphs:
        p = doc.paragraphs[0]._element
        p.getparent().remove(p)

    hostname = parsed.get("hostname") or "Unknown"
    mgmt_ip  = parsed.get("mgmt_ip") or "—"
    model    = user_inputs.get("model")  or "—"
    serial   = user_inputs.get("serial") or "—"
    updated  = date.today().strftime("%d.%m.%Y")

    physical, logical = classify_interfaces(parsed["interfaces"])

    _add_header_block(doc, hostname)
    _add_info_block(doc, model, serial, mgmt_ip, updated)
    _add_section_header(doc, "ФІЗИЧНІ ПОРТИ")
    _add_interface_table(doc, physical)
    _add_section_header(doc, "PORT-CHANNEL ТА VLAN")
    _add_interface_table(doc, logical, logical=True)

    vlans = parsed.get("vlans", [])
    if vlans:
        _add_section_header(doc, "VLAN DEFINITIONS")
        _add_vlan_table(doc, vlans)

    doc.save(output_path)


# ═════════════════════════════════════════════════════════════════════════════
#  GUI
# ═════════════════════════════════════════════════════════════════════════════

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _BASE = TkinterDnD.Tk
    _HAS_DND = True
except ImportError:
    _BASE = tk.Tk
    _HAS_DND = False
    DND_FILES = None

def _asset(name: str) -> str:
    """Resolve path to an asset file — works both in dev and PyInstaller .exe."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'assets', name)

# Dark theme palette (matches reference style)
_G_BG      = "#282828"
_G_IN      = "#1e1e1e"
_G_BTN     = "#1a1a1a"
_G_FG      = "#e0e0e0"
_G_LBL     = "#b8b8b8"
_G_ACCENT  = "#00ccff"
_G_ACCH    = "#55ddff"
_G_BORDER  = "#3a3a3a"
_G_STATUS  = "#94a3b8"
_G_GREEN   = "#22c55e"
_G_GREENH  = "#4ade80"
_G_GREENBG = "#0f2a1a"


class App(_BASE):
    def __init__(self):
        super().__init__()
        self.title("network-documentr — Cisco DOCX Generator")
        self.resizable(False, True)
        self.geometry("560x155")
        self.configure(bg=_G_BG)
        try:
            self.iconbitmap(_asset("app_icon.ico"))
        except Exception:
            pass  # не критично — іконка просто не відобразиться

        self._paths: list = []
        self._config_entries: list = []
        self._status = tk.StringVar(
            value="Оберіть файл конфігурації та заповніть поля.")

        self._setup_styles()
        self._close_img = self._load_icon("close.png")
        self._build_ui()
        self.update_idletasks()
        self.geometry(f"560x{self.winfo_reqheight()}")
        self.after(50, self._dark_titlebar)

    def _dark_titlebar(self):
        """Dark title bar on Windows 10 1903+ / Windows 11."""
        try:
            import ctypes
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(int(self.winfo_id()))
            if not hwnd:
                hwnd = int(self.winfo_id())
            val = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(val), ctypes.sizeof(val))
        except Exception:
            pass

    def _load_icon(self, name: str):
        try:
            return tk.PhotoImage(file=_asset(name))
        except Exception:
            return None

    def _setup_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")

        s.configure(".",
            background=_G_BG, foreground=_G_FG,
            font=("Arial", 10), borderwidth=0, relief="flat")
        s.configure("TFrame",  background=_G_BG)
        s.configure("TLabel",
            background=_G_BG, foreground=_G_LBL,
            font=("Arial", 10, "bold"))

        s.configure("TEntry",
            fieldbackground=_G_IN, foreground=_G_FG,
            bordercolor=_G_BORDER, lightcolor=_G_BORDER, darkcolor=_G_BORDER,
            insertcolor=_G_FG, padding=5)
        s.map("TEntry",
            bordercolor=[("focus", _G_ACCENT)],
            lightcolor=[("focus", _G_ACCENT)])

        s.configure("TButton",
            background=_G_BTN, foreground=_G_ACCENT,
            bordercolor=_G_ACCENT, lightcolor=_G_ACCENT, darkcolor=_G_BTN,
            relief="solid", font=("Arial", 10, "bold"),
            padding=(12, 6), borderwidth=2)
        s.map("TButton",
            background=[("active", "#2a2a2a"), ("pressed", "#111111")],
            foreground=[("active", _G_ACCH)],
            bordercolor=[("active", _G_ACCH)],
            lightcolor=[("active", _G_ACCH)])

        s.configure("TSeparator", background=_G_BORDER)
        s.configure("Status.TLabel",
            background=_G_BG, foreground=_G_STATUS, font=("Arial", 9))
        s.configure("Filename.TLabel",
            background=_G_BG, foreground=_G_FG, font=("Arial", 12))

        s.configure("X.TButton",
            background=_G_BG, foreground="#ff6b6b",
            borderwidth=0, relief="flat", font=("Arial", 20, "bold"),
            padding=(4, 0))
        s.map("X.TButton",
            foreground=[("active", "#ff4444")],
            background=[("active", _G_BG), ("pressed", _G_BG)])

        s.configure("Loaded.TButton",
            background=_G_GREENBG, foreground=_G_GREEN,
            bordercolor=_G_GREEN, lightcolor=_G_GREEN, darkcolor=_G_GREENBG,
            relief="solid", font=("Arial", 10, "bold"),
            padding=(12, 6), borderwidth=2)
        s.map("Loaded.TButton",
            background=[("active", "#1a3a2a"), ("pressed", "#0a1a10")],
            foreground=[("active", _G_GREENH)],
            bordercolor=[("active", _G_GREENH)],
            lightcolor=[("active", _G_GREENH)])

        s.configure("Blue.TButton",
            background="#0078d4", foreground="#ffffff",
            bordercolor="#0078d4", lightcolor="#0078d4", darkcolor="#0078d4",
            relief="solid", font=("Arial", 10, "bold"),
            padding=(12, 6), borderwidth=0)
        s.map("Blue.TButton",
            background=[("active", "#106ebe"), ("pressed", "#005a9e")],
            foreground=[("active", "#ffffff")],
            bordercolor=[("active", "#106ebe")],
            lightcolor=[("active", "#106ebe")])

    def _build_ui(self):
        PAD = {"padx": 10, "pady": 5}
        f = ttk.Frame(self, padding="14 12 14 10")
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        self._f = f
        self._dynamic_widgets: list = []

        self._btn_load = ttk.Button(f, text="Завантажити конфігурації",
                                    style="Blue.TButton", command=self._browse,
                                    cursor="hand2")
        self._btn_load.grid(row=0, column=0, columnspan=3, sticky="ew", **PAD)
        if _HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)

        ttk.Separator(f, orient="horizontal").grid(
            row=999, column=0, columnspan=3, sticky="ew", pady=8)

        ttk.Label(f, textvariable=self._status, style="Status.TLabel").grid(
            row=1000, column=0, columnspan=2, sticky="w", padx=10)
        self._btn_generate = ttk.Button(f, text="Створити DOCX",
                                        style="Blue.TButton", command=self._generate,
                                        cursor="hand2")
        self._btn_generate.grid(row=1000, column=2, padx=10, pady=2)
        self._btn_generate.grid_remove()

    def _rebuild_entries_ui(self):
        for w in self._dynamic_widgets:
            w.destroy()
        self._dynamic_widgets = []

        PAD = {"padx": 10, "pady": 3}
        f = self._f
        row = 1
        for i, entry in enumerate(self._config_entries):
            if i > 0:
                w = ttk.Separator(f, orient="horizontal")
                w.grid(row=row, column=0, columnspan=3, sticky="ew", pady=4)
                self._dynamic_widgets.append(w)
                row += 1

            filename = Path(entry["path"]).name
            w = ttk.Label(f, text=filename, style="Filename.TLabel")
            w.grid(row=row, column=0, columnspan=2, sticky="w", padx=10, pady=(8, 0))
            self._dynamic_widgets.append(w)
            _xkw = {"image": self._close_img} if self._close_img else {"text": "×"}
            w = ttk.Button(f, **_xkw, style="X.TButton", cursor="hand2",
                           command=lambda idx=i: self._remove_entry(idx))
            w.grid(row=row, column=2, sticky="e", padx=(0, 10), pady=(6, 0))
            self._dynamic_widgets.append(w)
            row += 1

            status_text = format_load_status(entry["parsed"])
            w = ttk.Label(f, text=status_text, style="Status.TLabel")
            w.grid(row=row, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 6))
            self._dynamic_widgets.append(w)
            row += 1

            w = ttk.Label(f, text="Модель / Вендор:")
            w.grid(row=row, column=0, sticky="w", **PAD)
            self._dynamic_widgets.append(w)
            w = ttk.Entry(f, textvariable=entry["model"], width=40)
            w.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(0, 10), pady=3)
            self._dynamic_widgets.append(w)
            row += 1

            w = ttk.Label(f, text="Серійний номер:")
            w.grid(row=row, column=0, sticky="w", **PAD)
            self._dynamic_widgets.append(w)
            w = ttk.Entry(f, textvariable=entry["serial"], width=40)
            w.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(0, 10), pady=3)
            self._dynamic_widgets.append(w)
            row += 1

        self.update_idletasks()
        self.geometry(f"560x{self.winfo_reqheight()}")

    def _remove_entry(self, index: int):
        self._config_entries.pop(index)
        self._paths.pop(index)
        n = len(self._config_entries)
        if n == 0:
            self._btn_load.configure(text="Завантажити конфігурації", style="Blue.TButton")
            self._btn_generate.grid_remove()
            self._status.set("Оберіть файл конфігурації та заповніть поля.")
            self._rebuild_entries_ui()
            self.update_idletasks()
            self.geometry(f"560x{self.winfo_reqheight()}")
        else:
            self._btn_load.configure(text=f"Завантажено конфігурацій: {n}", style="Loaded.TButton")
            self._rebuild_entries_ui()

    def _browse(self):
        paths = filedialog.askopenfilenames(
            title="Оберіть файл(и) show running-config",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not paths:
            return
        self._load_files(list(paths))

    def _load_files(self, paths: list):
        try:
            texts = [read_file_safe(p) for p in paths]
            parsed_list = [parse_showrun(t) for t in texts]
            detected_list = [parse_version_inventory(t) for t in texts]
        except Exception:
            self._paths = []
            self._config_entries = []
            self._btn_load.configure(text="Завантажити конфігурації", style="Blue.TButton")
            self._status.set("Помилка читання файлу.")
            return

        self._paths = list(paths)
        self._config_entries = [
            {
                "path":   p,
                "parsed": parsed,
                "model":  tk.StringVar(value=det["model"]),
                "serial": tk.StringVar(value=det["serial"]),
            }
            for p, parsed, det in zip(paths, parsed_list, detected_list)
        ]
        n = len(paths)
        self._btn_load.configure(text=f"Завантажено конфігурацій: {n}", style="Loaded.TButton")
        self._btn_generate.grid(row=1000, column=2, padx=10, pady=2)
        self._status.set("")
        self._rebuild_entries_ui()

    def _on_drop(self, event):
        tokens = re.findall(r'\{[^}]+\}|\S+', event.data)
        paths = [t.strip('{}') for t in tokens if os.path.isfile(t.strip('{}'))]
        if paths:
            self._load_files(paths)

    def _generate(self):
        if not self._config_entries:
            messagebox.showerror("Помилка",
                                 "Оберіть файл(и) show running-config.")
            return

        if len(self._config_entries) == 1:
            entry = self._config_entries[0]
            src = entry["path"]
            parsed = entry["parsed"]
            user_inputs = {
                "model":  entry["model"].get().strip(),
                "serial": entry["serial"].get().strip(),
            }
            hostname = parsed.get("hostname") or Path(src).stem
            save_path = filedialog.asksaveasfilename(
                title="Зберегти DOCX як…",
                initialdir=str(Path(src).parent),
                initialfile=f"{hostname}_doc.docx",
                defaultextension=".docx",
                filetypes=[("Word document", "*.docx")],
            )
            if not save_path:
                return

            try:
                self._status.set("Генерую документ…")
                self.update()
                build_docx(parsed, user_inputs, save_path)
                physical, logical = classify_interfaces(parsed["interfaces"])
                self._status.set(f"Готово: {Path(save_path).name}")
                messagebox.showinfo(
                    "Готово",
                    f"Документ збережено:\n{save_path}\n\n"
                    f"Hostname       : {hostname}\n"
                    f"Фізичні порти  : {len(physical)}\n"
                    f"Po / VLAN      : {len(logical)}",
                )
            except Exception as exc:
                messagebox.showerror("Помилка генерації", str(exc))
                self._status.set("Помилка. Перевірте файл конфігурації.")

        else:
            out_dir = filedialog.askdirectory(
                title="Оберіть директорію для збереження документів")
            if not out_dir:
                return

            self._status.set("Генерую документи…")
            self.update()
            saved = []
            errors = []
            for entry in self._config_entries:
                try:
                    parsed = entry["parsed"]
                    user_inputs = {
                        "model":  entry["model"].get().strip(),
                        "serial": entry["serial"].get().strip(),
                    }
                    hostname = parsed.get("hostname") or Path(entry["path"]).stem
                    out_path = os.path.join(out_dir, f"{hostname}_doc.docx")
                    build_docx(parsed, user_inputs, out_path)
                    saved.append(Path(out_path).name)
                except Exception as exc:
                    errors.append(f"{Path(entry['path']).name}: {exc}")

            if errors:
                messagebox.showerror("Помилки генерації", "\n".join(errors))
            if saved:
                self._status.set(f"Готово: {len(saved)} файлів")
                messagebox.showinfo(
                    "Готово",
                    f"Збережено {len(saved)} документів:\n" + "\n".join(saved),
                )


if __name__ == "__main__":
    App().mainloop()
