#!/usr/bin/env python3
"""Улучшенный генератор изображений для терминала с полутонами Unicode."""

import sys
import os
from pathlib import Path
from PIL import Image

def image_to_halftones(image_path: str, max_width: int = 120):
    """
    Конвертирует изображение в цветной полутоновый арт.
    Использует Unicode половинные блоки (▀▄█) для 2x разрешения по Y.
    Каждый символ = 2 пикселя вертикально, сохраняет пропорции.
    """
    img = Image.open(image_path)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    orig_width, orig_height = img.size
    # Соотношение сторон: учитываем что символы в терминале ~2x выше чем широкие
    # При полутоновых блоках (▀▄█) каждый символ = 2 пикселя по высоте
    # Поэтому коррекция: aspect_ratio / 2 для правильных пропорций
    aspect = (orig_height / orig_width) / 2
    
    new_width = min(max_width, orig_width, 120)  # Ширина в символах (каждый символ = 2 пробела)
    new_height_px = int(new_width * aspect * 2)  # Пикселей (делим на 2 → символы)
    new_height_px = min(new_height_px, 200)
    new_height_px = max(4, (new_height_px // 2) * 2)  # Округляем до четного
    
    img = img.resize((new_width, new_height_px), Image.Resampling.LANCZOS)
    pixels = list(img.getdata())
    
    lines = []
    for y in range(0, new_height_px - 1, 2):
        line = ""
        for x in range(new_width):
            # Верхний и нижний пиксели
            r1, g1, b1 = pixels[y * new_width + x]
            r2, g2, b2 = pixels[(y + 1) * new_width + x]
            
            bright1 = (r1 + g1 + b1) / 3
            bright2 = (r2 + g2 + b2) / 3
            
            # Порог ниже чтобы видеть больше деталей
            threshold = 20
            upper = bright1 > threshold
            lower = bright2 > threshold
            
            if upper and lower:
                # Полный блок: два пробела с background color
                r, g, b = (r1 + r2) // 2, (g1 + g2) // 2, (b1 + b2) // 2
                line += f"\033[48;2;{r};{g};{b}m  \033[0m"
            elif upper:
                # Верхняя половина: foreground цвет верха, background черный
                line += f"\033[38;2;{r1};{g1};{b1}m\033[48;2;0;0;0m▀\033[0m"
            elif lower:
                # Нижняя половина: foreground цвет низа, background черный  
                line += f"\033[38;2;{r2};{g2};{b2}m\033[48;2;0;0;0m▄\033[0m"
            else:
                # Пустое место - черный фон (два пробела для ширины)
                line += "\033[48;2;0;0;0m  \033[0m"
        lines.append(line)
    
    return "\n".join(lines), (new_width, len(lines))


def image_to_quarters(image_path: str, max_width: int = 100):
    """
    Максимальное качество: четвертные блоки ▘▝▗▚▞ (2x2 пикселя на символ).
    Даже более высокое разрешение чем полутона.
    """
    img = Image.open(image_path)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    orig_width, orig_height = img.size
    aspect = orig_height / orig_width
    
    # 2x2 пикселя на символ
    new_width = min(max_width, orig_width // 2, 80)
    new_height_px = int(new_width * aspect * 2)
    new_height_px = min(new_height_px, 160)
    new_height_px = (new_height_px // 2) * 2
    new_width_px = new_width * 2
    
    img = img.resize((new_width_px, new_height_px), Image.Resampling.LANCZOS)
    pixels = list(img.getdata())
    
    # Четвертные блоки
    blocks = {
        (0, 0, 0, 0): " ",
        (1, 0, 0, 0): "▘",  # левый верх
        (0, 1, 0, 0): "▝",  # правый верх  
        (0, 0, 1, 0): "▖",  # левый низ
        (0, 0, 0, 1): "▗",  # правый низ
        (1, 1, 0, 0): "▀",  # верх
        (0, 0, 1, 1): "▄",  # низ
        (1, 0, 1, 0): "▌",  # лево
        (0, 1, 0, 1): "▐",  # право
        (1, 1, 1, 0): "▛",  # без правого низа
        (1, 1, 0, 1): "▜",  # без левого низа
        (1, 0, 1, 1): "▙",  # без правого верха
        (0, 1, 1, 1): "▟",  # без левого верха
        (1, 1, 1, 1): "█",  # полный
    }
    
    lines = []
    for y in range(0, new_height_px - 1, 2):
        line = ""
        for x in range(0, new_width_px - 1, 2):
            # 2x2 пикселя
            p1 = pixels[y * new_width_px + x]         # левый верх
            p2 = pixels[y * new_width_px + (x + 1)]     # правый верх
            p3 = pixels[(y + 1) * new_width_px + x]     # левый низ
            p4 = pixels[(y + 1) * new_width_px + (x + 1)] # правый низ
            
            threshold = 80
            mask = (
                1 if (p1[0] + p1[1] + p1[2]) / 3 > threshold else 0,
                1 if (p2[0] + p2[1] + p2[2]) / 3 > threshold else 0,
                1 if (p3[0] + p3[1] + p3[2]) / 3 > threshold else 0,
                1 if (p4[0] + p4[1] + p4[2]) / 3 > threshold else 0,
            )
            
            char = blocks.get(mask, "█")
            
            # Цвет — среднее по всем включенным пикселям
            colors = []
            if mask[0]: colors.append(p1)
            if mask[1]: colors.append(p2)
            if mask[2]: colors.append(p3)
            if mask[3]: colors.append(p4)
            
            if colors and char != " ":
                r = sum(c[0] for c in colors) // len(colors)
                g = sum(c[1] for c in colors) // len(colors)
                b = sum(c[2] for c in colors) // len(colors)
                line += f"\033[38;2;{r};{g};{b}m{char}\033[0m"
            else:
                line += " "
        lines.append(line)
    
    return "\n".join(lines), (len(lines[0]) if lines else 0, len(lines))


def image_to_fullcolor(image_path: str, max_width: int = 80):
    """
    Полноценный цвет: каждый пиксель = 2 пробела с background color.
    Полностью независимо от фона терминала.
    """
    img = Image.open(image_path)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    orig_width, orig_height = img.size
    aspect = orig_height / orig_width
    
    # Каждый пиксель = 2 пробела по ширине × 1 символ по высоте
    # Символы терминала ~2x выше чем широкие, поэтому 2:1 дает квадратные пиксели
    new_width = min(max_width, orig_width, 100)
    new_height = int(new_width * aspect)  # Без коррекции — 2 символа ширина = 2x высота символа
    new_height = min(new_height, 40)
    
    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    pixels = list(img.getdata())
    
    lines = []
    for y in range(new_height):
        line = ""
        for x in range(new_width):
            r, g, b = pixels[y * new_width + x]
            # Два пробела с background color = цветной пиксель
            line += f"\033[48;2;{r};{g};{b}m  \033[0m"
        lines.append(line)
    
    return "\n".join(lines), (new_width * 2, new_height)


if __name__ == "__main__":
    import argparse
    import shutil
    
    parser = argparse.ArgumentParser(description="Вывод изображения в терминале цветными блоками")
    parser.add_argument("image", help="Путь к изображению")
    parser.add_argument("-w", "--width", type=int, default=60, help="Максимальная ширина в пикселях")
    args = parser.parse_args()
    
    image_path = Path(args.image)
    
    if not image_path.exists():
        print(f"❌ Файл не найден: {image_path}", file=sys.stderr)
        sys.exit(1)
    
    # Проверяем что это изображение
    try:
        img = Image.open(image_path)
        img.verify()
    except Exception as e:
        print(f"❌ Не удалось открыть изображение: {e}", file=sys.stderr)
        print("Использование: python3 image_ascii.py <путь_к_изображению> [-w ШИРИНА]", file=sys.stderr)
        sys.exit(1)
    
    term_size = shutil.get_terminal_size()
    # Используем заданную ширину или авто по терминалу
    if args.width != 60:  # Пользователь задал явно
        max_width = args.width
    else:
        max_width = (term_size.columns - 2) // 2
    
    ascii_art, _ = image_to_fullcolor(str(image_path), max_width)
    print(ascii_art)

