# network-documentr

Генератор DOCX-документації для Cisco-обладнання на основі виводу `show running-config`.

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

1. Натисніть **Завантажити конфігурації** і оберіть один або кілька `.txt`-файлів з виводом `show running-config`
   — або перетягніть файл(и) прямо на кнопку (потребує `tkinterdnd2`)
2. Заповніть поля **Модель / Вендор** і **Серійний номер** (необов'язково)
3. Натисніть **Створити DOCX** (кнопка з'являється після завантаження конфігурацій)
   - Один файл → вибір імені та шляху збереження
   - Кілька файлів → вибір директорії, документи зберігаються як `<hostname>_doc.docx`

MGMT IP підхоплюється автоматично (з `ip ssh source-interface` або першого `ip address`).

---

## Тести

```bash
pip install pytest
python -m pytest tests/ -v
```

252 тести покривають парсер (`test_parser.py`) та DOCX-білдер (`test_docx_builder.py`).

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
│   ├── test_parser.py         # Юніт-тести парсера
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
