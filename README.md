# network-documentr

Генератор DOCX-документації для Cisco-обладнання на основі виводу `show running-config`.

Завантажуєте текстовий файл конфігурації — отримуєте готовий Word-документ з таблицями всіх інтерфейсів, IP-адресами і VLAN-інформацією.

---

## Можливості

- Автоматично витягує `hostname` і MGMT IP (через `ip ssh source-interface` або перший знайдений IP)
- Парсить всі блоки `interface` — фізичні і логічні
- Розпізнає режим порту: `access`, `trunk`, `routed`
- Виводить ACC/Native VLAN, дозволені VLAN на транках
- Позначає `shutdown`-порти бурштиновим кольором
- Автоматично визначає членів Port-channel (`channel-group`)
- Підтримує кодування UTF-8 / CP1251 / Latin-1
- Компактна верстка: **~48 фізичних портів на одному аркуші A4**

---

## Структура документа

```
┌─────────────────────────────────────────────────────┐
│  HOSTNAME                                   #1A2B4A │  ← 10pt bold, білий
├──────────────┬──────────────┬──────────────┬────────┤
│ МОДЕЛЬ/ВЕНДОР│ СЕРІЙНИЙ №   │ MGMT IP      │ОНОВЛЕНО│  ← info block #E8EFF8
├─────────────────────────────────────────────────────┤
│  ФІЗИЧНІ ПОРТИ                              #2C4A7C │
├──────┬───────────────┬───────┬──────┬───────┬───────┤
│ ПОРТ │ ОПИС          │ РЕЖИМ │ VLAN │ TRUNK │ ПРИМ. │  ← Gi, Fa, Te, Fo, Hu, Mgmt
├─────────────────────────────────────────────────────┤
│  PORT-CHANNEL ТА VLAN                       #2C4A7C │
├──────┬───────────────┬───────┬──────────────┬───────┤
│ ПОРТ │ ОПИС          │ РЕЖИМ │ IP-АДРЕСА    │ ПРИМ. │  ← Po, Vlan, Lo
└─────────────────────────────────────────────────────┘
```

### Колонки — фізичні порти (182 mm)

| Колонка         | Ширина | Вирівнювання |
|-----------------|--------|--------------|
| ПОРТ            | 18 mm  | center, bold |
| ОПИС            | 45 mm  | left         |
| РЕЖИМ           | 22 mm  | center       |
| ACC/NAT VLAN    | 32 mm  | center       |
| TRUNK VLANs     | 42 mm  | center       |
| ПРИМІТКА        | 23 mm  | center       |

### Колонки — Port-channel та VLAN (182 mm)

| Колонка         | Ширина | Вирівнювання |
|-----------------|--------|--------------|
| ПОРТ            | 18 mm  | center, bold |
| ОПИС            | 82 mm  | left         |
| РЕЖИМ           | 22 mm  | center       |
| IP-АДРЕСА       | 37 mm  | center       |
| ПРИМІТКА        | 23 mm  | center       |

---

## Вимоги

- Python 3.10+
- `python-docx >= 1.2.0`
- `lxml`
- `tkinter` (вбудований у CPython)
- `pyinstaller` — тільки для збірки .exe

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

1. Натисніть **Огляд…** і оберіть `.txt`-файл з виводом `show running-config`
2. Заповніть поля **Модель / Вендор** і **Серійний номер** (необов'язково)
3. Натисніть **Створити DOCX**
4. Вкажіть куди зберегти — документ готовий

MGMT IP підхоплюється автоматично (з `ip ssh source-interface` або першого `ip address`).

---

## Тести

```bash
pip install pytest
python -m pytest tests/ -v
```

186 тестів покривають парсер (`test_parser.py`) та DOCX-білдер (`test_docx_builder.py`).

---

## Збірка .exe

```bat
build.bat
```

Використовує PyInstaller з прапорами:

```
--onefile --windowed --name network-documentr --collect-all=docx
```

> `--collect-all=docx` є критичним: без нього .exe не знаходить `docx/templates/default.docx` і падає при запуску.

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
- **Shutdown**: колонка РЕЖИМ виводиться кольором `#B45309` (amber).
- **Port-channel members**: рядки з `channel-group N` отримують примітку `PoN member` автоматично.
- **Кодування**: файл читається послідовно через UTF-8 → CP1251 → Latin-1.
