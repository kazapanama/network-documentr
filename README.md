# network-documentr

Генератор DOCX-документації для Cisco-обладнання (`show running-config`) та Fortinet — FortiGate і standalone FortiSwitch (`show full-configuration`). Вендор визначається автоматично.

Завантажуєте текстовий файл конфігурації — отримуєте готовий Word-документ з таблицями всіх інтерфейсів, IP-адресами і VLAN-інформацією.

---

## Можливості

- Автоматично витягує `hostname` і MGMT IP (через `ip ssh source-interface` або перший знайдений IP)
- Парсить всі блоки `interface` — фізичні і логічні
- Розпізнає режим порту: `access`, `trunk`, `routed`
- Виводить ACC/Native VLAN, дозволені VLAN на транках
- Позначає `shutdown`-порти окремим кольором
- Автоматично визначає членів Port-channel (`channel-group`)
- Підтримує кодування UTF-8 / CP1251 / Latin-1
- **Автовизначення моделі та серійного номера** — якщо до файлу конфігурації доклеєно вивід `show version` / `show inventory` (Cisco) чи `get system status` (Fortinet)
- **Fortinet**: FortiGate (`config system interface` — physical / vlan / aggregate / loopback / tunnel) і standalone FortiSwitch (`config switch physical-port|interface|trunk|vlan`)
- Розпізнає Voice VLAN, STP PortFast / RootGuard / BPDUGuard, Port Security — виводить у ПРИМІТКУ
- Генерує таблицю **VLAN DEFINITIONS** з назвами VLAN (`vlan N` + `name`)
- **Drag & drop** конфігураційного файлу на кнопку "Завантажити" (потребує `tkinterdnd2`)
- **Batch mode** — вибір кількох файлів одночасно, генерація всіх документів у обрану директорію

---

## Структура документа

```
┌─────────────────────────────────────────────────────┐
│  HOSTNAME                                           │
├──────────────┬──────────────┬──────────────┬────────┤
│ МОДЕЛЬ/ВЕНДОР│ СЕРІЙНИЙ №   │ MGMT IP      │ОНОВЛЕНО│
├─────────────────────────────────────────────────────┤
│  ФІЗИЧНІ ПОРТИ                                      │
├──────┬───────────────┬───────┬──────┬───────┬───────┤
│ ПОРТ │ ОПИС          │ РЕЖИМ │ VLAN │ TRUNK │ ПРИМ. │
├─────────────────────────────────────────────────────┤
│  PORT-CHANNEL ТА VLAN                               │
├──────┬───────────────┬───────┬──────────────┬───────┤
│ ПОРТ │ ОПИС          │ РЕЖИМ │ IP-АДРЕСА    │ ПРИМ. │
├─────────────────────────────────────────────────────┤
│  VLAN DEFINITIONS  (якщо є vlan + name у конфізі)  │
├──────┬─────────────────────────────────────────────┤
│ VLAN │ НАЗВА                                       │
└─────────────────────────────────────────────────────┘
```

---

## Вимоги

- Python 3.10+
- `python-docx >= 1.2.0`
- `lxml`
- `tkinter` (вбудований у CPython)
- `pyinstaller` — тільки для збірки .exe
- `tkinterdnd2` — опціонально, для drag & drop

---

## Встановлення та запуск

### З вихідного коду

```bash
# Створити і активувати venv
python -m venv .venv
.venv\Scripts\activate

# Встановити залежності
pip install -r requirements.txt

# Запустити
python main.py
```

### Готовий .exe

Просто запустіть `dist\network-documentr.exe` — без Python і без залежностей.

---

## Використання

1. Натисніть **Завантажити конфігурації** і оберіть один або кілька файлів з виводом `show running-config` (Cisco) чи `show full-configuration` (Fortinet)
   — або перетягніть файл(и) прямо на кнопку (потребує `tkinterdnd2`)
2. Перевірте поля **Модель / Вендор** і **Серійний номер** — вони заповнюються автоматично, якщо у файлі є вивід `show version` / `show inventory` / `get system status` (див. нижче), інакше впишіть вручну (необов'язково)
3. Натисніть **Створити DOCX** (кнопка з'являється після завантаження конфігурацій)
   - Один файл → вибір імені та шляху збереження
   - Кілька файлів → вибір директорії, документи зберігаються як `<hostname>_doc.docx`

MGMT IP підхоплюється автоматично:
- **Cisco** — з `ip ssh source-interface`, інакше перший `ip address`
- **Fortinet** — інтерфейс `mgmt`/`mgmt1`/`management`, інакше інтерфейс з `allowaccess` ssh/https, інакше перший IP

---

## Автовизначення моделі та серійного номера

Поля **Модель / Вендор** і **Серійний номер** заповнюються автоматично, якщо у тому ж текстовому файлі, що й конфігурація, є вивід додаткових команд. Просто виконайте їх у тій самій сесії терміналу і збережіть увесь вивід в один файл.

### Cisco

```
show running-config
show inventory          ← модель (PID) + серійний номер (SN)
show version            ← запасний варіант
```

Пріоритет пошуку:

1. `show inventory` — перший рядок `PID: … , SN: …` (шасі / головний юніт стека)
2. `show version` — `Model number : …`
3. `show version` — `System serial number : …`
4. `show version` — `Processor board ID …` (старі платформи, напр. 3750)

### Fortinet

```
show full-configuration
get system status       ← серійний номер (рядок Serial-Number:)
```

- **Модель** береться прямо з заголовка конфігурації — рядок `#config-version=FGT60E-7.2.5-…` (`FGT60E`), окрема команда не потрібна
- **Серійний номер** у `show full-configuration` відсутній — для нього доклейте вивід `get system status` (рядок `Serial-Number: FGT60E4Q16012345`)

Якщо автовизначення нічого не знайшло, поля можна заповнити вручну — або лишити порожніми (у документі буде «—»).

---

## Тести

```bash
pip install pytest
python -m pytest tests/ -v
```

364 тести покривають Cisco-парсер (`test_parser.py`), Fortinet-парсер (`test_fortinet.py`) та DOCX-білдер (`test_docx_builder.py`).

---

## Збірка .exe

```bat
build.bat
```

Використовує PyInstaller з прапорами:

```
--onefile --windowed --name network-documentr --collect-all=docx --collect-all=tkinterdnd2
```

> `--collect-all=docx` є критичним: без нього .exe не знаходить `docx/templates/default.docx` і падає при запуску.
> `--collect-all=tkinterdnd2` потрібен для drag & drop; якщо пакет не встановлено — функція просто не активується.

Результат: `dist\network-documentr.exe`

---

## Структура проекту

```
network-documentr/
├── main.py                    # Єдиний source-файл: парсер + DOCX-білдер + GUI
├── build.bat                  # Збірка .exe через PyInstaller
├── requirements.txt           # python-docx, lxml, pyinstaller
├── network-documentr.spec     # PyInstaller spec
├── tests/
│   ├── test_parser.py         # Юніт-тести Cisco-парсера
│   ├── test_fortinet.py       # Юніт-тести Fortinet-парсера
│   └── test_docx_builder.py   # Тести DOCX-білдера
├── dist/
│   └── network-documentr.exe  # Готовий бінарник
└── CLAUDE.md                  # Інструкції для AI-асистента
```

---

## Підтримувані типи інтерфейсів

| Тип              | Скорочення | Таблиця   |
|------------------|------------|-----------|
| GigabitEthernet  | Gi         | Фізичні   |
| FastEthernet     | Fa         | Фізичні   |
| TenGigabitEthernet | Te       | Фізичні   |
| TwentyFiveGigE   | Twe        | Фізичні   |
| FortyGigabitEthernet | Fo     | Фізичні   |
| HundredGigE      | Hu         | Фізичні   |
| Management       | Mgmt       | Фізичні   |
| Port-channel     | Po         | Po / VLAN |
| Vlan             | Vlan       | Po / VLAN |
| Loopback         | Lo         | Po / VLAN |

---

## Примітки

- **Кирилиця**: функція `_set_run_font()` встановлює `w:cs="Calibri"` — без цього кирилиця у Word рендериться іншим шрифтом.
- **Shutdown**: колонка РЕЖИМ виділяється окремим кольором (amber).
- **Port-channel members**: рядки з `channel-group N` отримують примітку `PoN member` автоматично.
- **ПРИМІТКА** формується в порядку: `PoN member` → `Voice:N` → `PortFast` → `RootGuard` → `BPDUGuard` → `SecMax:N` / `PortSec` → `shutdown`.
- **VLAN DEFINITIONS**: секція додається лише якщо конфіг містить блоки `vlan N` + `name`.
- **Кодування**: файл читається послідовно через UTF-8 → CP1251 → Latin-1.
