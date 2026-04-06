"""
Unit tests for parser functions:
  read_file_safe / short_iface / parse_showrun / classify_interfaces
  format_load_status
"""
import textwrap
import pytest

from main import (
    read_file_safe,
    short_iface,
    parse_showrun,
    classify_interfaces,
    format_load_status,
    parse_version_inventory,
)


# ─────────────────────────────────────────────────────────────────────────────
#  short_iface
# ─────────────────────────────────────────────────────────────────────────────

class TestShortIface:

    # ── known prefixes ────────────────────────────────────────────────────────

    def test_gigabit_ethernet(self):
        assert short_iface("GigabitEthernet1/0/1") == "Gi1/0/1"

    def test_gigabit_ethernet_two_part(self):
        assert short_iface("GigabitEthernet0/1") == "Gi0/1"

    def test_fast_ethernet(self):
        assert short_iface("FastEthernet0/1") == "Fa0/1"

    def test_ten_gigabit(self):
        assert short_iface("TenGigabitEthernet1/1/1") == "Te1/1/1"

    def test_twenty_five_gig(self):
        assert short_iface("TwentyFiveGigE1/0/1") == "Twe1/0/1"

    def test_forty_gigabit(self):
        assert short_iface("FortyGigabitEthernet1/0/1") == "Fo1/0/1"

    def test_hundred_gig(self):
        assert short_iface("HundredGigE1/0/1") == "Hu1/0/1"

    def test_port_channel_capital(self):
        assert short_iface("Port-channel10") == "Po10"

    def test_port_channel_lower(self):
        assert short_iface("port-channel10") == "Po10"

    def test_vlan(self):
        assert short_iface("Vlan100") == "Vlan100"

    def test_vlan_single_digit(self):
        assert short_iface("Vlan1") == "Vlan1"

    def test_loopback(self):
        assert short_iface("Loopback0") == "Lo0"

    def test_management(self):
        assert short_iface("Management0") == "Mgmt0"

    def test_management_numbered(self):
        assert short_iface("Management1") == "Mgmt1"

    # ── unknown prefix ────────────────────────────────────────────────────────

    def test_unknown_prefix_unchanged(self):
        assert short_iface("Serial1/0") == "Serial1/0"

    def test_empty_string(self):
        assert short_iface("") == ""

    def test_partial_prefix_not_matched(self):
        # "GigabitOnly" does NOT start with "GigabitEthernet" → returned as-is
        assert short_iface("GigabitOnly") == "GigabitOnly"


# ─────────────────────────────────────────────────────────────────────────────
#  parse_showrun
# ─────────────────────────────────────────────────────────────────────────────

def _p(raw: str) -> dict:
    """Helper: dedent and parse."""
    return parse_showrun(textwrap.dedent(raw))


class TestParseShowrunHostname:

    def test_hostname_extracted(self):
        assert _p("hostname CORE-SW-01\n")["hostname"] == "CORE-SW-01"

    def test_hostname_missing_returns_empty(self):
        assert _p("! no hostname\n")["hostname"] == ""

    def test_hostname_must_be_start_of_line(self):
        # Indented "hostname" (inside interface block etc.) should not match.
        # Note: do NOT use _p() here — textwrap.dedent would strip the leading space.
        assert parse_showrun(" hostname FAKE\n")["hostname"] == ""

    def test_hostname_alphanumeric_with_dashes(self):
        assert _p("hostname SW-01-FLOOR3\n")["hostname"] == "SW-01-FLOOR3"


class TestParseShowrunInterfaces:

    def test_no_interfaces_returns_empty_list(self):
        assert _p("hostname SW\n")["interfaces"] == []

    def test_single_interface_name(self):
        r = _p("""
            interface GigabitEthernet1/0/1
        """)
        assert r["interfaces"][0]["name"] == "GigabitEthernet1/0/1"

    def test_interface_description(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             description Uplink to Core
        """)
        assert r["interfaces"][0]["description"] == "Uplink to Core"

    def test_description_empty_by_default(self):
        r = _p("""
            interface GigabitEthernet1/0/1
        """)
        assert r["interfaces"][0]["description"] == ""

    def test_multiple_interfaces_all_parsed(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             description Port 1
            interface GigabitEthernet1/0/2
             description Port 2
            interface GigabitEthernet1/0/3
        """)
        assert len(r["interfaces"]) == 3
        names = {i["name"] for i in r["interfaces"]}
        assert names == {
            "GigabitEthernet1/0/1",
            "GigabitEthernet1/0/2",
            "GigabitEthernet1/0/3",
        }

    def test_result_has_all_required_keys(self):
        r = _p("""
            interface GigabitEthernet1/0/1
        """)
        iface = r["interfaces"][0]
        for field in (
            "name", "description", "mode", "access_vlan",
            "native_vlan", "trunk_vlans", "ip_address",
            "shutdown", "notes", "iface_class",
            "voice_vlan", "stp_portfast", "stp_rootguard",
            "stp_bpduguard", "port_security", "port_security_max",
            "port_security_violation", "port_security_macs", "port_security_sticky",
        ):
            assert field in iface, f"Missing key: {field}"


class TestParseShowrunAccessPort:

    def test_access_mode(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport mode access
        """)
        assert r["interfaces"][0]["mode"] == "access"

    def test_access_vlan(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport mode access
             switchport access vlan 20
        """)
        assert r["interfaces"][0]["access_vlan"] == "20"

    def test_access_vlan_without_explicit_mode(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport access vlan 50
        """)
        assert r["interfaces"][0]["access_vlan"] == "50"


class TestParseShowrunTrunkPort:

    def test_trunk_mode(self):
        r = _p("""
            interface GigabitEthernet1/0/2
             switchport mode trunk
        """)
        assert r["interfaces"][0]["mode"] == "trunk"

    def test_trunk_allowed_vlans(self):
        r = _p("""
            interface GigabitEthernet1/0/2
             switchport mode trunk
             switchport trunk allowed vlan 10,20,30
        """)
        assert r["interfaces"][0]["trunk_vlans"] == "10,20,30"

    def test_trunk_native_vlan(self):
        r = _p("""
            interface GigabitEthernet1/0/2
             switchport mode trunk
             switchport trunk native vlan 99
        """)
        assert r["interfaces"][0]["native_vlan"] == "99"

    def test_trunk_vlan_add_accumulates(self):
        r = _p("""
            interface GigabitEthernet1/0/2
             switchport mode trunk
             switchport trunk allowed vlan 1,2,3
             switchport trunk allowed vlan add 4,5,6
        """)
        vlans = r["interfaces"][0]["trunk_vlans"]
        assert "1,2,3" in vlans
        assert "4,5,6" in vlans

    def test_trunk_multiple_add_lines(self):
        r = _p("""
            interface GigabitEthernet1/0/2
             switchport mode trunk
             switchport trunk allowed vlan 100
             switchport trunk allowed vlan add 200
             switchport trunk allowed vlan add 300
        """)
        vlans = r["interfaces"][0]["trunk_vlans"]
        assert "100" in vlans
        assert "200" in vlans
        assert "300" in vlans


class TestParseShowrunRoutedInterface:

    def test_no_switchport_sets_routed(self):
        r = _p("""
            interface GigabitEthernet0/0
             no switchport
             ip address 10.0.0.1 255.255.255.0
        """)
        iface = r["interfaces"][0]
        assert iface["mode"] == "routed"
        assert iface["ip_address"] == "10.0.0.1 255.255.255.0"

    def test_ip_address_stored_fully(self):
        r = _p("""
            interface Vlan10
             ip address 192.168.10.1 255.255.255.0
        """)
        assert r["interfaces"][0]["ip_address"] == "192.168.10.1 255.255.255.0"


class TestParseShowrunModeFallback:

    def test_vlan_interface_without_mode_defaults_routed(self):
        r = _p("""
            interface Vlan10
             ip address 192.168.10.1 255.255.255.0
        """)
        assert r["interfaces"][0]["mode"] == "routed"

    def test_vlan_interface_no_ip_still_routed(self):
        # Vlan name triggers routed fallback even without ip
        r = _p("""
            interface Vlan1
             no ip address
        """)
        assert r["interfaces"][0]["mode"] == "routed"

    def test_port_channel_without_mode_defaults_trunk(self):
        r = _p("""
            interface Port-channel1
             description LAG Uplink
        """)
        assert r["interfaces"][0]["mode"] == "trunk"

    def test_port_channel_lowercase_defaults_trunk(self):
        r = _p("""
            interface port-channel2
        """)
        assert r["interfaces"][0]["mode"] == "trunk"

    def test_interface_with_ip_but_not_vlan_not_trunk_defaults_routed(self):
        # An interface that has an IP but no "no switchport" and no vlan name
        # → mode fallback via ip_address check
        r = _p("""
            interface GigabitEthernet0/0
             ip address 172.16.0.1 255.255.255.0
        """)
        assert r["interfaces"][0]["mode"] == "routed"


class TestParseShowrunShutdown:

    def test_shutdown_flag_true(self):
        r = _p("""
            interface GigabitEthernet1/0/5
             shutdown
        """)
        assert r["interfaces"][0]["shutdown"] is True

    def test_no_shutdown_flag_false(self):
        r = _p("""
            interface GigabitEthernet1/0/6
             description Active
        """)
        assert r["interfaces"][0]["shutdown"] is False

    def test_shutdown_appended_to_notes(self):
        r = _p("""
            interface GigabitEthernet1/0/7
             shutdown
        """)
        assert "shutdown" in r["interfaces"][0]["notes"]

    def test_shutdown_does_not_duplicate_notes(self):
        r = _p("""
            interface GigabitEthernet1/0/7
             shutdown
        """)
        notes = r["interfaces"][0]["notes"]
        assert notes.count("shutdown") == 1


class TestParseShowrunChannelGroup:

    def test_channel_group_sets_notes(self):
        r = _p("""
            interface GigabitEthernet1/0/8
             channel-group 2 mode active
        """)
        assert r["interfaces"][0]["notes"] == "Po2 member"

    def test_channel_group_number_extracted(self):
        r = _p("""
            interface GigabitEthernet1/0/9
             channel-group 10 mode on
        """)
        assert r["interfaces"][0]["notes"] == "Po10 member"

    def test_channel_group_with_shutdown_combined(self):
        r = _p("""
            interface GigabitEthernet1/0/10
             channel-group 3 mode active
             shutdown
        """)
        notes = r["interfaces"][0]["notes"]
        assert "Po3 member" in notes
        assert "shutdown" in notes


class TestParseShowrunClassification:

    @pytest.mark.parametrize("prefix,expected", [
        ("GigabitEthernet",     "physical"),
        ("FastEthernet",        "physical"),
        ("TenGigabitEthernet",  "physical"),
        ("TwentyFiveGigE",      "physical"),
        ("FortyGigabitEthernet","physical"),
        ("HundredGigE",         "physical"),
        ("Management",          "physical"),
        ("Port-channel",        "logical"),
        ("port-channel",        "logical"),
        ("Vlan",                "logical"),
        ("Loopback",            "logical"),
    ])
    def test_classification(self, prefix, expected):
        r = _p(f"""
            interface {prefix}1
        """)
        assert r["interfaces"][0]["iface_class"] == expected

    def test_unknown_prefix_defaults_physical(self):
        r = _p("""
            interface Serial0/0/0
        """)
        assert r["interfaces"][0]["iface_class"] == "physical"


class TestParseShowrunMgmtIp:

    def test_mgmt_ip_from_ssh_source_interface(self):
        r = _p("""
            ip ssh source-interface Vlan99
            interface Vlan99
             ip address 10.99.99.1 255.255.255.0
            interface GigabitEthernet1/0/1
             ip address 172.16.0.1 255.255.255.0
        """)
        assert r["mgmt_ip"] == "10.99.99.1"

    def test_mgmt_ip_ssh_source_picks_correct_interface(self):
        # ssh source is Vlan10, not Vlan20
        r = _p("""
            ip ssh source-interface Vlan10
            interface Vlan20
             ip address 192.168.20.1 255.255.255.0
            interface Vlan10
             ip address 192.168.10.1 255.255.255.0
        """)
        assert r["mgmt_ip"] == "192.168.10.1"

    def test_mgmt_ip_fallback_to_first_ip_when_no_ssh_source(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             ip address 172.16.1.1 255.255.255.0
            interface Vlan10
             ip address 192.168.1.1 255.255.255.0
        """)
        assert r["mgmt_ip"] == "172.16.1.1"

    def test_mgmt_ip_empty_when_no_interfaces_have_ip(self):
        r = _p("""
            hostname SW
            interface GigabitEthernet1/0/1
             switchport mode access
        """)
        assert r["mgmt_ip"] == ""

    def test_mgmt_ip_only_host_part(self):
        # Must return only the IP, not "IP mask"
        r = _p("""
            interface Vlan1
             ip address 10.0.0.1 255.255.255.0
        """)
        assert r["mgmt_ip"] == "10.0.0.1"
        assert " " not in r["mgmt_ip"]

    def test_ssh_source_iface_key_stored(self):
        r = _p("ip ssh source-interface Vlan99\n")
        assert r.get("ssh_source_iface") == "Vlan99"

    def test_ssh_source_iface_empty_when_absent(self):
        r = _p("hostname SW\n")
        assert r.get("ssh_source_iface", "") == ""

    def test_ssh_source_iface_not_found_falls_back(self):
        # SSH source references Vlan99 but that interface has no IP → fallback to first IP
        r = _p("""
            ip ssh source-interface Vlan99
            interface Vlan99
            interface GigabitEthernet1/0/1
             ip address 10.1.1.1 255.255.255.0
        """)
        assert r["mgmt_ip"] == "10.1.1.1"


class TestParseShowrunIntegration:

    def test_full_realistic_config(self):
        cfg = textwrap.dedent("""
            hostname CORE-SW-01
            ip ssh source-interface Vlan99
            !
            interface GigabitEthernet1/0/1
             description Server Farm
             switchport mode access
             switchport access vlan 100
            !
            interface GigabitEthernet1/0/2
             description Trunk to Distribution
             switchport mode trunk
             switchport trunk native vlan 1
             switchport trunk allowed vlan 10,20,30,40
             switchport trunk allowed vlan add 50,60
            !
            interface GigabitEthernet1/0/3
             description LAG member
             channel-group 1 mode active
             shutdown
            !
            interface Port-channel1
             description Uplink LAG
             switchport mode trunk
             switchport trunk allowed vlan 1-100
            !
            interface Vlan99
             description Management
             ip address 10.99.99.1 255.255.255.0
            !
            interface Loopback0
             ip address 1.1.1.1 255.255.255.255
        """)
        r = parse_showrun(cfg)

        assert r["hostname"] == "CORE-SW-01"
        assert r["mgmt_ip"] == "10.99.99.1"
        assert len(r["interfaces"]) == 6

        physical = [i for i in r["interfaces"] if i["iface_class"] == "physical"]
        logical  = [i for i in r["interfaces"] if i["iface_class"] == "logical"]
        assert len(physical) == 3
        assert len(logical) == 3

        gi2 = next(i for i in r["interfaces"] if i["name"] == "GigabitEthernet1/0/2")
        assert "10,20,30,40" in gi2["trunk_vlans"]
        assert "50,60" in gi2["trunk_vlans"]

        gi3 = next(i for i in r["interfaces"] if i["name"] == "GigabitEthernet1/0/3")
        assert gi3["shutdown"] is True
        assert "Po1 member" in gi3["notes"]
        assert "shutdown" in gi3["notes"]


# ─────────────────────────────────────────────────────────────────────────────
#  classify_interfaces
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyInterfaces:

    def test_empty_list(self):
        phys, log = classify_interfaces([])
        assert phys == [] and log == []

    def test_all_physical(self):
        ifaces = [{"iface_class": "physical"}, {"iface_class": "physical"}]
        phys, log = classify_interfaces(ifaces)
        assert len(phys) == 2
        assert len(log) == 0

    def test_all_logical(self):
        ifaces = [{"iface_class": "logical"}, {"iface_class": "logical"}]
        phys, log = classify_interfaces(ifaces)
        assert len(phys) == 0
        assert len(log) == 2

    def test_mixed(self):
        ifaces = [
            {"iface_class": "physical", "name": "Gi1/0/1"},
            {"iface_class": "logical",  "name": "Vlan10"},
            {"iface_class": "physical", "name": "Gi1/0/2"},
            {"iface_class": "logical",  "name": "Po1"},
        ]
        phys, log = classify_interfaces(ifaces)
        assert len(phys) == 2
        assert len(log) == 2
        assert all(i["iface_class"] == "physical" for i in phys)
        assert all(i["iface_class"] == "logical"  for i in log)

    def test_returns_same_objects_not_copies(self):
        obj = {"iface_class": "physical", "name": "Gi1/0/1"}
        phys, _ = classify_interfaces([obj])
        assert phys[0] is obj

    def test_order_preserved(self):
        ifaces = [
            {"iface_class": "physical", "name": "A"},
            {"iface_class": "physical", "name": "B"},
            {"iface_class": "physical", "name": "C"},
        ]
        phys, _ = classify_interfaces(ifaces)
        assert [i["name"] for i in phys] == ["A", "B", "C"]


# ─────────────────────────────────────────────────────────────────────────────
#  read_file_safe
# ─────────────────────────────────────────────────────────────────────────────

class TestReadFileSafe:

    def test_reads_utf8_file(self, tmp_path):
        f = tmp_path / "config.txt"
        f.write_text("hostname TEST-UTF8\n", encoding="utf-8")
        result = read_file_safe(str(f))
        assert "hostname TEST-UTF8" in result

    def test_reads_cp1251_cyrillic(self, tmp_path):
        f = tmp_path / "config_cp1251.txt"
        content = "hostname ТЕСТ\ninterface GigabitEthernet1/0/1\n"
        f.write_bytes(content.encode("cp1251"))
        result = read_file_safe(str(f))
        assert "hostname" in result

    def test_reads_latin1_file(self, tmp_path):
        f = tmp_path / "config_latin1.txt"
        # Bytes invalid in UTF-8, valid in Latin-1
        f.write_bytes(b"hostname SW\nversion 15.2\n\x80\x81\x82\n")
        result = read_file_safe(str(f))
        assert "hostname SW" in result

    def test_returns_string_type(self, tmp_path):
        f = tmp_path / "config.txt"
        f.write_text("test content\n", encoding="utf-8")
        assert isinstance(read_file_safe(str(f)), str)

    def test_empty_file_returns_empty_string(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        assert read_file_safe(str(f)) == ""

    def test_multiline_content_preserved(self, tmp_path):
        content = "hostname SW\nversion 15.2\n!\ninterface GigabitEthernet1/0/1\n"
        f = tmp_path / "multi.txt"
        f.write_text(content, encoding="utf-8")
        result = read_file_safe(str(f))
        assert result == content


# ─────────────────────────────────────────────────────────────────────────────
#  format_load_status
# ─────────────────────────────────────────────────────────────────────────────

def _parsed_from(cfg: str) -> dict:
    return parse_showrun(textwrap.dedent(cfg))


class TestFormatLoadStatus:

    def test_only_physical_ports(self):
        parsed = _parsed_from("""
            interface GigabitEthernet1/0/1
            interface GigabitEthernet1/0/2
        """)
        status = format_load_status(parsed)
        assert "Порти: 2" in status

    def test_mgmt_ip_shown(self):
        parsed = _parsed_from("""
            interface Vlan1
             ip address 10.0.0.1 255.255.255.0
        """)
        status = format_load_status(parsed)
        assert "MGMT: 10.0.0.1" in status

    def test_no_mgmt_ip_omitted(self):
        parsed = _parsed_from("""
            interface GigabitEthernet1/0/1
             switchport mode access
        """)
        status = format_load_status(parsed)
        assert "MGMT" not in status

    def test_port_channel_count_shown(self):
        parsed = _parsed_from("""
            interface Port-channel1
            interface Port-channel2
        """)
        status = format_load_status(parsed)
        assert "Po: 2" in status

    def test_lowercase_port_channel_counted(self):
        parsed = _parsed_from("""
            interface port-channel1
        """)
        status = format_load_status(parsed)
        assert "Po: 1" in status

    def test_vlan_count_shown(self):
        parsed = _parsed_from("""
            interface Vlan10
            interface Vlan20
            interface Vlan30
        """)
        status = format_load_status(parsed)
        assert "VLAN: 3" in status

    def test_loopback_count_shown(self):
        parsed = _parsed_from("""
            interface Loopback0
            interface Loopback1
        """)
        status = format_load_status(parsed)
        assert "Lo: 2" in status

    def test_zero_po_omitted(self):
        parsed = _parsed_from("""
            interface GigabitEthernet1/0/1
        """)
        assert "Po:" not in format_load_status(parsed)

    def test_zero_vlan_omitted(self):
        parsed = _parsed_from("""
            interface GigabitEthernet1/0/1
        """)
        assert "VLAN:" not in format_load_status(parsed)

    def test_zero_loopback_omitted(self):
        parsed = _parsed_from("""
            interface GigabitEthernet1/0/1
        """)
        assert "Lo:" not in format_load_status(parsed)

    def test_separator_between_parts(self):
        parsed = _parsed_from("""
            interface Vlan1
             ip address 10.0.0.1 255.255.255.0
        """)
        status = format_load_status(parsed)
        assert "  ·  " in status

    def test_empty_interfaces(self):
        parsed = {"hostname": "SW", "mgmt_ip": "", "interfaces": []}
        status = format_load_status(parsed)
        assert "Порти: 0" in status
        assert "MGMT" not in status

    def test_full_mix(self):
        parsed = _parsed_from("""
            ip ssh source-interface Vlan99
            interface GigabitEthernet1/0/1
            interface GigabitEthernet1/0/2
            interface Port-channel1
            interface Vlan10
            interface Vlan99
             ip address 10.99.99.1 255.255.255.0
            interface Loopback0
        """)
        status = format_load_status(parsed)
        assert "MGMT: 10.99.99.1" in status
        assert "Порти: 2" in status
        assert "Po: 1" in status
        assert "VLAN: 2" in status
        assert "Lo: 1" in status

    def test_returns_string(self):
        parsed = {"hostname": "SW", "mgmt_ip": "", "interfaces": []}
        assert isinstance(format_load_status(parsed), str)


# ─────────────────────────────────────────────────────────────────────────────
#  Voice VLAN
# ─────────────────────────────────────────────────────────────────────────────

class TestParseShowrunVoiceVlan:

    def test_voice_vlan_parsed(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport voice vlan 10
        """)
        assert r["interfaces"][0]["voice_vlan"] == "10"

    def test_voice_vlan_default_empty(self):
        r = _p("""
            interface GigabitEthernet1/0/1
        """)
        assert r["interfaces"][0]["voice_vlan"] == ""

    def test_voice_vlan_in_notes(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport voice vlan 20
        """)
        assert "Voice:20" in r["interfaces"][0]["notes"]

    def test_voice_vlan_notes_before_shutdown(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport voice vlan 5
             shutdown
        """)
        notes = r["interfaces"][0]["notes"]
        assert notes.index("Voice:5") < notes.index("shutdown")

    def test_voice_vlan_various_numbers(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport voice vlan 999
        """)
        assert r["interfaces"][0]["voice_vlan"] == "999"


# ─────────────────────────────────────────────────────────────────────────────
#  Spanning-tree (PortFast / RootGuard / BPDUGuard)
# ─────────────────────────────────────────────────────────────────────────────

class TestParseShowrunSpanningTree:

    def test_portfast_set(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             spanning-tree portfast
        """)
        assert r["interfaces"][0]["stp_portfast"] is True

    def test_portfast_trunk_also_sets_flag(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             spanning-tree portfast trunk
        """)
        assert r["interfaces"][0]["stp_portfast"] is True

    def test_portfast_default_false(self):
        r = _p("""
            interface GigabitEthernet1/0/1
        """)
        assert r["interfaces"][0]["stp_portfast"] is False

    def test_rootguard_set(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             spanning-tree guard root
        """)
        assert r["interfaces"][0]["stp_rootguard"] is True

    def test_rootguard_default_false(self):
        r = _p("""
            interface GigabitEthernet1/0/1
        """)
        assert r["interfaces"][0]["stp_rootguard"] is False

    def test_bpduguard_set(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             spanning-tree bpduguard enable
        """)
        assert r["interfaces"][0]["stp_bpduguard"] is True

    def test_bpduguard_default_false(self):
        r = _p("""
            interface GigabitEthernet1/0/1
        """)
        assert r["interfaces"][0]["stp_bpduguard"] is False

    def test_portfast_in_notes(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             spanning-tree portfast
        """)
        assert "PortFast" in r["interfaces"][0]["notes"]

    def test_rootguard_in_notes(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             spanning-tree guard root
        """)
        assert "RootGuard" in r["interfaces"][0]["notes"]

    def test_bpduguard_in_notes(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             spanning-tree bpduguard enable
        """)
        assert "BPDUGuard" in r["interfaces"][0]["notes"]

    def test_portfast_before_rootguard_in_notes(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             spanning-tree portfast
             spanning-tree guard root
        """)
        notes = r["interfaces"][0]["notes"]
        assert notes.index("PortFast") < notes.index("RootGuard")

    def test_rootguard_before_bpduguard_in_notes(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             spanning-tree guard root
             spanning-tree bpduguard enable
        """)
        notes = r["interfaces"][0]["notes"]
        assert notes.index("RootGuard") < notes.index("BPDUGuard")

    def test_stp_notes_before_shutdown(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             spanning-tree portfast
             shutdown
        """)
        notes = r["interfaces"][0]["notes"]
        assert notes.index("PortFast") < notes.index("shutdown")


# ─────────────────────────────────────────────────────────────────────────────
#  Port security
# ─────────────────────────────────────────────────────────────────────────────

class TestParseShowrunPortSecurity:

    def test_port_security_bare(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security
        """)
        assert r["interfaces"][0]["port_security"] is True

    def test_port_security_default_false(self):
        r = _p("""
            interface GigabitEthernet1/0/1
        """)
        assert r["interfaces"][0]["port_security"] is False

    def test_port_security_maximum_sets_both(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security maximum 3
        """)
        iface = r["interfaces"][0]
        assert iface["port_security"] is True
        assert iface["port_security_max"] == "3"

    def test_port_security_max_default_empty(self):
        r = _p("""
            interface GigabitEthernet1/0/1
        """)
        assert r["interfaces"][0]["port_security_max"] == ""

    def test_port_security_bare_notes_portsec(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security
        """)
        assert "PortSec" in r["interfaces"][0]["notes"]

    def test_port_security_max_notes(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security maximum 5
        """)
        notes = r["interfaces"][0]["notes"]
        assert "PortSec" in notes
        assert "max:5" in notes

    def test_port_security_max_always_includes_portsec(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security maximum 2
        """)
        notes = r["interfaces"][0]["notes"]
        assert "PortSec" in notes
        assert "max:2" in notes

    def test_port_security_notes_before_shutdown(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security
             shutdown
        """)
        notes = r["interfaces"][0]["notes"]
        assert notes.index("PortSec") < notes.index("shutdown")

    # ── violation mode ────────────────────────────────────────────────────────

    def test_port_security_violation_default_empty(self):
        r = _p("""
            interface GigabitEthernet1/0/1
        """)
        assert r["interfaces"][0]["port_security_violation"] == ""

    def test_port_security_violation_restrict(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security violation restrict
        """)
        iface = r["interfaces"][0]
        assert iface["port_security_violation"] == "restrict"
        assert iface["port_security"] is True

    def test_port_security_violation_protect(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security violation protect
        """)
        assert r["interfaces"][0]["port_security_violation"] == "protect"

    def test_port_security_violation_shutdown(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security violation shutdown
        """)
        assert r["interfaces"][0]["port_security_violation"] == "shutdown"

    def test_port_security_violation_in_notes(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security violation restrict
        """)
        notes = r["interfaces"][0]["notes"]
        assert "violation:restrict" in notes

    # ── static MACs ───────────────────────────────────────────────────────────

    def test_port_security_macs_default_empty(self):
        r = _p("""
            interface GigabitEthernet1/0/1
        """)
        assert r["interfaces"][0]["port_security_macs"] == []

    def test_port_security_single_static_mac(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security mac-address aabb.cc00.1122
        """)
        iface = r["interfaces"][0]
        assert iface["port_security"] is True
        assert iface["port_security_macs"] == ["aabb.cc00.1122"]

    def test_port_security_multiple_static_macs(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security mac-address aabb.cc00.1122
             switchport port-security mac-address aabb.cc00.3344
        """)
        assert r["interfaces"][0]["port_security_macs"] == [
            "aabb.cc00.1122", "aabb.cc00.3344"
        ]

    def test_port_security_static_mac_in_notes(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security mac-address aabb.cc00.1122
        """)
        notes = r["interfaces"][0]["notes"]
        assert "MAC:aabb.cc00.1122" in notes

    def test_port_security_each_mac_on_own_line(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security mac-address aabb.cc00.1122
             switchport port-security mac-address aabb.cc00.3344
        """)
        notes = r["interfaces"][0]["notes"]
        lines = notes.split("\n")
        assert any("MAC:aabb.cc00.1122" in l for l in lines)
        assert any("MAC:aabb.cc00.3344" in l for l in lines)

    # ── sticky ────────────────────────────────────────────────────────────────

    def test_port_security_sticky_default_false(self):
        r = _p("""
            interface GigabitEthernet1/0/1
        """)
        assert r["interfaces"][0]["port_security_sticky"] is False

    def test_port_security_sticky_set(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security mac-address sticky
        """)
        iface = r["interfaces"][0]
        assert iface["port_security_sticky"] is True
        assert iface["port_security"] is True

    def test_port_security_sticky_in_notes(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security mac-address sticky
        """)
        assert "sticky" in r["interfaces"][0]["notes"]

    def test_port_security_sticky_with_mac(self):
        """sticky + explicit MAC address on same line."""
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security mac-address sticky aabb.cc00.5566
        """)
        iface = r["interfaces"][0]
        assert iface["port_security_sticky"] is True
        assert "aabb.cc00.5566" in iface["port_security_macs"]

    def test_port_security_sticky_mac_not_in_mac_address_list_when_bare(self):
        """bare 'sticky' keyword alone → no MACs added to list."""
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security mac-address sticky
        """)
        assert r["interfaces"][0]["port_security_macs"] == []

    # ── combined ──────────────────────────────────────────────────────────────

    def test_port_security_full_combination(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security
             switchport port-security maximum 3
             switchport port-security violation restrict
             switchport port-security mac-address aabb.cc00.1122
             switchport port-security mac-address aabb.cc00.3344
        """)
        iface = r["interfaces"][0]
        assert iface["port_security"] is True
        assert iface["port_security_max"] == "3"
        assert iface["port_security_violation"] == "restrict"
        assert iface["port_security_macs"] == ["aabb.cc00.1122", "aabb.cc00.3344"]
        notes = iface["notes"]
        assert "PortSec" in notes
        assert "max:3" in notes
        assert "violation:restrict" in notes
        assert "MAC:aabb.cc00.1122" in notes
        assert "MAC:aabb.cc00.3344" in notes


# ── notes separator ──────────────────────────────────────────────────────────

class TestParseShowrunNotesSeparator:

    def test_notes_use_newline_separator(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport voice vlan 10
             spanning-tree portfast
        """)
        notes = r["interfaces"][0]["notes"]
        assert "\n" in notes
        assert "Voice:10" in notes
        assert "PortFast" in notes

    def test_single_note_no_newline(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             spanning-tree portfast
        """)
        assert "\n" not in r["interfaces"][0]["notes"]

    def test_mac_entries_each_on_own_line(self):
        r = _p("""
            interface GigabitEthernet1/0/1
             switchport port-security mac-address 1111.2222.3333
             switchport port-security mac-address 4444.5555.6666
             shutdown
        """)
        lines = r["interfaces"][0]["notes"].split("\n")
        assert lines[-1] == "shutdown"
        assert any("MAC:1111.2222.3333" in l for l in lines)
        assert any("MAC:4444.5555.6666" in l for l in lines)


# ─────────────────────────────────────────────────────────────────────────────
#  VLAN definitions
# ─────────────────────────────────────────────────────────────────────────────

class TestParseShowrunVlanDefinitions:

    def test_vlans_key_present(self):
        r = _p("hostname SW\n")
        assert "vlans" in r

    def test_empty_when_no_vlan_blocks(self):
        r = _p("""
            hostname SW
            interface GigabitEthernet1/0/1
        """)
        assert r["vlans"] == []

    def test_single_vlan_with_name(self):
        r = _p("""
            vlan 10
             name SERVERS
        """)
        assert len(r["vlans"]) == 1
        assert r["vlans"][0]["id"] == "10"
        assert r["vlans"][0]["name"] == "SERVERS"

    def test_multiple_vlans(self):
        r = _p("""
            vlan 10
             name SERVERS
            vlan 20
             name CLIENTS
        """)
        ids = [v["id"] for v in r["vlans"]]
        assert "10" in ids
        assert "20" in ids

    def test_vlan_without_name_included(self):
        r = _p("""
            vlan 10
            vlan 20
             name MGMT
        """)
        ids = [v["id"] for v in r["vlans"]]
        assert "10" in ids
        assert "20" in ids
        names = {v["id"]: v["name"] for v in r["vlans"]}
        assert names["10"] == ""
        assert names["20"] == "MGMT"

    def test_vlan_range_skipped(self):
        r = _p("""
            vlan 10,20,30
             name RANGE
        """)
        assert r["vlans"] == []

    def test_vlan_hyphen_range_skipped(self):
        r = _p("""
            vlan 10-20
             name RANGE
        """)
        assert r["vlans"] == []

    def test_vlan_database_skipped(self):
        # "vlan database" does not match "^vlan \d+$"
        r = _p("""
            vlan database
             vlan 10 name OLD
        """)
        assert r["vlans"] == []

    def test_vlan_name_whitespace_stripped(self):
        r = _p("""
            vlan 99
             name   MGMT-VLAN
        """)
        assert r["vlans"][0]["name"] == "MGMT-VLAN"

    def test_vlans_sorted_by_numeric_id(self):
        r = _p("""
            vlan 30
             name C
            vlan 10
             name A
            vlan 20
             name B
        """)
        ids = [v["id"] for v in r["vlans"]]
        assert ids == ["10", "20", "30"]

    # ── used / dead field ─────────────────────────────────────────────────────

    def test_vlan_used_field_present(self):
        r = _p("""
            vlan 10
             name TEST
        """)
        assert "used" in r["vlans"][0]

    def test_vlan_not_used_when_no_interfaces(self):
        r = _p("""
            vlan 10
             name TEST
        """)
        assert r["vlans"][0]["used"] is False

    def test_vlan_used_via_access_port(self):
        r = _p("""
            vlan 10
             name SERVERS
            interface GigabitEthernet1/0/1
             switchport mode access
             switchport access vlan 10
        """)
        v = next(v for v in r["vlans"] if v["id"] == "10")
        assert v["used"] is True

    def test_vlan_dead_when_not_referenced(self):
        r = _p("""
            vlan 10
             name USED
            vlan 20
             name DEAD
            interface GigabitEthernet1/0/1
             switchport mode access
             switchport access vlan 10
        """)
        v20 = next(v for v in r["vlans"] if v["id"] == "20")
        assert v20["used"] is False

    def test_vlan_used_via_native_vlan(self):
        r = _p("""
            vlan 99
             name NATIVE
            interface GigabitEthernet1/0/1
             switchport mode trunk
             switchport trunk native vlan 99
        """)
        v = next(v for v in r["vlans"] if v["id"] == "99")
        assert v["used"] is True

    def test_vlan_used_via_voice_vlan(self):
        r = _p("""
            vlan 50
             name VOICE
            interface GigabitEthernet1/0/1
             switchport voice vlan 50
        """)
        v = next(v for v in r["vlans"] if v["id"] == "50")
        assert v["used"] is True

    def test_vlan_used_via_trunk_range(self):
        r = _p("""
            vlan 15
             name IN-RANGE
            interface GigabitEthernet1/0/1
             switchport mode trunk
             switchport trunk allowed vlan 10-20
        """)
        v = next(v for v in r["vlans"] if v["id"] == "15")
        assert v["used"] is True

    def test_vlan_dead_outside_trunk_range(self):
        r = _p("""
            vlan 25
             name OUTSIDE
            interface GigabitEthernet1/0/1
             switchport mode trunk
             switchport trunk allowed vlan 10-20
        """)
        v = next(v for v in r["vlans"] if v["id"] == "25")
        assert v["used"] is False

    def test_vlan_used_trunk_all(self):
        r = _p("""
            vlan 777
             name ANY
            interface GigabitEthernet1/0/1
             switchport mode trunk
             switchport trunk allowed vlan all
        """)
        v = next(v for v in r["vlans"] if v["id"] == "777")
        assert v["used"] is True

    def test_vlan_without_name_included_with_used_field(self):
        r = _p("""
            vlan 10
            interface GigabitEthernet1/0/1
             switchport mode access
             switchport access vlan 10
        """)
        assert len(r["vlans"]) == 1
        assert r["vlans"][0]["name"] == ""
        assert r["vlans"][0]["used"] is True


# ─────────────────────────────────────────────────────────────────────────────
#  Integration: full notes ordering
# ─────────────────────────────────────────────────────────────────────────────

class TestParseShowrunIntegrationNotes:

    def test_full_notes_ordering(self):
        """All note tokens appear in the correct order."""
        r = _p("""
            interface GigabitEthernet1/0/1
             channel-group 2 mode active
             switchport voice vlan 10
             spanning-tree portfast
             spanning-tree guard root
             spanning-tree bpduguard enable
             switchport port-security maximum 3
             shutdown
        """)
        notes = r["interfaces"][0]["notes"]
        order = ["Po2 member", "Voice:10", "PortFast", "RootGuard", "BPDUGuard", "PortSec", "shutdown"]
        positions = [notes.index(tok) for tok in order]
        assert positions == sorted(positions), f"Wrong order in: {notes}"


# ─────────────────────────────────────────────────────────────────────────────
#  parse_version_inventory
# ─────────────────────────────────────────────────────────────────────────────

class TestParseVersionInventory:

    def test_inventory_pid_sn(self):
        text = textwrap.dedent("""\
            NAME: "1", DESCR: "Cisco Catalyst 9300-48U Switch"
            PID: C9300-48U        , VID: V01  , SN: FDO1234ABCD
        """)
        r = parse_version_inventory(text)
        assert r["model"] == "C9300-48U"
        assert r["serial"] == "FDO1234ABCD"

    def test_inventory_with_command_prefix(self):
        text = textwrap.dedent("""\
            Switch#show inventory
            NAME: "1", DESCR: "WS-C3750G-48PS-S"
            PID: WS-C3750G-48PS-S , VID: V06  , SN: CAT1234ABCD
        """)
        r = parse_version_inventory(text)
        assert r["model"] == "WS-C3750G-48PS-S"
        assert r["serial"] == "CAT1234ABCD"

    def test_version_model_and_system_serial(self):
        text = textwrap.dedent("""\
            Cisco IOS Software, Version 15.2(7)E6
            Model number                  : WS-C3850-48T
            System serial number          : FOC1234ABCD
        """)
        r = parse_version_inventory(text)
        assert r["model"] == "WS-C3850-48T"
        assert r["serial"] == "FOC1234ABCD"

    def test_version_processor_board_id(self):
        text = textwrap.dedent("""\
            cisco WS-C3750G-48PS (PowerPC405) processor
            Processor board ID CAT0987ZZZZ
        """)
        r = parse_version_inventory(text)
        assert r["model"] == ""
        assert r["serial"] == "CAT0987ZZZZ"

    def test_inventory_priority_over_version(self):
        text = textwrap.dedent("""\
            Model number                  : WS-C3850-48T
            System serial number          : FOC0000VERSION
            PID: C9300-48U        , VID: V01  , SN: FDO9999INVENTORY
        """)
        r = parse_version_inventory(text)
        assert r["model"] == "C9300-48U"
        assert r["serial"] == "FDO9999INVENTORY"

    def test_empty_text(self):
        r = parse_version_inventory("")
        assert r == {"model": "", "serial": ""}

    def test_no_relevant_data(self):
        text = "hostname SW-CORE\nip domain-name example.com\n"
        r = parse_version_inventory(text)
        assert r == {"model": "", "serial": ""}

    def test_mixed_with_running_config(self):
        text = textwrap.dedent("""\
            hostname SW-CORE
            ip ssh source-interface Vlan1
            interface GigabitEthernet1/0/1
             description uplink
             no shutdown
            !
            Switch#show inventory
            NAME: "1", DESCR: "Cisco Catalyst 9300-48U Switch"
            PID: C9300-48U        , VID: V01  , SN: FDO5555MIXED
        """)
        r = parse_version_inventory(text)
        assert r["model"] == "C9300-48U"
        assert r["serial"] == "FDO5555MIXED"

    def test_inventory_first_pid_wins_for_stacked(self):
        text = textwrap.dedent("""\
            NAME: "Switch 1", DESCR: "WS-C3750G-48PS-S"
            PID: WS-C3750G-48PS-S , VID: V06  , SN: CAT1111FIRST
            NAME: "Switch 2", DESCR: "WS-C3750G-48PS-S"
            PID: WS-C3750G-48PS-S , VID: V06  , SN: CAT2222SECOND
        """)
        r = parse_version_inventory(text)
        assert r["serial"] == "CAT1111FIRST"
