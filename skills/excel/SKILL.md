# Excel Skill

Работа с Excel файлами (.xlsx, .xlsm, .csv, .tsv)

## Установка для botinok

```bash
# Вариант 1: системный Python (нужен --break-system-packages)
pip install openpyxl pandas --break-system-packages

# Вариант 2: виртуальное окружение botinok
python3 -m venv ~/.botinok/venv
~/.botinok/venv/bin/pip install openpyxl pandas
```

## Инструменты

- **Python + openpyxl** — создание, редактирование, чтение Excel файлов
- **Python + pandas** — работа с таблицами и данными
- **shell_exec** — выполнение Python скриптов

## Быстрые примеры

### Создать Excel файл

```python
from openpyxl import Workbook

wb = Workbook()
ws = wb.active
ws.title = "Sheet1"
ws['A1'] = "Заголовок"
ws['B1'] = 100
ws['C1'] = "=SUM(B1:B10)"  # формула

wb.save("output.xlsx")
```

### Прочитать Excel файл

```python
import openpyxl

wb = openpyxl.load_workbook("file.xlsx")
ws = wb.active

for row in ws.iter_rows(values_only=True):
    print(row)
```

### Читать с формулами (не вычисленными)

```python
wb = openpyxl.load_workbook("file.xlsx", data_only=False)
```

### Читать с вычисленными значениями

```python
wb = openpyxl.load_workbook("file.xlsx", data_only=True)
```

## Формулы

openpyxl поддерживает формулы Excel:
- `=SUM(A1:A10)`
- `=AVERAGE(B1:B5)`
- `=IF(A1>10, "больше", "меньше")`
- `=VLOOKUP(A1, Sheet2!A:B, 2, FALSE)`

## Работа с листами

```python
# Создать лист
ws = wb.create_sheet("Новый")

# Удалить лист
del wb["Sheet1"]

# Переименовать
ws.title = "Переименовано"
```

## Форматирование (базовое)

```python
from openpyxl.styles import Font, PatternFill

# Шрифт
ws['A1'].font = Font(bold=True, color="FF0000")

# Заливка
ws['A1'].fill = PatternFill(start_color="FFFF00", fill_type="solid")

# Ширина столбца
ws.column_dimensions['A'].width = 20
```

## CSV файлы

```python
import pandas as pd

# Читать CSV
df = pd.read_csv("file.csv")

# Сохранить в Excel
df.to_excel("output.xlsx", index=False)
```

## Важные моменты

1. **Путь к файлу** — используй абсолютные пути или проверяй cwd
2. **Формулы** — сохраняй с `data_only=False` чтобы не потерять
3. **Большие файлы** — `iter_rows()` вместо загрузки всего в память
4. **Кодировка CSV** — указывай `encoding='utf-8'` или `encoding='cp1251'`
