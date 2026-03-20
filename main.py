#!/usr/bin/env python3
"""
network-documentr — Cisco 'show running-config' → DOCX generator
"""

import re
import os
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
C_BORDER      = "CBD5E1"
C_WHITE       = "FFFFFF"

RGB_WHITE      = RGBColor(0xFF, 0xFF, 0xFF)
RGB_DARK_TEXT  = RGBColor(0x1E, 0x29, 0x3B)
RGB_GREY_LABEL = RGBColor(0x94, 0xA3, 0xB8)
RGB_AMBER      = RGBColor(0xB4, 0x53, 0x09)

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
            "voice_vlan":        "",
            "stp_portfast":      False,
            "stp_rootguard":     False,
            "stp_bpduguard":     False,
            "port_security":     False,
            "port_security_max": "",
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

            elif line == "switchport port-security":
                iface["port_security"] = True

        # Build notes: Po member → Voice:X → PortFast → RootGuard → BPDUGuard → SecMax/PortSec → shutdown
        notes_parts = [iface["notes"]] if iface["notes"] else []
        if iface["voice_vlan"]:        notes_parts.append(f"Voice:{iface['voice_vlan']}")
        if iface["stp_portfast"]:      notes_parts.append("PortFast")
        if iface["stp_rootguard"]:     notes_parts.append("RootGuard")
        if iface["stp_bpduguard"]:     notes_parts.append("BPDUGuard")
        if iface["port_security_max"]: notes_parts.append(f"SecMax:{iface['port_security_max']}")
        elif iface["port_security"]:   notes_parts.append("PortSec")
        if iface["shutdown"]:          notes_parts.append("shutdown")
        iface["notes"] = " ".join(notes_parts)

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
        if vlan_name:
            result["vlans"].append({"id": m_vid.group(1), "name": vlan_name})

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
    """Write text into the first paragraph of a cell with full styling."""
    para = cell.paragraphs[0]
    para.clear()
    para.paragraph_format.space_before = Pt(0)
    para.paragraph_format.space_after  = Pt(0)
    para.alignment = align
    run = para.add_run(text or "")
    run.bold = bold
    run.font.size = Pt(font_size)
    if color:
        run.font.color.rgb = color
    _set_run_font(run)


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
    """Two-column VLAN definitions table: VLAN ID | НАЗВА."""
    if not vlans:
        return

    COL_W_MM = [22, 160]
    COL_HDR  = ["VLAN", "НАЗВА"]

    tbl = doc.add_table(rows=1, cols=2)
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
                    align=WD_ALIGN_PARAGRAPH.CENTER if ci == 0
                    else WD_ALIGN_PARAGRAPH.LEFT)

    for ri, vlan in enumerate(vlans):
        bg = C_WHITE if ri % 2 == 0 else C_ROW_ALT
        row = tbl.add_row()
        set_row_min_height(row, 360)

        c0 = row.cells[0]
        c0.width = Mm(COL_W_MM[0])
        c0.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        set_cell_bg(c0, bg)
        _write_cell(c0, str(vlan["id"]), bold=True, color=RGB_DARK_TEXT,
                    font_size=10, align=WD_ALIGN_PARAGRAPH.CENTER)

        c1 = row.cells[1]
        c1.width = Mm(COL_W_MM[1])
        c1.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        set_cell_bg(c1, bg)
        _write_cell(c1, vlan["name"], color=RGB_DARK_TEXT,
                    font_size=10, align=WD_ALIGN_PARAGRAPH.LEFT)

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
        self.resizable(False, False)
        self.geometry("560x215")
        self.configure(bg=_G_BG)

        self._paths: list = []
        self._model  = tk.StringVar()
        self._serial = tk.StringVar()
        self._status = tk.StringVar(
            value="Оберіть файл конфігурації та заповніть поля.")

        self._setup_styles()
        self._build_ui()
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

    def _build_ui(self):
        PAD = {"padx": 10, "pady": 5}
        f = ttk.Frame(self, padding="14 12 14 10")
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        self._btn_load = ttk.Button(f, text="Завантажити", command=self._browse)
        self._btn_load.grid(row=0, column=0, columnspan=3, sticky="ew", **PAD)
        if _HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)

        ttk.Label(f, text="Модель / Вендор:").grid(
            row=1, column=0, sticky="e", **PAD)
        ttk.Entry(f, textvariable=self._model, width=40).grid(
            row=1, column=1, columnspan=2, sticky="ew", **PAD)

        ttk.Label(f, text="Серійний номер:").grid(
            row=2, column=0, sticky="e", **PAD)
        ttk.Entry(f, textvariable=self._serial, width=40).grid(
            row=2, column=1, columnspan=2, sticky="ew", **PAD)

        ttk.Separator(f, orient="horizontal").grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=8)

        ttk.Label(f, textvariable=self._status, style="Status.TLabel").grid(
            row=4, column=0, columnspan=2, sticky="w", padx=10)
        ttk.Button(f, text="Створити DOCX", command=self._generate).grid(
            row=4, column=2, padx=10, pady=2)

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
            parsed_list = [parse_showrun(read_file_safe(p)) for p in paths]
        except Exception:
            self._paths = []
            self._btn_load.configure(text="Завантажити", style="TButton")
            self._status.set("Помилка читання файлу.")
            return

        self._paths = list(paths)
        n = len(paths)
        if n == 1:
            self._btn_load.configure(text="Завантажено", style="Loaded.TButton")
            self._status.set(format_load_status(parsed_list[0]))
        else:
            self._btn_load.configure(text=f"Завантажено ({n})", style="Loaded.TButton")
            self._status.set(f"{n} конфігів готові до генерації")

    def _on_drop(self, event):
        tokens = re.findall(r'\{[^}]+\}|\S+', event.data)
        paths = [t.strip('{}') for t in tokens if os.path.isfile(t.strip('{}'))]
        if paths:
            self._load_files(paths)

    def _generate(self):
        if not self._paths:
            messagebox.showerror("Помилка",
                                 "Оберіть файл(и) show running-config.")
            return

        user_inputs = {
            "model":  self._model.get().strip(),
            "serial": self._serial.get().strip(),
        }

        if len(self._paths) == 1:
            src = self._paths[0]
            try:
                raw    = read_file_safe(src)
                parsed = parse_showrun(raw)
            except Exception as exc:
                messagebox.showerror("Помилка читання файлу", str(exc))
                return

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
            for path in self._paths:
                try:
                    raw    = read_file_safe(path)
                    parsed = parse_showrun(raw)
                    hostname = parsed.get("hostname") or Path(path).stem
                    out_path = os.path.join(out_dir, f"{hostname}_doc.docx")
                    build_docx(parsed, user_inputs, out_path)
                    saved.append(Path(out_path).name)
                except Exception as exc:
                    errors.append(f"{Path(path).name}: {exc}")

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
