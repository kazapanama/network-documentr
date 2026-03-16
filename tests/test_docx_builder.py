"""
Tests for DOCX XML helpers and builder functions:
  set_cell_bg / set_table_borders / set_table_fixed_layout / set_table_width
  set_cell_margins_table / set_cell_margins / set_repeat_header_row
  set_row_min_height / _set_run_font / _write_cell
  _add_header_block / _add_info_block / _add_section_header
  _add_interface_table / build_docx
"""
import pytest
from pathlib import Path

from docx import Document
from docx.shared import Mm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from main import (
    # XML helpers
    set_cell_bg,
    set_table_borders,
    set_table_fixed_layout,
    set_table_width,
    set_cell_margins_table,
    set_cell_margins,
    set_repeat_header_row,
    set_row_min_height,
    _set_run_font,
    _write_cell,
    # Builders
    _add_header_block,
    _add_info_block,
    _add_section_header,
    _add_interface_table,
    build_docx,
    parse_showrun,
    classify_interfaces,
    # Constants
    USABLE_MM,
    C_DARK_BLUE,
    C_MID_BLUE,
    C_LIGHT_BLUE,
    C_ACCENT_BLUE,
    RGB_WHITE,
    RGB_DARK_TEXT,
    RGB_AMBER,
)

# ─────────────────────────────────────────────────────────────────────────────
#  Shared fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────

MINIMAL_CONFIG = """\
hostname TEST-SWITCH
ip ssh source-interface Vlan1

interface GigabitEthernet1/0/1
 description Test Port
 switchport mode access
 switchport access vlan 10

interface Vlan1
 ip address 192.168.1.1 255.255.255.0
"""


def _doc():
    return Document()


def _iface(name: str, **kwargs) -> dict:
    """Minimal valid interface dict."""
    defaults = {
        "name":        name,
        "description": "",
        "mode":        "access",
        "access_vlan": "10",
        "native_vlan": "",
        "trunk_vlans": "",
        "ip_address":  "",
        "shutdown":    False,
        "notes":       "",
        "iface_class": "physical",
    }
    defaults.update(kwargs)
    return defaults


# ─────────────────────────────────────────────────────────────────────────────
#  XML helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestSetCellBg:

    def test_shd_element_created(self):
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        set_cell_bg(cell, "FF0000")
        shd = cell._tc.tcPr.find(qn("w:shd"))
        assert shd is not None

    def test_fill_color_set(self):
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        set_cell_bg(cell, "1A2B4A")
        shd = cell._tc.tcPr.find(qn("w:shd"))
        assert shd.get(qn("w:fill")) == "1A2B4A"

    def test_val_is_clear(self):
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        set_cell_bg(cell, "FFFFFF")
        shd = cell._tc.tcPr.find(qn("w:shd"))
        assert shd.get(qn("w:val")) == "clear"

    def test_replaces_existing_shd(self):
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        set_cell_bg(cell, "FF0000")
        set_cell_bg(cell, "00FF00")
        shds = cell._tc.tcPr.findall(qn("w:shd"))
        assert len(shds) == 1
        assert shds[0].get(qn("w:fill")) == "00FF00"


class TestSetTableBorders:

    def test_borders_element_created(self):
        doc = _doc()
        tbl = doc.add_table(rows=1, cols=1)
        set_table_borders(tbl)
        borders = tbl._tbl.tblPr.find(qn("w:tblBorders"))
        assert borders is not None

    @pytest.mark.parametrize("side", ["top", "left", "bottom", "right", "insideH", "insideV"])
    def test_all_sides_present(self, side):
        doc = _doc()
        tbl = doc.add_table(rows=1, cols=1)
        set_table_borders(tbl, color_hex="CBD5E1")
        borders = tbl._tbl.tblPr.find(qn("w:tblBorders"))
        elem = borders.find(qn(f"w:{side}"))
        assert elem is not None

    def test_color_applied_to_all_sides(self):
        doc = _doc()
        tbl = doc.add_table(rows=1, cols=1)
        set_table_borders(tbl, color_hex="123456")
        borders = tbl._tbl.tblPr.find(qn("w:tblBorders"))
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            elem = borders.find(qn(f"w:{side}"))
            assert elem.get(qn("w:color")) == "123456"

    def test_replaces_existing_borders(self):
        doc = _doc()
        tbl = doc.add_table(rows=1, cols=1)
        set_table_borders(tbl, color_hex="AAAAAA")
        set_table_borders(tbl, color_hex="BBBBBB")
        border_elems = tbl._tbl.tblPr.findall(qn("w:tblBorders"))
        assert len(border_elems) == 1


class TestSetTableFixedLayout:

    def test_layout_element_created(self):
        doc = _doc()
        tbl = doc.add_table(rows=1, cols=1)
        set_table_fixed_layout(tbl)
        layout = tbl._tbl.tblPr.find(qn("w:tblLayout"))
        assert layout is not None

    def test_type_is_fixed(self):
        doc = _doc()
        tbl = doc.add_table(rows=1, cols=1)
        set_table_fixed_layout(tbl)
        layout = tbl._tbl.tblPr.find(qn("w:tblLayout"))
        assert layout.get(qn("w:type")) == "fixed"

    def test_replaces_existing_layout(self):
        doc = _doc()
        tbl = doc.add_table(rows=1, cols=1)
        set_table_fixed_layout(tbl)
        set_table_fixed_layout(tbl)
        layouts = tbl._tbl.tblPr.findall(qn("w:tblLayout"))
        assert len(layouts) == 1


class TestSetTableWidth:

    def test_width_element_created(self):
        doc = _doc()
        tbl = doc.add_table(rows=1, cols=1)
        set_table_width(tbl, 182.0)
        w = tbl._tbl.tblPr.find(qn("w:tblW"))
        assert w is not None

    def test_type_is_dxa(self):
        doc = _doc()
        tbl = doc.add_table(rows=1, cols=1)
        set_table_width(tbl, 182.0)
        w = tbl._tbl.tblPr.find(qn("w:tblW"))
        assert w.get(qn("w:type")) == "dxa"

    def test_width_value_calculated_correctly(self):
        doc = _doc()
        tbl = doc.add_table(rows=1, cols=1)
        set_table_width(tbl, 182.0)
        w = tbl._tbl.tblPr.find(qn("w:tblW"))
        assert w.get(qn("w:w")) == str(int(182.0 * 56.7))

    def test_replaces_existing_width(self):
        doc = _doc()
        tbl = doc.add_table(rows=1, cols=1)
        set_table_width(tbl, 100.0)
        set_table_width(tbl, 182.0)
        assert len(tbl._tbl.tblPr.findall(qn("w:tblW"))) == 1


class TestSetCellMarginsTable:

    def test_mar_element_created(self):
        doc = _doc()
        tbl = doc.add_table(rows=1, cols=1)
        set_cell_margins_table(tbl, top=15, left=60, bottom=15, right=40)
        mar = tbl._tbl.tblPr.find(qn("w:tblCellMar"))
        assert mar is not None

    @pytest.mark.parametrize("side,val", [("top", "15"), ("left", "60"), ("bottom", "15"), ("right", "40")])
    def test_sides_set_correctly(self, side, val):
        doc = _doc()
        tbl = doc.add_table(rows=1, cols=1)
        set_cell_margins_table(tbl, top=15, left=60, bottom=15, right=40)
        mar = tbl._tbl.tblPr.find(qn("w:tblCellMar"))
        assert mar.find(qn(f"w:{side}")).get(qn("w:w")) == val

    def test_replaces_existing(self):
        doc = _doc()
        tbl = doc.add_table(rows=1, cols=1)
        set_cell_margins_table(tbl, top=10)
        set_cell_margins_table(tbl, top=20)
        assert len(tbl._tbl.tblPr.findall(qn("w:tblCellMar"))) == 1


class TestSetCellMargins:

    def test_mar_element_created(self):
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        set_cell_margins(cell, top=60, left=80, bottom=60, right=40)
        mar = cell._tc.tcPr.find(qn("w:tcMar"))
        assert mar is not None

    @pytest.mark.parametrize("side,val", [("top", "60"), ("left", "80"), ("bottom", "60"), ("right", "40")])
    def test_sides_set(self, side, val):
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        set_cell_margins(cell, top=60, left=80, bottom=60, right=40)
        mar = cell._tc.tcPr.find(qn("w:tcMar"))
        assert mar.find(qn(f"w:{side}")).get(qn("w:w")) == val

    def test_all_sides_type_dxa(self):
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        set_cell_margins(cell, top=60, left=80, bottom=60, right=40)
        mar = cell._tc.tcPr.find(qn("w:tcMar"))
        for side in ("top", "left", "bottom", "right"):
            assert mar.find(qn(f"w:{side}")).get(qn("w:type")) == "dxa"


class TestSetRepeatHeaderRow:

    def test_tbl_header_added(self):
        doc = _doc()
        row = doc.add_table(rows=1, cols=1).rows[0]
        set_repeat_header_row(row)
        assert row._tr.trPr.find(qn("w:tblHeader")) is not None


class TestSetRowMinHeight:

    def test_tr_height_element_created(self):
        doc = _doc()
        row = doc.add_table(rows=1, cols=1).rows[0]
        set_row_min_height(row, 300)
        h = row._tr.trPr.find(qn("w:trHeight"))
        assert h is not None

    def test_height_value_set(self):
        doc = _doc()
        row = doc.add_table(rows=1, cols=1).rows[0]
        set_row_min_height(row, 300)
        h = row._tr.trPr.find(qn("w:trHeight"))
        assert h.get(qn("w:val")) == "300"

    def test_hrule_is_at_least(self):
        doc = _doc()
        row = doc.add_table(rows=1, cols=1).rows[0]
        set_row_min_height(row, 300)
        h = row._tr.trPr.find(qn("w:trHeight"))
        assert h.get(qn("w:hRule")) == "atLeast"

    def test_default_height_240(self):
        doc = _doc()
        row = doc.add_table(rows=1, cols=1).rows[0]
        set_row_min_height(row)
        h = row._tr.trPr.find(qn("w:trHeight"))
        assert h.get(qn("w:val")) == "240"

    def test_replaces_existing(self):
        doc = _doc()
        row = doc.add_table(rows=1, cols=1).rows[0]
        set_row_min_height(row, 100)
        set_row_min_height(row, 200)
        assert len(row._tr.trPr.findall(qn("w:trHeight"))) == 1
        assert row._tr.trPr.find(qn("w:trHeight")).get(qn("w:val")) == "200"


class TestSetRunFont:

    def test_r_fonts_element_created(self):
        doc = _doc()
        run = doc.add_paragraph().add_run("test")
        _set_run_font(run)
        assert run._r.rPr.find(qn("w:rFonts")) is not None

    def test_default_font_is_calibri(self):
        doc = _doc()
        run = doc.add_paragraph().add_run("test")
        _set_run_font(run)
        rFonts = run._r.rPr.find(qn("w:rFonts"))
        assert rFonts.get(qn("w:ascii")) == "Calibri"

    def test_cs_attribute_set_for_cyrillic(self):
        doc = _doc()
        run = doc.add_paragraph().add_run("Тест")
        _set_run_font(run)
        rFonts = run._r.rPr.find(qn("w:rFonts"))
        assert rFonts.get(qn("w:cs")) == "Calibri"

    def test_h_ansi_set(self):
        doc = _doc()
        run = doc.add_paragraph().add_run("test")
        _set_run_font(run)
        rFonts = run._r.rPr.find(qn("w:rFonts"))
        assert rFonts.get(qn("w:hAnsi")) == "Calibri"

    def test_east_asia_set(self):
        doc = _doc()
        run = doc.add_paragraph().add_run("test")
        _set_run_font(run)
        rFonts = run._r.rPr.find(qn("w:rFonts"))
        assert rFonts.get(qn("w:eastAsia")) == "Calibri"

    def test_custom_font_name(self):
        doc = _doc()
        run = doc.add_paragraph().add_run("test")
        _set_run_font(run, "Arial")
        rFonts = run._r.rPr.find(qn("w:rFonts"))
        assert rFonts.get(qn("w:ascii")) == "Arial"

    def test_replaces_existing_r_fonts(self):
        doc = _doc()
        run = doc.add_paragraph().add_run("test")
        _set_run_font(run, "Times New Roman")
        _set_run_font(run, "Calibri")
        assert len(run._r.rPr.findall(qn("w:rFonts"))) == 1
        assert run._r.rPr.find(qn("w:rFonts")).get(qn("w:ascii")) == "Calibri"


class TestWriteCell:

    def test_text_written(self):
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        _write_cell(cell, "Hello World")
        assert cell.paragraphs[0].text == "Hello World"

    def test_empty_string_written(self):
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        _write_cell(cell, "")
        assert cell.paragraphs[0].text == ""

    def test_none_written_as_empty(self):
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        _write_cell(cell, None)
        assert cell.paragraphs[0].text == ""

    def test_bold_run(self):
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        _write_cell(cell, "Bold", bold=True)
        assert cell.paragraphs[0].runs[0].bold is True

    def test_not_bold_by_default(self):
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        _write_cell(cell, "Normal")
        assert not cell.paragraphs[0].runs[0].bold

    def test_font_size_applied(self):
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        _write_cell(cell, "Test", font_size=7)
        assert cell.paragraphs[0].runs[0].font.size == Pt(7)

    def test_color_applied(self):
        from docx.shared import RGBColor
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        color = RGBColor(0xFF, 0xFF, 0xFF)
        _write_cell(cell, "White", color=color)
        assert cell.paragraphs[0].runs[0].font.color.rgb == color

    def test_alignment_center(self):
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        _write_cell(cell, "Center", align=WD_ALIGN_PARAGRAPH.CENTER)
        assert cell.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER

    def test_no_space_before_after(self):
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        _write_cell(cell, "Test")
        fmt = cell.paragraphs[0].paragraph_format
        assert fmt.space_before == Pt(0)
        assert fmt.space_after == Pt(0)

    def test_cyrillic_text(self):
        doc = _doc()
        cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        _write_cell(cell, "Тест Кирилиця")
        assert cell.paragraphs[0].text == "Тест Кирилиця"


# ─────────────────────────────────────────────────────────────────────────────
#  Builder functions
# ─────────────────────────────────────────────────────────────────────────────

class TestAddHeaderBlock:

    def test_adds_one_table(self):
        doc = _doc()
        _add_header_block(doc, "SWITCH-01")
        assert len(doc.tables) == 1

    def test_hostname_in_cell(self):
        doc = _doc()
        _add_header_block(doc, "MY-SWITCH")
        assert doc.tables[0].cell(0, 0).paragraphs[0].text == "MY-SWITCH"

    def test_dark_blue_background(self):
        doc = _doc()
        _add_header_block(doc, "SW")
        cell = doc.tables[0].cell(0, 0)
        shd = cell._tc.tcPr.find(qn("w:shd"))
        assert shd.get(qn("w:fill")) == C_DARK_BLUE

    def test_font_is_bold(self):
        doc = _doc()
        _add_header_block(doc, "SW")
        run = doc.tables[0].cell(0, 0).paragraphs[0].runs[0]
        assert run.bold is True

    def test_font_size_16(self):
        doc = _doc()
        _add_header_block(doc, "SW")
        run = doc.tables[0].cell(0, 0).paragraphs[0].runs[0]
        assert run.font.size == Pt(16)

    def test_adds_spacer_paragraph_after(self):
        doc = _doc()
        initial_para_count = len(doc.paragraphs)
        _add_header_block(doc, "SW")
        # One spacer paragraph added
        assert len(doc.paragraphs) > initial_para_count


class TestAddInfoBlock:

    def test_creates_table_with_4_cols(self):
        doc = _doc()
        _add_info_block(doc, "Cisco 3750", "FCZ001", "10.0.0.1", "01.01.2025")
        assert len(doc.tables[0].columns) == 4

    def test_model_present_in_cell(self):
        doc = _doc()
        _add_info_block(doc, "Cisco 3750", "FCZ001", "10.0.0.1", "01.01.2025")
        texts = _all_cell_texts(doc.tables[0])
        assert any("Cisco 3750" in t for t in texts)

    def test_serial_present_in_cell(self):
        doc = _doc()
        _add_info_block(doc, "Cisco 3750", "FCZ001", "10.0.0.1", "01.01.2025")
        texts = _all_cell_texts(doc.tables[0])
        assert any("FCZ001" in t for t in texts)

    def test_mgmt_ip_present_in_cell(self):
        doc = _doc()
        _add_info_block(doc, "Cisco 3750", "FCZ001", "10.0.0.1", "01.01.2025")
        texts = _all_cell_texts(doc.tables[0])
        assert any("10.0.0.1" in t for t in texts)

    def test_updated_date_present(self):
        doc = _doc()
        _add_info_block(doc, "Cisco 3750", "FCZ001", "10.0.0.1", "15.03.2026")
        texts = _all_cell_texts(doc.tables[0])
        assert any("15.03.2026" in t for t in texts)

    def test_empty_model_uses_dash(self):
        doc = _doc()
        _add_info_block(doc, "", "", "", "01.01.2025")
        texts = _all_cell_texts(doc.tables[0])
        assert any("—" in t for t in texts)

    def test_light_blue_background(self):
        doc = _doc()
        _add_info_block(doc, "M", "S", "IP", "D")
        cell = doc.tables[0].cell(0, 0)
        shd = cell._tc.tcPr.find(qn("w:shd"))
        assert shd.get(qn("w:fill")) == C_LIGHT_BLUE

    def test_label_and_value_paragraphs(self):
        doc = _doc()
        _add_info_block(doc, "Model X", "SN123", "1.2.3.4", "01.01.2025")
        cell = doc.tables[0].cell(0, 0)
        # Should have 2 paragraphs: label + value
        assert len(cell.paragraphs) == 2


class TestAddSectionHeader:

    def test_adds_table(self):
        doc = _doc()
        _add_section_header(doc, "ФІЗИЧНІ ПОРТИ")
        assert len(doc.tables) == 1

    def test_text_in_cell(self):
        doc = _doc()
        _add_section_header(doc, "ФІЗИЧНІ ПОРТИ")
        assert doc.tables[0].cell(0, 0).paragraphs[0].text == "ФІЗИЧНІ ПОРТИ"

    def test_mid_blue_background(self):
        doc = _doc()
        _add_section_header(doc, "TEST")
        shd = doc.tables[0].cell(0, 0)._tc.tcPr.find(qn("w:shd"))
        assert shd.get(qn("w:fill")) == C_MID_BLUE

    def test_bold_white_text(self):
        doc = _doc()
        _add_section_header(doc, "TEST")
        run = doc.tables[0].cell(0, 0).paragraphs[0].runs[0]
        assert run.bold is True
        assert run.font.color.rgb == RGB_WHITE


class TestAddInterfaceTable:

    def test_empty_shows_no_interfaces_message(self):
        doc = _doc()
        _add_interface_table(doc, [])
        para_texts = [p.text for p in doc.paragraphs]
        assert any("немає" in t for t in para_texts)

    def test_empty_does_not_add_table(self):
        doc = _doc()
        _add_interface_table(doc, [])
        assert len(doc.tables) == 0

    def test_physical_table_has_6_columns(self):
        doc = _doc()
        _add_interface_table(doc, [_iface("GigabitEthernet1/0/1")], logical=False)
        assert len(doc.tables[0].columns) == 6

    def test_logical_table_has_5_columns(self):
        doc = _doc()
        _add_interface_table(
            doc, [_iface("Port-channel1", iface_class="logical")], logical=True
        )
        assert len(doc.tables[0].columns) == 5

    def test_header_row_contains_port_column(self):
        doc = _doc()
        _add_interface_table(doc, [_iface("GigabitEthernet1/0/1")])
        hdr_texts = [c.paragraphs[0].text for c in doc.tables[0].rows[0].cells]
        assert "ПОРТ" in hdr_texts

    def test_header_row_contains_mode_column(self):
        doc = _doc()
        _add_interface_table(doc, [_iface("GigabitEthernet1/0/1")])
        hdr_texts = [c.paragraphs[0].text for c in doc.tables[0].rows[0].cells]
        assert "РЕЖИМ" in hdr_texts

    def test_physical_header_has_trunk_vlans_col(self):
        doc = _doc()
        _add_interface_table(doc, [_iface("GigabitEthernet1/0/1")], logical=False)
        hdr_texts = [c.paragraphs[0].text for c in doc.tables[0].rows[0].cells]
        assert "TRUNK VLANs" in hdr_texts

    def test_logical_header_has_ip_col(self):
        doc = _doc()
        _add_interface_table(
            doc, [_iface("Vlan10", iface_class="logical")], logical=True
        )
        hdr_texts = [c.paragraphs[0].text for c in doc.tables[0].rows[0].cells]
        assert "IP-АДРЕСА" in hdr_texts

    def test_data_row_count_equals_interface_count(self):
        doc = _doc()
        ifaces = [_iface(f"GigabitEthernet1/0/{i}") for i in range(1, 5)]
        _add_interface_table(doc, ifaces)
        # 1 header + 4 data rows
        assert len(doc.tables[0].rows) == 5

    def test_short_name_in_port_cell(self):
        doc = _doc()
        _add_interface_table(doc, [_iface("GigabitEthernet1/0/1")])
        port_text = doc.tables[0].rows[1].cells[0].paragraphs[0].text
        assert "Gi1/0/1" in port_text

    def test_description_in_desc_cell(self):
        doc = _doc()
        _add_interface_table(doc, [_iface("GigabitEthernet1/0/1", description="Server")])
        desc_text = doc.tables[0].rows[1].cells[1].paragraphs[0].text
        assert "Server" in desc_text

    def test_empty_description_shows_dash(self):
        doc = _doc()
        _add_interface_table(doc, [_iface("GigabitEthernet1/0/1", description="")])
        desc_text = doc.tables[0].rows[1].cells[1].paragraphs[0].text
        assert desc_text == "—"

    def test_shutdown_mode_cell_amber_color(self):
        doc = _doc()
        _add_interface_table(doc, [_iface("GigabitEthernet1/0/1", shutdown=True, mode="access")])
        mode_cell = doc.tables[0].rows[1].cells[2]
        run = mode_cell.paragraphs[0].runs[0]
        assert run.font.color.rgb == RGB_AMBER

    def test_non_shutdown_mode_cell_dark_text(self):
        doc = _doc()
        _add_interface_table(doc, [_iface("GigabitEthernet1/0/1", shutdown=False, mode="access")])
        mode_cell = doc.tables[0].rows[1].cells[2]
        run = mode_cell.paragraphs[0].runs[0]
        assert run.font.color.rgb == RGB_DARK_TEXT

    def test_port_cell_is_bold(self):
        doc = _doc()
        _add_interface_table(doc, [_iface("GigabitEthernet1/0/1")])
        port_run = doc.tables[0].rows[1].cells[0].paragraphs[0].runs[0]
        assert port_run.bold is True

    def test_48_interfaces_all_rendered(self):
        doc = _doc()
        ifaces = [_iface(f"GigabitEthernet1/0/{i}") for i in range(1, 49)]
        _add_interface_table(doc, ifaces)
        tbl = doc.tables[0]
        assert len(tbl.rows) == 49  # 1 header + 48 data


# ─────────────────────────────────────────────────────────────────────────────
#  build_docx — integration
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildDocx:

    def test_creates_file(self, tmp_path):
        out = str(tmp_path / "out.docx")
        build_docx(parse_showrun(MINIMAL_CONFIG), {"model": "X", "serial": "Y"}, out)
        assert Path(out).exists()

    def test_output_is_valid_docx(self, tmp_path):
        out = str(tmp_path / "out.docx")
        build_docx(parse_showrun(MINIMAL_CONFIG), {}, out)
        doc = Document(out)
        assert doc is not None

    def test_a4_page_dimensions(self, tmp_path):
        out = str(tmp_path / "out.docx")
        build_docx(parse_showrun(MINIMAL_CONFIG), {}, out)
        sec = Document(out).sections[0]
        # 1 EMU tolerance
        assert abs(sec.page_width  - Mm(210)) < 1000
        assert abs(sec.page_height - Mm(297)) < 1000

    def test_14mm_margins(self, tmp_path):
        out = str(tmp_path / "out.docx")
        build_docx(parse_showrun(MINIMAL_CONFIG), {}, out)
        sec = Document(out).sections[0]
        for margin in (sec.left_margin, sec.right_margin, sec.top_margin, sec.bottom_margin):
            assert abs(margin - Mm(14)) < 1000

    def test_hostname_in_header_table(self, tmp_path):
        out = str(tmp_path / "out.docx")
        build_docx(parse_showrun(MINIMAL_CONFIG), {}, out)
        doc = Document(out)
        header_text = doc.tables[0].cell(0, 0).paragraphs[0].text
        assert "TEST-SWITCH" in header_text

    def test_unknown_hostname_shows_unknown(self, tmp_path):
        out = str(tmp_path / "out.docx")
        build_docx(parse_showrun("! no hostname\n"), {}, out)
        header_text = Document(out).tables[0].cell(0, 0).paragraphs[0].text
        assert "Unknown" in header_text

    def test_model_in_info_block(self, tmp_path):
        out = str(tmp_path / "out.docx")
        build_docx(parse_showrun(MINIMAL_CONFIG), {"model": "Catalyst 3750G"}, out)
        doc = Document(out)
        texts = _all_cell_texts(doc.tables[1])
        assert any("Catalyst 3750G" in t for t in texts)

    def test_serial_in_info_block(self, tmp_path):
        out = str(tmp_path / "out.docx")
        build_docx(parse_showrun(MINIMAL_CONFIG), {"serial": "FOC1234X567"}, out)
        doc = Document(out)
        texts = _all_cell_texts(doc.tables[1])
        assert any("FOC1234X567" in t for t in texts)

    def test_empty_model_serial_show_dash(self, tmp_path):
        out = str(tmp_path / "out.docx")
        build_docx(parse_showrun(MINIMAL_CONFIG), {"model": "", "serial": ""}, out)
        doc = Document(out)
        texts = _all_cell_texts(doc.tables[1])
        assert any("—" in t for t in texts)

    def test_at_least_4_tables_in_document(self, tmp_path):
        out = str(tmp_path / "out.docx")
        build_docx(parse_showrun(MINIMAL_CONFIG), {}, out)
        # header + info + section_phys + iface_phys + section_log + iface_log
        assert len(Document(out).tables) >= 4

    def test_empty_interfaces_builds_without_error(self, tmp_path):
        out = str(tmp_path / "out.docx")
        parsed = {"hostname": "EMPTY-SW", "mgmt_ip": "", "interfaces": []}
        build_docx(parsed, {}, out)
        assert Path(out).exists()

    def test_empty_interfaces_no_interface_tables(self, tmp_path):
        out = str(tmp_path / "out.docx")
        parsed = {"hostname": "EMPTY-SW", "mgmt_ip": "", "interfaces": []}
        build_docx(parsed, {}, out)
        doc = Document(out)
        # No interface data tables (only header + info + 2 section headers)
        assert len(doc.tables) == 4

    def test_48_port_config_completes(self, tmp_path):
        lines = ["hostname SWITCH-48P\n"]
        for i in range(1, 49):
            lines += [
                f"interface GigabitEthernet1/0/{i}\n",
                f" description PC-{i}\n",
                " switchport mode access\n",
                f" switchport access vlan {(i % 10) + 1}\n",
            ]
        lines.append("interface Vlan1\n ip address 10.0.0.1 255.255.255.0\n")
        cfg = "".join(lines)

        out = str(tmp_path / "out_48p.docx")
        parsed = parse_showrun(cfg)
        build_docx(parsed, {"model": "Catalyst 2960-48"}, out)

        doc = Document(out)
        physical, _ = classify_interfaces(parsed["interfaces"])
        assert len(physical) == 48
        assert Path(out).exists()

    def test_cyrillic_hostname_renders(self, tmp_path):
        out = str(tmp_path / "out.docx")
        parsed = parse_showrun("hostname ТЕСТ-СВІЧ\n")
        build_docx(parsed, {}, out)
        header_text = Document(out).tables[0].cell(0, 0).paragraphs[0].text
        assert "ТЕСТ-СВІЧ" in header_text

    def test_output_path_respects_given_path(self, tmp_path):
        out = str(tmp_path / "subdir" / "output.docx")
        (tmp_path / "subdir").mkdir()
        build_docx(parse_showrun(MINIMAL_CONFIG), {}, out)
        assert Path(out).exists()


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _all_cell_texts(table) -> list[str]:
    """Collect all paragraph texts from every cell in a table."""
    texts = []
    for row in table.rows:
        for cell in row.cells:
            for para in cell.paragraphs:
                texts.append(para.text)
    return texts
