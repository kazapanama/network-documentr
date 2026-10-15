"""
Аудит конфігурацій: що на пристрої НЕДОЛАШТОВАНО.

run_audit(text, parsed) → AuditReport зі списком Finding: рівень, що не так,
чим це загрожує, де саме (порти / рядки) і готові команди для виправлення.

Перевірки консервативні: якщо файл — фрагмент (немає секцій, з яких можна
судити про глобальні налаштування), відповідні перевірки пропускаються,
а не вважаються проваленими; що саме пропущено — у report.skipped.
"""

import re
from dataclasses import dataclass, field

SEV_ORDER = {"high": 0, "medium": 1, "low": 2}
SEV_LABEL = {"high": "КРИТИЧНО", "medium": "ВАЖЛИВО", "low": "ПОРАДА"}


@dataclass
class Finding:
    sev: str            # high | medium | low
    code: str           # стабільний ідентифікатор перевірки
    title: str          # що недолаштовано
    why: str            # чим це загрожує
    where: list = field(default_factory=list)
    fix: str = ""       # команди для виправлення


@dataclass
class AuditReport:
    vendor: str
    findings: list = field(default_factory=list)
    skipped: list = field(default_factory=list)

    def counts(self) -> dict:
        c = {"high": 0, "medium": 0, "low": 0}
        for f in self.findings:
            c[f.sev] += 1
        return c

    def codes(self) -> set:
        return {f.code for f in self.findings}

    def get(self, code: str):
        return next((f for f in self.findings if f.code == code), None)


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def summary_text(report: AuditReport) -> str:
    c = report.counts()
    parts = []
    if c["high"]:
        parts.append(f"{c['high']} {plural(c['high'], 'критичне', 'критичні', 'критичних')}")
    if c["medium"]:
        parts.append(f"{c['medium']} {plural(c['medium'], 'важливе', 'важливі', 'важливих')}")
    if c["low"]:
        parts.append(f"{c['low']} {plural(c['low'], 'порада', 'поради', 'порад')}")
    return " · ".join(parts) if parts else "зауважень немає"


def short_summary(report: AuditReport) -> str:
    """Короткий рядок для статусу у головному вікні."""
    c = report.counts()
    if not report.findings:
        return "Аудит: OK"
    bits = []
    if c["high"]:
        bits.append(f"{c['high']} крит.")
    if c["medium"]:
        bits.append(f"{c['medium']} важл.")
    if c["low"]:
        bits.append(f"{c['low']} пор.")
    return "Аудит: " + " · ".join(bits)


# ═════════════════════════════════════════════════════════════════════════════
#  Порти: стиснення списків і команди interface range
# ═════════════════════════════════════════════════════════════════════════════

_SHORT = [
    ("GigabitEthernet", "Gi"), ("FastEthernet", "Fa"), ("TenGigabitEthernet", "Te"),
    ("TwentyFiveGigE", "Twe"), ("FortyGigabitEthernet", "Fo"), ("HundredGigE", "Hu"),
    ("Port-channel", "Po"), ("port-channel", "Po"), ("Loopback", "Lo"),
]


def _short(name: str) -> str:
    for long, short in _SHORT:
        if name.startswith(long):
            return short + name[len(long):]
    return name


def _port_groups(names: list) -> list:
    """['Gi1/0/1','Gi1/0/2','Gi1/0/3','Gi1/0/9'] → [('Gi1/0/', 1, 3), ('Gi1/0/', 9, 9)]
    Порядок появи зберігається; без числового хвоста — (name, None, None)."""
    groups = []
    for n in names:
        m = re.match(r"^(.*?)(\d+)$", n)
        if not m:
            groups.append((n, None, None))
            continue
        pre, num = m.group(1), int(m.group(2))
        if groups and groups[-1][0] == pre and groups[-1][2] is not None and groups[-1][2] + 1 == num:
            groups[-1] = (pre, groups[-1][1], num)
        else:
            groups.append((pre, num, num))
    return groups


def compress_ports(names: list) -> str:
    out = []
    for pre, lo, hi in _port_groups([_short(n) for n in names]):
        if lo is None:
            out.append(pre)
        elif lo == hi:
            out.append(f"{pre}{lo}")
        else:
            out.append(f"{pre}{lo}-{hi}")
    return ", ".join(out)


def range_cmds(names: list, body: list) -> str:
    """Cisco: 'interface range Gi1/0/1 - 6 , Gi1/0/9' (до 5 діапазонів у команді) + тіло."""
    parts = []
    for pre, lo, hi in _port_groups([_short(n) for n in names]):
        if lo is None:
            parts.append(pre)
        elif lo == hi:
            parts.append(f"{pre}{lo}")
        else:
            parts.append(f"{pre}{lo} - {hi}")
    blocks = []
    for i in range(0, len(parts), 5):
        head = parts[i:i + 5]
        cmd = ("interface range " if len(head) > 1 or " - " in head[0] else "interface ") + " , ".join(head)
        blocks.append("\n".join([cmd] + [" " + b for b in body]))
    return "\n".join(blocks)


# ═════════════════════════════════════════════════════════════════════════════
#  CISCO IOS / IOS-XE
# ═════════════════════════════════════════════════════════════════════════════

_PHYS = ("GigabitEthernet", "FastEthernet", "TenGigabitEthernet", "TwentyFiveGigE",
         "FortyGigabitEthernet", "HundredGigE", "Ethernet")
# рядки, що не роблять порт «налаштованим»
_TRIVIAL = re.compile(r"^(no ip address|negotiation auto|media-type .*|speed .*|duplex .*|"
                      r"load-interval .*|no shutdown|mtu .*|no cdp enable|cdp enable)$")


def cisco_blocks(text: str) -> list:
    """Верхньорівневі команди show running-config як (header, [дочірні рядки]).
    Читання зупиняється на першому 'end' (далі може бути show inventory тощо);
    багаторядкові банери пропускаються."""
    blocks = []
    cur = None
    delim = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if delim is not None:
            if delim in line:
                delim = None
            continue
        if line == "end":
            break
        s = line.strip()
        if not s or s == "!":
            cur = None
            continue
        if line[0] in " \t":
            if cur is not None:
                cur[1].append(s)
            continue
        cur = (s, [])
        blocks.append(cur)
        m = re.match(r"^banner\s+\S+\s+(\^C|\S)(.*)$", s)
        if m and m.group(1) not in m.group(2):
            delim = m.group(1)
    return blocks


def _expand_vlans(spec: str) -> tuple:
    """'10,20-22,all' → ({'10','20','21','22'}, has_all)"""
    ids, has_all = set(), False
    for part in re.split(r"[,\s]+", spec or ""):
        part = part.strip().lower()
        if not part or part in ("none", "add", "remove", "except"):
            continue
        if part == "all":
            has_all = True
            continue
        m = re.match(r"^(\d+)-(\d+)$", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if hi - lo <= 1000:
                ids.update(str(i) for i in range(lo, hi + 1))
            else:
                has_all = True
        elif part.isdigit():
            ids.add(part)
    return ids, has_all


def audit_cisco(text: str, parsed: dict) -> AuditReport:
    rep = AuditReport(vendor="Cisco IOS")
    F = rep.findings
    add = lambda *a, **k: F.append(Finding(*a, **k))

    blocks = cisco_blocks(text)
    glob = [h for h, _ in blocks]

    def has(rx):
        return any(re.match(rx, g) for g in glob)

    full = bool(re.search(r"^(Current configuration|Building configuration)", text, re.M)) or has(r"line vty")
    if not full:
        rep.skipped.append("Схоже на фрагмент конфігурації (немає заголовка show running-config і line vty) — "
                           "глобальні перевірки (паролі, VTY, NTP, syslog, SNMP…) пропущено, перевірено лише інтерфейси.")

    ifaces = [(h.split(None, 1)[1], ch) for h, ch in blocks if h.startswith("interface ") and len(h.split()) > 1]
    vtys = [(h, ch) for h, ch in blocks if h.startswith("line vty")]
    cons = [(h, ch) for h, ch in blocks if h.startswith("line con")]
    users = [g for g in glob if g.startswith("username ")]
    is_switch = any(c.startswith("switchport") for _n, ch in ifaces for c in ch)
    hostname = parsed.get("hostname", "") if parsed else ""

    # ── Глобальні налаштування ───────────────────────────────────────────────
    if full:
        if has(r"enable password"):
            add("high", "enable-password", "Пароль привілейованого режиму задано як enable password",
                "enable password зберігається відкритим текстом або оборотним шифром type 7 — його легко відновити з конфігу.",
                ["enable password"], "no enable password\nenable algorithm-type scrypt secret <ПАРОЛЬ>")
        elif not has(r"enable secret") and not any(" privilege 15" in u for u in users):
            add("low", "no-enable-secret", "Не задано enable secret",
                "Без нього віддалено не перейти в привілейований режим, а локально з консолі — без пароля.",
                [], "enable algorithm-type scrypt secret <ПАРОЛЬ>")

        weak_users = [u.split()[1] for u in users if re.search(r"\spassword\s", u)]
        if weak_users:
            add("medium", "user-password", "Локальні користувачі з password замість secret",
                "Паролі type 0/7 відновлюються з конфігу за секунди.",
                weak_users, "\n".join(f"username {u} algorithm-type scrypt secret <ПАРОЛЬ>" for u in weak_users))

        plain_pw = any(re.search(r"(^|\s)password (0 )?[^7\s]", x) for h, ch in blocks for x in [h] + ch
                       if not x.startswith("username"))
        if not has(r"service password-encryption") and (plain_pw or weak_users):
            add("medium", "password-encryption", "Не ввімкнено service password-encryption",
                "Паролі line/username password лежать у конфігу відкритим текстом — видно будь-кому з доступом до бекапу.",
                [], "service password-encryption")

        # VTY: лінії без login/password і без AAA не пускають нікого — їх не перевіряємо
        aaa = has(r"aaa new-model")
        vtys = [(h, ch) for h, ch in vtys if aaa or any(c.startswith(("login", "password")) for c in ch)]
        if not vtys:
            rep.skipped.append("Робочих line vty немає (або вони без login/AAA) — перевірки віддаленого доступу "
                               "(telnet, ACL, таймаути) пропущено.")
        tr_default, telnet, no_acl, no_timeout, login_local_nousers, shared_pw = [], [], [], [], [], []
        ssh_allowed = False
        for h, ch in vtys:
            tr = next((c for c in ch if c.startswith("transport input")), "")
            if not tr:
                tr_default.append(h)
                ssh_allowed = True
            else:
                if re.search(r"\b(telnet|all)\b", tr):
                    telnet.append(h)
                if re.search(r"\b(ssh|all)\b", tr):
                    ssh_allowed = True
            if not any(c.startswith("access-class") for c in ch):
                no_acl.append(h)
            if any(re.match(r"^exec-timeout 0( 0)?$", c) for c in ch):
                no_timeout.append(h)
            if "login local" in ch and not users:
                login_local_nousers.append(h)
            if "login" in ch and any(c.startswith("password") for c in ch) and not aaa:
                shared_pw.append(h)
        if telnet:
            add("high", "vty-telnet", "Telnet дозволено на VTY",
                "Логін, пароль і вся сесія керування йдуть мережею відкритим текстом.",
                telnet, "line vty 0 15\n transport input ssh")
        if tr_default:
            add("medium", "vty-transport-default", "На VTY не задано transport input",
                "Без явного значення на багатьох версіях IOS дозволено telnet разом із SSH.",
                tr_default, "line vty 0 15\n transport input ssh")
        if login_local_nousers:
            add("high", "vty-login-local-no-users", "VTY вимагає login local, але локальних користувачів немає",
                "Віддалено на пристрій не зайти, якщо немає AAA-сервера.",
                login_local_nousers, "username <ЛОГІН> privilege 15 algorithm-type scrypt secret <ПАРОЛЬ>")
        if no_acl:
            add("medium", "vty-no-acl", "Доступ до VTY не обмежено access-class",
                "Підключитися по SSH/telnet може будь-хто, хто має IP-зв'язність із пристроєм.",
                no_acl, "ip access-list standard MGMT-ONLY\n permit <МЕРЕЖА_АДМІНІВ> <WILDCARD>\n"
                        "line vty 0 15\n access-class MGMT-ONLY in")
        if no_timeout:
            add("medium", "vty-no-timeout", "exec-timeout 0 0 на VTY",
                "Забуті сесії адміністраторів висять вічно і займають VTY-лінії.",
                no_timeout, "line vty 0 15\n exec-timeout 10 0")
        if shared_pw:
            add("low", "vty-shared-password", "VTY з одним спільним паролем (login + password)",
                "Немає персональних облікових записів — не видно, хто що змінював.",
                shared_pw, "line vty 0 15\n login local\n no password")
        if ssh_allowed and not has(r"ip ssh version 2"):
            add("medium", "ssh-v1", "Не зафіксовано ip ssh version 2",
                "За замовчуванням пристрій може прийняти застарілий SSHv1.",
                [], "ip ssh version 2")
        for h, ch in cons:
            if any(re.match(r"^exec-timeout 0( 0)?$", c) for c in ch):
                add("low", "con-no-timeout", "exec-timeout 0 0 на консолі",
                    "Сесія на консольному порту не завершується сама — хто підійде до шафи, отримає відкриту сесію.",
                    [h], f"{h}\n exec-timeout 10 0")

        if has(r"ip http server$"):
            add("medium", "http-server", "Ввімкнено вебсервер ip http server",
                "Зайвий сервіс керування без шифрування; історично — джерело критичних вразливостей IOS-XE.",
                ["ip http server"], "no ip http server" + ("" if has(r"ip http secure-server") else "\nno ip http secure-server"))

        # SNMP
        default_comm, rw_comm, noacl_comm = [], [], []
        for g in glob:
            m = re.match(r"^snmp-server community (\S+)(?:\s+view\s+\S+)?(?:\s+(RO|RW|ro|rw))?(?:\s+(\S+))?", g)
            if not m:
                continue
            name, mode, acl = m.group(1), (m.group(2) or "RO").upper(), m.group(3)
            if name.lower() in ("public", "private", "cisco", "community"):
                default_comm.append(name)
            if mode == "RW":
                rw_comm.append(name)
            if not acl or acl.lower() == "ipv6":
                noacl_comm.append(name)
        if default_comm:
            add("high", "snmp-default-community", "SNMP-community зі стандартною назвою",
                "public/private перебирають сканери першими — з неї читається вся конфігурація інтерфейсів і ARP.",
                default_comm, "\n".join(f"no snmp-server community {c}" for c in default_comm) +
                "\nsnmp-server community <ДОВГА_ВИПАДКОВА> RO MGMT-ONLY")
        if rw_comm:
            add("high", "snmp-rw", "SNMP-community з правом запису (RW)",
                "Через SNMP RW можна змінити конфігурацію або вивантажити її на TFTP.",
                rw_comm, "\n".join(f"snmp-server community {c} RO MGMT-ONLY" for c in rw_comm))
        if noacl_comm:
            add("medium", "snmp-no-acl", "SNMP-community без ACL",
                "Опитувати пристрій може будь-яка адреса, що знає community.",
                noacl_comm, "\n".join(f"snmp-server community {c} RO MGMT-ONLY" for c in noacl_comm))

        if not has(r"ntp server"):
            add("medium", "no-ntp", "Не налаштовано NTP",
                "Годинник пливе — час у логах не збігається з іншими пристроями, сертифікати й розслідування ламаються.",
                [], "ntp server <IP_NTP>")
        if not has(r"logging (host )?\d"):
            add("medium", "no-syslog", "Логи не відправляються на syslog-сервер",
                "Після перезавантаження чи переповнення буфера історія подій зникає.",
                [], "logging host <IP_SYSLOG>\nlogging trap informational")
        if not has(r"service timestamps log datetime"):
            add("low", "no-timestamps", "У логах немає дати й часу",
                "Без service timestamps log datetime записи мають лише uptime — не зіставити з подіями.",
                [], "service timestamps log datetime msec localtime show-timezone")
        if not has(r"clock timezone"):
            add("low", "no-timezone", "Не задано часовий пояс",
                "Час у логах і show clock — у UTC, що плутає при розборі інцидентів.",
                [], "clock timezone EET 2 0\nclock summer-time EEST recurring last Sun Mar 3:00 last Sun Oct 4:00")
        if not has(r"banner (motd|login|exec)"):
            add("low", "no-banner", "Немає банера попередження",
                "Юридичне попередження про несанкціонований доступ відсутнє.",
                [], "banner login ^C\nНесанкціонований доступ заборонено.\n^C")
        if not hostname or hostname in ("Switch", "Router", "switch", "router"):
            add("low", "default-hostname", "Стандартне ім'я пристрою",
                "У логах, моніторингу й документації пристрій не відрізнити від інших.",
                [hostname or "(не задано)"], "hostname <ІМ'Я>")
        if not has(r"no ip domain[- ]lookup"):
            add("low", "domain-lookup", "Ввімкнено ip domain lookup",
                "Помилка в команді CLI трактується як ім'я хоста — консоль зависає на DNS-запиті.",
                [], "no ip domain lookup")

        svi_ip = any(n.startswith("Vlan") and any(c.startswith("ip address") for c in ch) for n, ch in ifaces)
        if is_switch and svi_ip and not has(r"ip routing") and not has(r"ip default-gateway") and not has(r"ip route "):
            add("medium", "no-default-gateway", "L2-комутатор без ip default-gateway",
                "Керувати комутатором можна лише з його власної підмережі.",
                [], "ip default-gateway <IP_ШЛЮЗУ>")
        if is_switch:
            m = next((g for g in glob if g.startswith("spanning-tree mode")), "")
            if not m or m.split()[-1] == "pvst":
                add("low", "stp-pvst", "Spanning-tree у класичному режимі PVST",
                    "Збіжність після обриву займає 30–50 секунд; Rapid-PVST — 1–2 секунди.",
                    [m or "(spanning-tree mode не задано)"], "spanning-tree mode rapid-pvst")

    # ── Інтерфейси ───────────────────────────────────────────────────────────
    pf_default = has(r"spanning-tree portfast (edge )?default")
    bg_default = has(r"spanning-tree portfast (edge )?bpduguard default")
    empty, l3_idle, dtp, acc_vlan1, acc_nopf, acc_nobg, no_desc = [], [], [], [], [], [], []
    tr_all, tr_native1, tr_dtp, portsec_off = [], [], [], []
    access_ports = 0
    bpduguard_used = bg_default
    refs = {}  # vlan → [порти], окрім native

    for name, ch in ifaces:
        phys = name.startswith(_PHYS)
        po = name.lower().startswith("port-channel")
        shut = "shutdown" in ch
        if "spanning-tree bpduguard enable" in ch:
            bpduguard_used = True
        if not (phys or po):
            continue
        member = any(c.startswith("channel-group") for c in ch)
        # L3-порт: явне no switchport або будь-який рядок ip address (комутаторні порти його не мають)
        routed = "no switchport" in ch or any(c == "no ip address" or c.startswith("ip address") for c in ch)
        mode = next((c.split()[-1] for c in ch if c.startswith("switchport mode ")), "")
        if any(c.startswith("switchport mode dynamic") for c in ch):
            mode = "dynamic"
        acc = next((c.split()[-1] for c in ch if c.startswith("switchport access vlan")), "")
        voice = next((c.split()[-1] for c in ch if c.startswith("switchport voice vlan")), "")
        native = next((c.split()[-1] for c in ch if c.startswith("switchport trunk native vlan")), "")
        allowed = ",".join(re.sub(r"^switchport trunk allowed vlan\s*(add\s*)?", "", c)
                           for c in ch if c.startswith("switchport trunk allowed vlan"))

        if shut:
            continue
        if phys and not [c for c in ch if not _TRIVIAL.match(c)]:
            (l3_idle if routed else empty).append(name)
            continue
        if not any(c.startswith("description") for c in ch):
            no_desc.append(name)

        opts = [c for c in ch if c.startswith("switchport port-security ")]
        if opts and "switchport port-security" not in ch:
            portsec_off.append(name)

        if member or routed:
            continue
        if mode in ("", "dynamic") and phys:
            dtp.append(name)
            continue
        if mode == "access":
            access_ports += 1
            if not acc:
                acc_vlan1.append(name)
            pf = any(re.match(r"^spanning-tree portfast( edge)?$", c) for c in ch)
            if not pf and not pf_default:
                acc_nopf.append(name)
            if "spanning-tree bpduguard enable" not in ch and not (bg_default and (pf or pf_default)):
                acc_nobg.append(name)
            for v in (acc, voice):
                if v:
                    refs.setdefault(v, []).append(name)
        elif mode == "trunk":
            if not allowed:
                tr_all.append(name)
            if not native or native == "1":
                tr_native1.append(name)
            if "switchport nonegotiate" not in ch:
                tr_dtp.append(name)
            ids, _all = _expand_vlans(allowed)
            for v in ids:
                refs.setdefault(v, []).append(name)

    if empty:
        add("medium", "port-empty", "Порти без жодних налаштувань і не вимкнені",
            "Такий порт — у VLAN 1 і в режимі DTP: хтось підключиться й опиниться в мережі керування "
            "або підніме транк. Невикористані порти варто вимкнути й перевести в «мертвий» VLAN.",
            [compress_ports(empty)],
            range_cmds(empty, ["switchport mode access", "switchport access vlan <UNUSED_VLAN>", "shutdown"]))
    if l3_idle:
        add("low", "l3-port-idle", "L3-порти без адреси не вимкнені",
            "Невикористаний порт адміністративно ввімкнений — його легко задіяти помилково; вимкнений порт видно одразу.",
            [compress_ports(l3_idle)], range_cmds(l3_idle, ["shutdown"]))
    if dtp:
        add("medium", "port-dtp", "Режим порту не задано (DTP)",
            "Без switchport mode порт домовляється сам і може стати транком із чужим пристроєм (VLAN hopping).",
            [compress_ports(dtp)], range_cmds(dtp, ["switchport mode access"]))
    if acc_vlan1:
        add("medium", "access-vlan1", "Access-порти у VLAN 1",
            "VLAN 1 — VLAN за замовчуванням і службових протоколів; користувачі в ньому змішуються з керуванням.",
            [compress_ports(acc_vlan1)], range_cmds(acc_vlan1, ["switchport access vlan <VLAN>"]))
    if acc_nobg:
        add("medium", "access-no-bpduguard", "Access-порти без BPDU Guard",
            "Принесений комутатор чи петля кабелем можуть перебудувати spanning-tree і покласти сегмент.",
            [compress_ports(acc_nobg)],
            "spanning-tree portfast bpduguard default\n! або на портах:\n" +
            range_cmds(acc_nobg, ["spanning-tree bpduguard enable"]))
    if acc_nopf:
        add("low", "access-no-portfast", "Access-порти без PortFast",
            "ПК і телефони чекають ~30 секунд, поки порт пройде стани STP — DHCP може не встигнути.",
            [compress_ports(acc_nopf)], range_cmds(acc_nopf, ["spanning-tree portfast"]))
    if tr_all:
        add("medium", "trunk-all-vlans", "Транки пропускають усі VLAN",
            "Без switchport trunk allowed vlan на сусіда летять усі VLAN, включно з тими, яких там бути не повинно.",
            [compress_ports(tr_all)], range_cmds(tr_all, ["switchport trunk allowed vlan <СПИСОК>"]))
    if tr_native1:
        add("low", "trunk-native1", "Native VLAN транку — VLAN 1",
            "Нетегований трафік змішується з VLAN 1; класичний вектор VLAN hopping через подвійне тегування.",
            [compress_ports(tr_native1)], range_cmds(tr_native1, ["switchport trunk native vlan <НЕВИКОРИСТАНИЙ_VLAN>"]))
    if tr_dtp:
        add("low", "trunk-dtp", "На транках не вимкнено DTP",
            "Порт продовжує розсилати DTP-кадри; switchport nonegotiate прибирає зайве узгодження.",
            [compress_ports(tr_dtp)], range_cmds(tr_dtp, ["switchport nonegotiate"]))
    if portsec_off:
        add("medium", "portsec-not-enabled", "Port-security налаштовано, але не ввімкнено",
            "Параметри maximum/violation/mac-address без рядка switchport port-security не діють.",
            [compress_ports(portsec_off)], range_cmds(portsec_off, ["switchport port-security"]))
    if no_desc:
        add("low", "no-description", "Активні порти без опису",
            "Без description незрозуміло, що підключено, — і в документації ці рядки будуть порожні.",
            [compress_ports(no_desc)], range_cmds(no_desc[:1], ["description <ЩО ПІДКЛЮЧЕНО>"]))

    # ── VLAN ──────────────────────────────────────────────────────────────────
    vlans = (parsed or {}).get("vlans", [])
    if vlans:
        defined = {v["id"] for v in vlans}
        for name, ch in ifaces:
            if name.startswith("Vlan") and "shutdown" not in ch and any(c.startswith("ip address") for c in ch):
                refs.setdefault(name[4:], []).append(name)
        missing = sorted((v for v in refs if v != "1" and v not in defined), key=int)
        if missing:
            add("medium", "vlan-undefined", "Порти посилаються на VLAN, яких немає в базі",
                "Порт у неіснуючому VLAN не передає трафік (на access-порту — порт неактивний).",
                [f"VLAN {v}: {compress_ports(refs[v])}" for v in missing],
                "\n".join(f"vlan {v}\n name <НАЗВА>" for v in missing))
        unused = [v for v in vlans if not v.get("used") and v["id"] != "1"]
        if unused:
            add("low", "vlan-unused", "VLAN оголошені, але не призначені жодному порту",
                "Мертві VLAN засмічують конфіг і документацію — або прибрати, або дописати порти.",
                [", ".join(v["id"] + (f" ({v['name']})" if v.get("name") else "") for v in unused)],
                "\n".join(f"no vlan {v['id']}" for v in unused))
    for name, ch in ifaces:
        if name == "Vlan1" and "shutdown" not in ch and any(c.startswith("ip address") for c in ch):
            add("low", "svi-vlan1", "Адреса керування у VLAN 1",
                "Керування в VLAN за замовчуванням ділить домен із будь-яким нетегованим трафіком.",
                ["interface Vlan1"], "interface Vlan<MGMT>\n ip address <IP> <MASK>\ninterface Vlan1\n no ip address\n shutdown")

    if full and is_switch and access_ports and not has(r"ip dhcp snooping$"):
        add("low", "no-dhcp-snooping", "Не ввімкнено DHCP snooping",
            "Будь-який пристрій на access-порту може роздавати адреси (rogue DHCP) і перехоплювати трафік.",
            [], "ip dhcp snooping\nip dhcp snooping vlan <VLANИ>\n! на аплінках: ip dhcp snooping trust")
    if full and bpduguard_used and not has(r"errdisable recovery cause (bpduguard|all)"):
        add("low", "no-errdisable-recovery", "BPDU Guard без автовідновлення порту",
            "Порт, що спіймав BPDU, лишається в err-disabled, поки його не підніме адміністратор.",
            [], "errdisable recovery cause bpduguard\nerrdisable recovery interval 300")
    return rep


# ═════════════════════════════════════════════════════════════════════════════
#  FORTINET (FortiGate / FortiSwitch)
# ═════════════════════════════════════════════════════════════════════════════

def _ftokens(line: str) -> list:
    out, i, n = [], 0, len(line)
    while i < n:
        while i < n and line[i] in " \t\r":
            i += 1
        if i >= n:
            break
        tok = ""
        if line[i] == '"':
            i += 1
            while i < n:
                c = line[i]
                if c == "\\" and i + 1 < n:
                    tok += line[i + 1]
                    i += 2
                    continue
                if c == '"':
                    i += 1
                    break
                tok += c
                i += 1
        else:
            while i < n and line[i] not in " \t\r":
                tok += line[i]
                i += 1
        out.append(tok)
    return out


def _quotes(s: str) -> int:
    c, i = 0, 0
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == '"':
            c += 1
        i += 1
    return c


def forti_tree(text: str) -> dict:
    """Дерево config/edit/set: вузол {type, name, attrs{key: [tokens]}, children}."""
    root = {"type": "root", "name": "", "attrs": {}, "children": []}
    stack = [root]
    buf, bq = None, 0
    for raw in text.splitlines():
        if buf is not None:
            buf += "\n" + raw
            bq += _quotes(raw)
            if bq % 2:
                continue
            raw, buf = buf, None
        elif _quotes(raw) % 2:
            buf, bq = raw, _quotes(raw)
            continue
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        t = _ftokens(s)
        cmd = t[0]
        top = stack[-1]
        if cmd == "config":
            node = {"type": "config", "name": " ".join(t[1:]), "attrs": {}, "children": []}
            top["children"].append(node)
            stack.append(node)
        elif cmd == "edit":
            node = {"type": "edit", "name": t[1] if len(t) > 1 else "", "attrs": {}, "children": []}
            top["children"].append(node)
            stack.append(node)
        elif cmd == "set" and len(t) >= 2:
            top["attrs"][t[1]] = t[2:]
        elif cmd == "unset" and len(t) >= 2:
            top["attrs"].pop(t[1], None)
        elif cmd == "next":
            while len(stack) > 1:
                if stack.pop()["type"] == "edit":
                    break
        elif cmd == "end":
            while len(stack) > 1:
                if stack.pop()["type"] == "config":
                    break
    return root


def fsections(root: dict, name: str) -> list:
    """Усі секції 'config <name>' на будь-якій глибині (мульти-VDOM, config global)."""
    out = []

    def walk(node):
        for c in node["children"]:
            if c["type"] == "config" and c["name"] == name:
                out.append(c)
            elif c["type"] == "config" and c["name"] in ("vdom", "global") or c["type"] == "edit" and node["name"] == "vdom":
                walk(c)
    walk(root)
    return out


def fedits(root: dict, name: str) -> list:
    return [e for s in fsections(root, name) for e in s["children"] if e["type"] == "edit"]


def fattrs(root: dict, name: str):
    secs = fsections(root, name)
    if not secs:
        return None
    merged = {}
    for s in secs:
        merged.update(s["attrs"])
    return merged


def _v(attrs: dict, key: str, default: str = "") -> str:
    v = attrs.get(key) if attrs else None
    return " ".join(v) if v else default


def _fix_iface(names: list, body: str) -> str:
    lines = ["config system interface"]
    for n in names:
        lines += [f'    edit "{n}"', f"        {body}", "    next"]
    lines.append("end")
    return "\n".join(lines)


def audit_fortinet(text: str, parsed: dict) -> AuditReport:
    root = forti_tree(text)
    is_switch = bool(fsections(root, "switch physical-port") or fsections(root, "switch interface"))
    rep = AuditReport(vendor="FortiSwitch" if is_switch else "FortiGate")
    F = rep.findings
    add = lambda *a, **k: F.append(Finding(*a, **k))
    skipped = []

    # ── доступ до керування на інтерфейсах ──────────────────────────────────
    ifs = fedits(root, "system interface")
    insecure, wan_admin, no_desc = [], [], []
    for e in ifs:
        a = e["attrs"]
        allow = a.get("allowaccess", [])
        bad = [x for x in allow if x in ("http", "telnet")]
        if bad:
            insecure.append((e["name"], bad))
        is_wan = _v(a, "role") == "wan" or re.match(r"^wan\d*$", e["name"])
        exposed = [x for x in allow if x in ("https", "ssh", "http", "telnet", "snmp")]
        if is_wan and exposed:
            wan_admin.append((e["name"], exposed))
        ip = _v(a, "ip")
        if not is_switch and _v(a, "status") != "down" and (ip and not ip.startswith("0.0.0.0") or _v(a, "vlanid")) \
                and not _v(a, "alias") and not _v(a, "description"):
            no_desc.append(e["name"])
    if insecure:
        add("high", "admin-cleartext", "Керування по HTTP або Telnet",
            "Пароль адміністратора й сесія йдуть мережею відкритим текстом.",
            [f"{n}: {', '.join(b)}" for n, b in insecure],
            _fix_iface([n for n, _ in insecure], "unselect allowaccess http telnet"))
    if wan_admin:
        add("high", "admin-on-wan", "Адмін-доступ відкрито на WAN-інтерфейсі",
            "Вебінтерфейс/SSH FortiGate доступні з інтернету — постійні перебори паролів і ризик експлуатації вразливостей.",
            [f"{n}: {', '.join(b)}" for n, b in wan_admin],
            _fix_iface([n for n, _ in wan_admin], "unselect allowaccess " + " ".join(
                sorted({x for _n, b in wan_admin for x in b}))) +
            "\n# якщо доступ ззовні справді потрібен — обмежте trusthost адмінів і local-in-policy")
    if no_desc:
        add("low", "iface-no-description", "Робочі інтерфейси без alias/опису",
            "У політиках, логах і документації незрозуміло, що це за сегмент.",
            no_desc, _fix_iface(no_desc[:1], 'set alias "<ПРИЗНАЧЕННЯ>"'))

    # ── адміністратори ──────────────────────────────────────────────────────
    admins = fedits(root, "system admin")
    if admins:
        open_admins, no2fa = [], []
        for e in admins:
            a = e["attrs"]
            hosts = [_v(a, f"trusthost{i}") for i in range(1, 11)]
            restricted = [h for h in hosts if h and h not in ("0.0.0.0 0.0.0.0", "0.0.0.0/0")]
            if not restricted:
                open_admins.append(e["name"])
            if _v(a, "two-factor", "disable") == "disable":
                no2fa.append(e["name"])
        if open_admins:
            add("high", "admin-no-trusthost", "Адміністратори без trusted hosts",
                "Під цими обліковими записами можна входити з будь-якої адреси, включно з інтернетом.",
                open_admins, "config system admin\n" + "\n".join(
                    f'    edit "{n}"\n        set trusthost1 <МЕРЕЖА_АДМІНІВ> <МАСКА>\n    next' for n in open_admins) + "\nend")
        if any(e["name"] == "admin" for e in admins):
            add("low", "admin-default-name", "Використовується стандартний логін admin",
                "Перебір паролів завжди починають з admin — персональні імена відсікають половину атак.",
                ["admin"], "# створіть персонального адміністратора з super_admin, перевірте вхід, потім:\n"
                           "config system admin\n    delete \"admin\"\nend")
        if no2fa:
            add("low", "admin-no-2fa", "Адміністратори без двофакторної автентифікації",
                "Для входу достатньо пароля.", no2fa,
                "config system admin\n    edit \"<ЛОГІН>\"\n        set two-factor fortitoken | email\n    next\nend")
    else:
        skipped.append("system admin")

    # ── глобальні налаштування ──────────────────────────────────────────────
    g = fattrs(root, "system global")
    if g is not None:
        t = _v(g, "admintimeout", "5")
        if t.isdigit() and int(t) > 15:
            add("low", "admin-timeout", f"Таймаут адмін-сесії {t} хв",
                "Відкрита й забута вкладка з адмінкою лишається робочою надто довго.",
                [f"admintimeout {t}"], "config system global\n    set admintimeout 10\nend")
        if _v(g, "strong-crypto") == "disable":
            add("medium", "weak-crypto", "Вимкнено strong-crypto",
                "Для адмінки та VPN дозволені застарілі шифри й хеші.",
                ["strong-crypto disable"], "config system global\n    set strong-crypto enable\nend")
        tls = g.get("admin-https-ssl-versions", [])
        old = [x for x in tls if x in ("tlsv1-0", "tlsv1-1", "sslv3")]
        if old:
            add("medium", "weak-tls", "Адмінка приймає застарілі TLS",
                "TLS 1.0/1.1 мають відомі слабкості й вимкнені в сучасних браузерах.",
                [", ".join(old)], "config system global\n    set admin-https-ssl-versions tlsv1-2 tlsv1-3\nend")
        host = _v(g, "hostname")
        model = re.search(r"^#config-version=(\w+)-", text, re.M)
        if not host or (model and host == model.group(1)) or re.match(r"^(FortiGate|FortiWiFi|FortiSwitch)-", host):
            add("low", "default-hostname", "Стандартне ім'я пристрою",
                "У логах, FortiAnalyzer і документації пристрій не відрізнити від інших.",
                [host or "(не задано)"], 'config system global\n    set hostname "<ІМ\'Я>"\nend')
    else:
        skipped.append("system global")

    ntp = fattrs(root, "system ntp")
    if ntp is not None:
        servers = [e for s in fsections(root, "system ntp") for c in s["children"]
                   if c["type"] == "config" and c["name"] == "ntpserver" for e in c["children"]]
        if _v(ntp, "ntpsync", "enable") == "disable":
            add("medium", "no-ntp", "Синхронізацію часу (NTP) вимкнено",
                "Годинник пливе — логи, сертифікати й розклади політик працюють за неправильним часом.",
                ["ntpsync disable"], "config system ntp\n    set ntpsync enable\n    set type fortiguard\nend")
        elif _v(ntp, "type") == "custom" and not servers:
            add("medium", "no-ntp", "NTP типу custom без жодного сервера",
                "Синхронізація ввімкнена, але синхронізуватися немає з чим.",
                ["type custom"], 'config system ntp\n    config ntpserver\n        edit 1\n'
                                 '            set server "<IP_NTP>"\n        next\n    end\nend')
    else:
        skipped.append("system ntp")

    log_secs = [s["name"] for s in _all_configs(root) if s["name"].startswith("log ")]
    if log_secs:
        remote = False
        for name in ("log syslogd setting", "log syslogd2 setting", "log syslogd3 setting", "log syslogd4 setting",
                     "log fortianalyzer setting", "log fortianalyzer2 setting", "log fortianalyzer3 setting",
                     "log fortianalyzer-cloud setting"):
            a = fattrs(root, name)
            if a and _v(a, "status") == "enable":
                remote = True
        fg = fattrs(root, "log fortiguard setting")
        if fg and _v(fg, "status") == "enable":
            remote = True
        if not remote:
            add("medium", "no-remote-log", "Логи нікуди не відправляються",
                "Syslog, FortiAnalyzer і FortiGuard Cloud вимкнені — після переповнення диска/пам'яті історії немає.",
                [], 'config log syslogd setting\n    set status enable\n    set server "<IP_SYSLOG>"\nend')
    else:
        skipped.append("log …")

    comms = fedits(root, "system snmp community")
    bad_name, any_host = [], []
    for e in comms:
        a = e["attrs"]
        if _v(a, "status") == "disable":
            continue
        nm = _v(a, "name")
        if nm.lower() in ("public", "private"):
            bad_name.append(nm)
        hosts = [h for c in e["children"] if c["type"] == "config" and c["name"] == "hosts"
                 for h in c["children"] if h["type"] == "edit"]
        if not hosts or any(_v(h["attrs"], "ip", "0.0.0.0 0.0.0.0") in ("0.0.0.0 0.0.0.0", "0.0.0.0/0") for h in hosts):
            any_host.append(nm or e["name"])
    if bad_name:
        add("high", "snmp-default-community", "SNMP-community зі стандартною назвою",
            "public/private перебирають сканери першими.", bad_name,
            'config system snmp community\n    edit <ID>\n        set name "<ДОВГА_ВИПАДКОВА>"\n    next\nend')
    if any_host:
        add("medium", "snmp-any-host", "SNMP-community доступна з будь-якої адреси",
            "У hosts немає обмежень — опитати пристрій може будь-хто, хто знає community.", any_host,
            "config system snmp community\n    edit <ID>\n        config hosts\n            edit 1\n"
            "                set ip <IP_МОНІТОРИНГУ> 255.255.255.255\n            next\n        end\n    next\nend")

    pp = fattrs(root, "system password-policy")
    if pp is not None and _v(pp, "status", "disable") == "disable":
        add("low", "no-password-policy", "Політику складності паролів вимкнено",
            "Адміністратори можуть ставити короткі й прості паролі.", [],
            "config system password-policy\n    set status enable\n    set minimum-length 12\nend")

    # ── політики (FortiGate) ─────────────────────────────────────────────────
    if not is_switch:
        any_any, nolog = [], []
        for e in fedits(root, "firewall policy"):
            a = e["attrs"]
            if _v(a, "status") == "disable" or _v(a, "action") != "accept":
                continue
            label = f"ID {e['name']}" + (f" «{_v(a, 'name')}»" if _v(a, "name") else "")
            if a.get("srcaddr") == ["all"] and a.get("dstaddr") == ["all"] and a.get("service") == ["ALL"] \
                    and _v(a, "internet-service") != "enable":
                any_any.append(label)
            if _v(a, "logtraffic") == "disable":
                nolog.append(label)
        if any_any:
            add("high", "policy-any-any", "Політики «дозволити все всім»",
                "accept з all → all будь-яким сервісом фактично вимикає міжмережевий екран між цими інтерфейсами.",
                any_any, "# звузьте джерела, призначення й сервіси до потрібних")
        if nolog:
            add("medium", "policy-no-log", "Accept-політики без логування",
                "Дозволений трафік ніде не фіксується — розслідувати інциденти нічим.",
                nolog, "config firewall policy\n    edit <ID>\n        set logtraffic all\n    next\nend")

    # ── FortiSwitch: порти ───────────────────────────────────────────────────
    if is_switch:
        allv, stp_off, native1 = [], [], []
        for e in fedits(root, "switch interface"):
            a = e["attrs"]
            if _v(a, "allowed-vlans-all") in ("enable", "enabled"):
                allv.append(e["name"])
            if _v(a, "stp-state") == "disabled":
                stp_off.append(e["name"])
            if (_v(a, "allowed-vlans") or _v(a, "allowed-vlans-all") in ("enable", "enabled")) and _v(a, "native-vlan", "1") == "1":
                native1.append(e["name"])
        if allv:
            add("medium", "sw-allowed-all", "Порти пропускають усі VLAN (allowed-vlans-all)",
                "На порт летять усі VLAN комутатора, а не лише потрібні.",
                [compress_ports(allv)], "config switch interface\n    edit \"<ПОРТ>\"\n        set allowed-vlans-all disable\n"
                                       "        set allowed-vlans <СПИСОК>\n    next\nend")
        if stp_off:
            add("medium", "sw-stp-off", "На портах вимкнено STP",
                "Петля кабелем на такому порту покладе мережу широкомовним штормом.",
                [compress_ports(stp_off)], "config switch interface\n    edit \"<ПОРТ>\"\n        set stp-state enabled\n    next\nend")
        if native1:
            add("low", "sw-native1", "Native VLAN транку — VLAN 1",
                "Нетегований трафік потрапляє у VLAN за замовчуванням.",
                [compress_ports(native1)], "config switch interface\n    edit \"<ПОРТ>\"\n        set native-vlan <VLAN>\n    next\nend")
        no_d = [e["name"] for e in fedits(root, "switch physical-port")
                if _v(e["attrs"], "status") != "down" and not _v(e["attrs"], "description")]
        if no_d:
            add("low", "no-description", "Активні порти без опису",
                "Без description незрозуміло, що підключено, — і в документації ці рядки будуть порожні.",
                [compress_ports(no_d)], "config switch physical-port\n    edit \"<ПОРТ>\"\n"
                                        "        set description \"<ЩО ПІДКЛЮЧЕНО>\"\n    next\nend")

    if skipped:
        rep.skipped.append("У файлі немає секцій " + ", ".join(f"config {s}" for s in skipped) +
                           " — відповідні перевірки пропущено (для повного аудиту потрібен show full-configuration).")
    return rep


def _all_configs(root: dict) -> list:
    out = []

    def walk(node):
        for c in node["children"]:
            if c["type"] == "config":
                out.append(c)
            walk(c)
    walk(root)
    return out


# ═════════════════════════════════════════════════════════════════════════════
#  Точка входу
# ═════════════════════════════════════════════════════════════════════════════

def _is_fortinet(text: str) -> bool:
    return bool(re.search(r"^#config-version=", text, re.M) or
                re.search(r"^\s*config (system (global|interface)|switch (interface|physical-port))\s*$", text, re.M))


def run_audit(text: str, parsed: dict = None) -> AuditReport:
    rep = audit_fortinet(text, parsed) if _is_fortinet(text) else audit_cisco(text, parsed or {})
    rep.findings.sort(key=lambda f: SEV_ORDER[f.sev])
    return rep


def report_text(rep: AuditReport, hostname: str = "") -> str:
    """Звіт простим текстом (для .txt і буфера обміну)."""
    out = [f"АУДИТ КОНФІГУРАЦІЇ — {hostname or 'пристрій'} ({rep.vendor})",
           summary_text(rep), ""]
    for note in rep.skipped:
        out += [f"! {note}", ""]
    for i, f in enumerate(rep.findings, 1):
        out.append(f"{i}. [{SEV_LABEL[f.sev]}] {f.title}")
        out.append(f"   Чому: {f.why}")
        if f.where:
            out.append("   Де: " + "; ".join(f.where))
        if f.fix:
            out.append("   Як виправити:")
            out += ["      " + ln for ln in f.fix.splitlines()]
        out.append("")
    if not rep.findings:
        out.append("Недолаштованого не знайдено.")
    return "\n".join(out).rstrip() + "\n"
