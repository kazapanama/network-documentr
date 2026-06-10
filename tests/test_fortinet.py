"""
Unit tests for the Fortinet (FortiGate / FortiSwitch) parser:
  detect_vendor / _forti_section / parse_fortinet / parse_config
  parse_version_inventory (Fortinet patterns)
"""
import textwrap
import pytest

from main import (
    detect_vendor,
    parse_config,
    parse_fortinet,
    parse_showrun,
    parse_version_inventory,
    classify_interfaces,
    format_load_status,
    _forti_section,
    _forti_unquote,
    _forti_values,
    _ip_with_prefix,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Sample configs
# ─────────────────────────────────────────────────────────────────────────────

FGT_CONFIG = textwrap.dedent("""\
    #config-version=FGT60E-6.4.5-FW-build1828-210217:opmode=0:vdom=0:user=admin
    #conf_file_ver=12345
    #buildno=1828
    config system global
        set admintimeout 30
        set hostname "FGT-OFFICE"
        set timezone 26
    end
    config system interface
        edit "wan1"
            set vdom "root"
            set ip 203.0.113.2 255.255.255.252
            set allowaccess ping
            set type physical
            set alias "ISP-1"
            set role wan
            config ipv6
                set ip6-mode static
            end
        next
        edit "internal"
            set vdom "root"
            set ip 192.168.1.1 255.255.255.0
            set allowaccess ping https ssh
            set type hard-switch
            set role lan
        next
        edit "mgmt"
            set vdom "root"
            set ip 10.255.1.1 255.255.255.0
            set allowaccess ping https ssh
            set type physical
            set dedicated-to management
        next
        edit "vlan100"
            set vdom "root"
            set ip 10.0.100.1 255.255.255.0
            set allowaccess ping
            set description "Users floor 1"
            set role lan
            set interface "internal"
            set vlanid 100
        next
        edit "agg1"
            set vdom "root"
            set type aggregate
            set member "port1" "port2"
        next
        edit "port1"
            set vdom "root"
            set type physical
        next
        edit "port2"
            set vdom "root"
            set type physical
            set status down
        next
        edit "Lo0"
            set vdom "root"
            set ip 1.1.1.1 255.255.255.255
            set type loopback
        next
        edit "VPN-tun"
            set vdom "root"
            set type tunnel
            set interface "wan1"
        next
        edit "dhcp-wan"
            set vdom "root"
            set mode dhcp
            set type physical
            set ip 0.0.0.0 0.0.0.0
        next
    end
""")

FSW_CONFIG = textwrap.dedent("""\
    #config-version=S248EF-7.0.4-FW-build0179-220318:opmode=0:vdom=0:user=admin
    config system global
        set hostname "FSW-ACCESS-01"
    end
    config system interface
        edit "internal"
            set ip 10.10.5.20 255.255.255.0
            set allowaccess ping https ssh
            set type vlan
            set vlanid 5
        next
    end
    config switch physical-port
        edit "port1"
            set description "AP poverh 1"
            set speed auto
        next
        edit "port2"
            set status down
        next
        edit "port49"
        next
        edit "port50"
        next
    end
    config switch trunk
        edit "TRK-CORE"
            set mode lacp-active
            set members "port49" "port50"
        next
    end
    config switch vlan
        edit 1
        next
        edit 5
            set description "MGMT"
        next
        edit 10
            set description "USERS"
        next
        edit 99
            set description "UNUSED"
        next
    end
    config switch interface
        edit "port1"
            set native-vlan 10
            set allowed-vlans 10,20
        next
        edit "port2"
            set native-vlan 10
            set security-mode 802.1X
        next
        edit "TRK-CORE"
            set native-vlan 1
            set allowed-vlans 5,10,20
        next
        edit "internal"
            set native-vlan 5
        next
    end
""")

CISCO_CONFIG = textwrap.dedent("""\
    hostname CORE-SW-01
    interface GigabitEthernet1/0/1
     switchport mode access
     switchport access vlan 10
""")


def _by_name(parsed: dict, name: str) -> dict:
    return next(i for i in parsed["interfaces"] if i["name"] == name)


# ─────────────────────────────────────────────────────────────────────────────
#  detect_vendor / parse_config dispatch
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectVendor:

    def test_fortigate_by_config_version(self):
        assert detect_vendor(FGT_CONFIG) == "fortinet"

    def test_fortiswitch_detected(self):
        assert detect_vendor(FSW_CONFIG) == "fortinet"

    def test_config_system_global_without_header(self):
        text = 'config system global\n    set hostname "X"\nend\n'
        assert detect_vendor(text) == "fortinet"

    def test_config_switch_interface_without_header(self):
        text = 'config switch interface\n    edit "port1"\n    next\nend\n'
        assert detect_vendor(text) == "fortinet"

    def test_cisco_config(self):
        assert detect_vendor(CISCO_CONFIG) == "cisco"

    def test_empty_text_defaults_cisco(self):
        assert detect_vendor("") == "cisco"


class TestParseConfigDispatch:

    def test_cisco_routed_to_parse_showrun(self):
        r = parse_config(CISCO_CONFIG)
        assert r["hostname"] == "CORE-SW-01"
        assert r["interfaces"][0]["name"] == "GigabitEthernet1/0/1"

    def test_fortinet_routed_to_parse_fortinet(self):
        r = parse_config(FGT_CONFIG)
        assert r["hostname"] == "FGT-OFFICE"

    def test_same_schema_keys(self):
        rc = parse_config(CISCO_CONFIG)
        rf = parse_config(FGT_CONFIG)
        for key in ("hostname", "mgmt_ip", "interfaces", "vlans"):
            assert key in rc
            assert key in rf

    def test_fortinet_iface_has_all_builder_fields(self):
        r = parse_config(FGT_CONFIG)
        cisco_iface = parse_showrun(CISCO_CONFIG)["interfaces"][0]
        for field in cisco_iface:
            assert field in r["interfaces"][0], f"Missing key: {field}"


# ─────────────────────────────────────────────────────────────────────────────
#  _forti_section / helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestFortiSection:

    def test_basic_edits(self):
        entries = _forti_section(FSW_CONFIG, "switch physical-port")
        names = [n for n, _ in entries]
        assert names == ["port1", "port2", "port49", "port50"]

    def test_settings_extracted(self):
        entries = dict(_forti_section(FSW_CONFIG, "switch physical-port"))
        assert entries["port1"]["description"] == '"AP poverh 1"'
        assert entries["port2"]["status"] == "down"

    def test_missing_section_returns_empty(self):
        assert _forti_section(FSW_CONFIG, "router static") == []

    def test_nested_config_skipped(self):
        # 'config ipv6' inside wan1 must not leak its sets into the edit
        entries = dict(_forti_section(FGT_CONFIG, "system interface"))
        assert "ip6-mode" not in entries["wan1"]

    def test_numeric_edit_names(self):
        entries = _forti_section(FSW_CONFIG, "switch vlan")
        assert [n for n, _ in entries] == ["1", "5", "10", "99"]

    def test_multiple_sections_merged(self):
        text = (
            'config system interface\n  edit "a"\n  next\nend\n'
            'config system interface\n  edit "b"\n  next\nend\n'
        )
        names = [n for n, _ in _forti_section(text, "system interface")]
        assert names == ["a", "b"]

    def test_unquote(self):
        assert _forti_unquote('"hello"') == "hello"
        assert _forti_unquote("plain") == "plain"
        assert _forti_unquote('""') == ""

    def test_values_quoted(self):
        assert _forti_values('"port1" "port2"') == ["port1", "port2"]

    def test_values_unquoted(self):
        assert _forti_values("port1 port2") == ["port1", "port2"]

    def test_ip_with_prefix(self):
        assert _ip_with_prefix("203.0.113.2 255.255.255.252") == "203.0.113.2/30"
        assert _ip_with_prefix("10.0.0.1 255.255.255.0") == "10.0.0.1/24"
        assert _ip_with_prefix("10.0.0.1") == "10.0.0.1"
        assert _ip_with_prefix("") == ""


# ─────────────────────────────────────────────────────────────────────────────
#  FortiGate
# ─────────────────────────────────────────────────────────────────────────────

class TestParseFortiGate:

    @pytest.fixture()
    def parsed(self):
        return parse_fortinet(FGT_CONFIG)

    def test_hostname(self, parsed):
        assert parsed["hostname"] == "FGT-OFFICE"

    def test_mgmt_ip_prefers_mgmt_interface(self, parsed):
        assert parsed["mgmt_ip"] == "10.255.1.1"

    def test_physical_interface_classified(self, parsed):
        assert _by_name(parsed, "wan1")["iface_class"] == "physical"
        assert _by_name(parsed, "port1")["iface_class"] == "physical"

    def test_physical_with_ip_routed_mode(self, parsed):
        assert _by_name(parsed, "wan1")["mode"] == "routed"

    def test_physical_ip_in_notes(self, parsed):
        assert "IP: 203.0.113.2/30" in _by_name(parsed, "wan1")["notes"]

    def test_alias_in_description(self, parsed):
        assert "ISP-1" in _by_name(parsed, "wan1")["description"]

    def test_role_in_notes(self, parsed):
        assert "role: wan" in _by_name(parsed, "wan1")["notes"]

    def test_allowaccess_in_notes(self, parsed):
        assert "ping https ssh" in _by_name(parsed, "mgmt")["notes"]

    def test_dedicated_mgmt_in_notes(self, parsed):
        assert "dedicated mgmt" in _by_name(parsed, "mgmt")["notes"]

    def test_vlan_interface_logical(self, parsed):
        vlan = _by_name(parsed, "vlan100")
        assert vlan["iface_class"] == "logical"
        assert vlan["row_kind"] == "vlan"
        assert vlan["access_vlan"] == "100"
        assert "VLAN 100 @ internal" in vlan["notes"]
        assert vlan["ip_address"] == "10.0.100.1 255.255.255.0"
        assert vlan["mode"] == "routed"

    def test_vlan_description_kept(self, parsed):
        assert "Users floor 1" in _by_name(parsed, "vlan100")["description"]

    def test_aggregate_logical_po(self, parsed):
        agg = _by_name(parsed, "agg1")
        assert agg["iface_class"] == "logical"
        assert agg["row_kind"] == "po"
        assert agg["mode"] == "lacp"
        assert "members: port1, port2" in agg["notes"]

    def test_aggregate_members_noted(self, parsed):
        assert "agg1 member" in _by_name(parsed, "port1")["notes"]
        assert "agg1 member" in _by_name(parsed, "port2")["notes"]

    def test_status_down_is_shutdown(self, parsed):
        port2 = _by_name(parsed, "port2")
        assert port2["shutdown"] is True
        assert "shutdown" in port2["notes"]

    def test_loopback_logical(self, parsed):
        lo = _by_name(parsed, "Lo0")
        assert lo["iface_class"] == "logical"
        assert lo["row_kind"] == "lo"
        assert lo["mode"] == "routed"

    def test_tunnel_logical(self, parsed):
        tun = _by_name(parsed, "VPN-tun")
        assert tun["iface_class"] == "logical"
        assert "tunnel" in tun["notes"]

    def test_hard_switch_logical(self, parsed):
        sw = _by_name(parsed, "internal")
        assert sw["iface_class"] == "logical"
        assert sw["mode"] == "switch"

    def test_dhcp_mode(self, parsed):
        dhcp = _by_name(parsed, "dhcp-wan")
        assert dhcp["mode"] == "dhcp"
        assert dhcp["ip_address"] == ""  # 0.0.0.0 must be skipped

    def test_no_vlan_definitions_for_fortigate(self, parsed):
        assert parsed["vlans"] == []

    def test_mgmt_fallback_allowaccess(self):
        text = textwrap.dedent("""\
            config system global
                set hostname "FGT"
            end
            config system interface
                edit "wan1"
                    set ip 203.0.113.2 255.255.255.252
                    set allowaccess ping
                next
                edit "lan"
                    set ip 192.168.1.1 255.255.255.0
                    set allowaccess ping https ssh
                next
            end
        """)
        assert parse_fortinet(text)["mgmt_ip"] == "192.168.1.1"

    def test_mgmt_fallback_first_ip(self):
        text = textwrap.dedent("""\
            config system interface
                edit "wan1"
                    set ip 203.0.113.2 255.255.255.252
                next
            end
        """)
        assert parse_fortinet(text)["mgmt_ip"] == "203.0.113.2"

    def test_format_load_status_counts(self, parsed):
        status = format_load_status(parsed)
        # physical: wan1, mgmt, port1, port2, dhcp-wan
        assert "Порти: 5" in status
        assert "Po: 1" in status
        assert "VLAN: 1" in status
        assert "Lo: 1" in status
        assert "MGMT: 10.255.1.1" in status


# ─────────────────────────────────────────────────────────────────────────────
#  FortiSwitch
# ─────────────────────────────────────────────────────────────────────────────

class TestParseFortiSwitch:

    @pytest.fixture()
    def parsed(self):
        return parse_fortinet(FSW_CONFIG)

    def test_hostname(self, parsed):
        assert parsed["hostname"] == "FSW-ACCESS-01"

    def test_mgmt_ip_from_system_interface(self, parsed):
        assert parsed["mgmt_ip"] == "10.10.5.20"

    def test_physical_ports_in_order(self, parsed):
        physical, _ = classify_interfaces(parsed["interfaces"])
        assert [i["name"] for i in physical] == ["port1", "port2", "port49", "port50"]

    def test_description_from_physical_port(self, parsed):
        assert _by_name(parsed, "port1")["description"] == "AP poverh 1"

    def test_trunk_port_mode_and_vlans(self, parsed):
        p1 = _by_name(parsed, "port1")
        assert p1["mode"] == "trunk"
        assert p1["trunk_vlans"] == "10,20"
        assert p1["native_vlan"] == "10"

    def test_access_port(self, parsed):
        p2 = _by_name(parsed, "port2")
        assert p2["mode"] == "access"
        assert p2["access_vlan"] == "10"

    def test_status_down_is_shutdown(self, parsed):
        p2 = _by_name(parsed, "port2")
        assert p2["shutdown"] is True
        assert "shutdown" in p2["notes"]

    def test_security_mode_noted(self, parsed):
        p2 = _by_name(parsed, "port2")
        assert p2["port_security"] is True
        assert "802.1X" in p2["notes"]

    def test_trunk_members_noted_on_ports(self, parsed):
        assert "TRK-CORE member" in _by_name(parsed, "port49")["notes"]
        assert "TRK-CORE member" in _by_name(parsed, "port50")["notes"]

    def test_lag_trunk_logical(self, parsed):
        trk = _by_name(parsed, "TRK-CORE")
        assert trk["iface_class"] == "logical"
        assert trk["row_kind"] == "po"
        assert trk["mode"] == "lacp-active"
        assert "members: port49, port50" in trk["notes"]
        assert "VLANs: 5,10,20" in trk["notes"]
        assert "native: 1" in trk["notes"]

    def test_internal_logical_with_ip(self, parsed):
        internal = _by_name(parsed, "internal")
        assert internal["iface_class"] == "logical"
        assert internal["row_kind"] == "vlan"
        assert internal["ip_address"] == "10.10.5.20 255.255.255.0"
        assert internal["mode"] == "routed"
        assert "VLAN 5" in internal["notes"]

    def test_internal_not_duplicated_as_physical(self, parsed):
        names = [i["name"] for i in parsed["interfaces"]]
        assert names.count("internal") == 1

    def test_vlan_definitions(self, parsed):
        ids = [v["id"] for v in parsed["vlans"]]
        assert ids == ["1", "5", "10", "99"]
        names = {v["id"]: v["name"] for v in parsed["vlans"]}
        assert names["5"] == "MGMT"
        assert names["10"] == "USERS"
        assert names["1"] == ""

    def test_vlan_used_marking(self, parsed):
        used = {v["id"]: v["used"] for v in parsed["vlans"]}
        assert used["1"] is True    # native on TRK-CORE
        assert used["5"] is True    # allowed on TRK-CORE
        assert used["10"] is True   # access on port2 / trunk on port1
        assert used["99"] is False  # referenced nowhere

    def test_allowed_vlans_space_separated(self):
        text = textwrap.dedent("""\
            config switch interface
                edit "port1"
                    set native-vlan 1
                    set allowed-vlans 10 20 30
                next
            end
        """)
        p1 = parse_fortinet(text)["interfaces"][0]
        assert p1["trunk_vlans"] == "10,20,30"

    def test_allowed_vlans_all(self):
        text = textwrap.dedent("""\
            config switch interface
                edit "port1"
                    set native-vlan 1
                    set allowed-vlans-all enable
                next
            end
        """)
        p1 = parse_fortinet(text)["interfaces"][0]
        assert p1["mode"] == "trunk"
        assert p1["trunk_vlans"] == "all"

    def test_format_load_status_counts(self, parsed):
        status = format_load_status(parsed)
        assert "Порти: 4" in status
        assert "Po: 1" in status
        assert "MGMT: 10.10.5.20" in status


# ─────────────────────────────────────────────────────────────────────────────
#  parse_version_inventory — Fortinet
# ─────────────────────────────────────────────────────────────────────────────

class TestVersionInventoryFortinet:

    def test_model_from_config_version(self):
        r = parse_version_inventory(FGT_CONFIG)
        assert r["model"] == "FGT60E"
        assert r["serial"] == ""

    def test_fortiswitch_model(self):
        r = parse_version_inventory(FSW_CONFIG)
        assert r["model"] == "S248EF"

    def test_serial_from_get_system_status(self):
        text = FGT_CONFIG + "\nVersion: FortiGate-60E v6.4.5\nSerial-Number: FGT60E4Q16012345\n"
        r = parse_version_inventory(text)
        assert r["model"] == "FGT60E"
        assert r["serial"] == "FGT60E4Q16012345"

    def test_cisco_patterns_still_win(self):
        text = "PID: C9300-48U , VID: V01 , SN: FDO1234ABCD\n#config-version=FGT60E-6.4.5\n"
        r = parse_version_inventory(text)
        assert r["model"] == "C9300-48U"
        assert r["serial"] == "FDO1234ABCD"
