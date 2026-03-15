#!/usr/bin/env python3
"""
ShowRunDoc — Cisco 'show running-config' → DOCX generator
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
            "name":        iface_name,
            "description": "",
            "mode":        "",
            "access_vlan": "",
            "native_vlan": "",
            "trunk_vlans": "",
            "ip_address":  "",
            "shutdown":    False,
            "notes":       "",
            "iface_class": "physical",
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

        # Append shutdown to notes if needed
        if iface["shutdown"]:
            iface["notes"] = (iface["notes"] + " shutdown").strip()

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

    # Resolve MGMT IP: prefer SSH source-interface, fallback to first IP found
    ssh_src = result.get("ssh_source_iface", "")
    for iface in result["interfaces"]:
        if ssh_src and iface["name"] == ssh_src and iface["ip_address"]:
            result["mgmt_ip"] = iface["ip_address"]
            break
    if not result["mgmt_ip"]:
        for iface in result["interfaces"]:
            if iface["ip_address"]:
                result["mgmt_ip"] = iface["ip_address"]
                break

    return result


def classify_interfaces(interfaces: list):
    physical = [i for i in interfaces if i["iface_class"] == "physical"]
    logical  = [i for i in interfaces if i["iface_class"] == "logical"]
    return physical, logical


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
        lr.font.size = Pt(6.5)
        lr.font.color.rgb = RGB_GREY_LABEL
        _set_run_font(lr)

        # value — second paragraph
        vp = cell.add_paragraph()
        vp.paragraph_format.space_before = Pt(0)
        vp.paragraph_format.space_after  = Pt(0)
        vr = vp.add_run(val)
        vr.bold = True
        vr.font.size = Pt(9)
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
    _write_cell(cell, text, bold=True, color=RGB_WHITE, font_size=8)


def _add_interface_table(doc, interfaces: list):
    """
    Compact 7-column interface table.
    Fits 48 physical ports + logical interfaces on one A4 page.
    """
    if not interfaces:
        sp = doc.add_paragraph("(немає інтерфейсів)")
        sp.paragraph_format.space_before = Pt(2)
        sp.paragraph_format.space_after  = Pt(4)
        return

    # Column widths must sum to USABLE_MM = 182 mm
    COL_W_MM = [18, 52, 16, 18, 32, 28, 18]
    COL_HDR  = [
        "ПОРТ", "ОПИС / ПРИЗНАЧЕННЯ", "РЕЖИМ",
        "ACC/NAT VLAN", "TRUNK VLANs", "IP-АДРЕСА", "ПРИМІТКА",
    ]
    # Columns that are centre-aligned
    CENTER = {0, 2, 3, 4, 5, 6}

    tbl = doc.add_table(rows=1, cols=7)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_table_fixed_layout(tbl)
    set_table_width(tbl, USABLE_MM)
    set_table_borders(tbl, color_hex=C_BORDER, sz="4")
    # Compact padding: 15 twips top/bottom ≈ 0.26 mm → row ≈ 4.2 mm at 7pt
    set_cell_margins_table(tbl, top=15, left=60, bottom=15, right=40)

    # ── Header row ────────────────────────────────────────────────────────
    hdr = tbl.rows[0]
    set_repeat_header_row(hdr)
    set_row_min_height(hdr, 280)   # ~4.9 mm

    for ci, (h, w) in enumerate(zip(COL_HDR, COL_W_MM)):
        c = hdr.cells[ci]
        c.width = Mm(w)
        set_cell_bg(c, C_ACCENT_BLUE)
        _write_cell(c, h, bold=True, color=RGB_WHITE, font_size=7,
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

        acc_nat = iface["access_vlan"] or iface["native_vlan"] or "—"
        trunk   = iface["trunk_vlans"] or "—"
        ip      = iface["ip_address"]  or "—"
        mode    = iface["mode"]        or "—"
        desc    = iface["description"] or "—"
        notes   = iface["notes"]       or "—"

        row = tbl.add_row()
        set_row_min_height(row, 240)   # ~4.2 mm minimum

        cells_data = [short, desc, mode, acc_nat, trunk, ip, notes]

        for ci, (txt, w) in enumerate(zip(cells_data, COL_W_MM)):
            c = row.cells[ci]
            c.width = Mm(w)
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            set_cell_bg(c, bg)

            align = (WD_ALIGN_PARAGRAPH.CENTER if ci in CENTER
                     else WD_ALIGN_PARAGRAPH.LEFT)
            color = RGB_AMBER if (ci == 2 and iface["shutdown"]) else RGB_DARK_TEXT
            _write_cell(c, txt, bold=(ci == 0), color=color,
                        font_size=7, align=align)

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
    _add_interface_table(doc, logical)

    doc.save(output_path)


# ═════════════════════════════════════════════════════════════════════════════
#  GUI
# ═════════════════════════════════════════════════════════════════════════════

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ShowRunDoc — Cisco DOCX Generator")
        self.resizable(False, False)
        self.geometry("540x190")

        self._src     = tk.StringVar()
        self._model   = tk.StringVar()
        self._serial  = tk.StringVar()
        self._status  = tk.StringVar(value="Оберіть файл конфігурації та заповніть поля.")

        self._build_ui()

    def _build_ui(self):
        self.columnconfigure(1, weight=1)
        PAD = {"padx": 10, "pady": 4}

        ttk.Label(self, text="Config файл:").grid(
            row=0, column=0, sticky="e", **PAD)
        ttk.Entry(self, textvariable=self._src, width=42).grid(
            row=0, column=1, sticky="ew", **PAD)
        ttk.Button(self, text="Огляд…", command=self._browse).grid(
            row=0, column=2, **PAD)

        ttk.Label(self, text="Модель / Вендор:").grid(
            row=1, column=0, sticky="e", **PAD)
        ttk.Entry(self, textvariable=self._model, width=42).grid(
            row=1, column=1, columnspan=2, sticky="ew", **PAD)

        ttk.Label(self, text="Серійний номер:").grid(
            row=2, column=0, sticky="e", **PAD)
        ttk.Entry(self, textvariable=self._serial, width=42).grid(
            row=2, column=1, columnspan=2, sticky="ew", **PAD)

        ttk.Separator(self, orient="horizontal").grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=6, padx=10)

        ttk.Label(self, textvariable=self._status,
                  foreground="#475569").grid(
            row=4, column=0, columnspan=2, sticky="w", padx=10)
        ttk.Button(self, text="Створити DOCX",
                   command=self._generate).grid(
            row=4, column=2, padx=10, pady=4)

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Оберіть файл show running-config",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        self._src.set(path)
        try:
            parsed = parse_showrun(read_file_safe(path))
            if parsed.get("mgmt_ip"):
                self._status.set(f"MGMT IP: {parsed['mgmt_ip']}")
        except Exception:
            pass

    def _generate(self):
        src = self._src.get().strip()
        if not src or not os.path.isfile(src):
            messagebox.showerror("Помилка",
                                 "Оберіть коректний файл show running-config.")
            return

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

            user_inputs = {
                "model":  self._model.get().strip(),
                "serial": self._serial.get().strip(),
            }
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


if __name__ == "__main__":
    App().mainloop()
