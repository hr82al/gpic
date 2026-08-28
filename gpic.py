#!/usr/bin/env python3
"""gpic — генератор обоев для рабочего стола.

Картинка рождается локально, на этой машине: FLUX.1-schnell через
stable-diffusion.cpp с бэкендом Vulkan. Ни сети, ни ключей, ни лимитов.

Модель умеет любой размер, кратный 16, поэтому изображение генерируется
сразу в разрешении экрана — никакого растягивания.

Только стандартная библиотека: pip install не нужен.
"""

import argparse
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Корень репозитория: движок и веса лежат рядом с этим файлом.
ROOT = Path(__file__).resolve().parent
SD_BINARY = ROOT / "build" / "sd"
MODELS = ROOT / "models"

DIFFUSION_MODEL = MODELS / "flux1-schnell-Q5_K_S.gguf"
TEXT_ENCODER = MODELS / "t5xxl-Q5_0.gguf"
CLIP_L = MODELS / "clip_l.safetensors"
VAE = MODELS / "ae.safetensors"

# FLUX.1-schnell дистиллирована под малое число шагов и не использует
# classifier-free guidance: cfg-scale обязан быть 1.0, шагов хватает четырёх.
STEPS = 4
CFG_SCALE = "1.0"
SAMPLING = "euler"

FALLBACK_RESOLUTION = (1920, 1200)

SUBJECTS = [
    "misty mountain lake",
    "snow-covered pine forest",
    "rocky coastline with breaking waves",
    "rolling hills under a wide sky",
    "quiet northern fjord",
    "desert dunes with long shadows",
    "alpine meadow in bloom",
    "old stone bridge over a river",
    "autumn birch grove",
    "glacier tongue meeting dark water",
    "lavender field stretching to the horizon",
    "storm clouds over open plains",
]

LIGHT = [
    "golden hour",
    "blue hour",
    "soft morning fog",
    "dramatic sunset",
    "overcast diffused light",
    "clear starry night",
    "low winter sun",
    "after the rain",
]

STYLES = [
    "landscape photography, sharp detail",
    "cinematic wide shot",
    "painterly, rich colors",
    "minimalist composition",
    "high dynamic range photograph",
    "serene and atmospheric",
]


def random_prompt(rng):
    """Собирает промпт из трёх независимых списков — сотни комбинаций."""
    return "{}, {}, {}, beautiful wallpaper".format(
        rng.choice(SUBJECTS), rng.choice(LIGHT), rng.choice(STYLES)
    )


def parse_resolution(text):
    """Разбирает ШИРИНАxВЫСОТА."""
    parts = text.lower().split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"ожидался формат ШИРИНАxВЫСОТА, получено «{text}»"
        )
    try:
        width, height = int(parts[0]), int(parts[1])
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"ширина и высота должны быть числами, получено «{text}»"
        )
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("ширина и высота должны быть больше нуля")
    return (width, height)


def detect_screen():
    """Разрешение подключённого монитора из sysfs.

    Читаем sysfs, а не xrandr: на Wayland xrandr пуст, а sysfs работает
    и не требует зависимостей.
    """
    drm = Path("/sys/class/drm")
    if not drm.is_dir():
        return FALLBACK_RESOLUTION
    for output in sorted(drm.iterdir()):
        try:
            if (output / "status").read_text().strip() != "connected":
                continue
            first_mode = (output / "modes").read_text().splitlines()[0].strip()
        except (OSError, IndexError):
            continue
        try:
            width, height = (int(v) for v in first_mode.split("x"))
        except ValueError:
            continue
        if width > 0 and height > 0:
            return (width, height)
    return FALLBACK_RESOLUTION


def align16(value):
    """FLUX работает с размерами, кратными 16."""
    return max(16, round(value / 16) * 16)


def check_installed():
    """Понятная ошибка вместо загадочного падения, если setup.sh не запускали."""
    missing = [
        str(path)
        for path in (SD_BINARY, DIFFUSION_MODEL, TEXT_ENCODER, CLIP_L, VAE)
        if not path.exists()
    ]
    if missing:
        print("Не хватает файлов движка или весов:", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        print(f"\nЗапусти установку: {ROOT / 'setup.sh'}", file=sys.stderr)
        sys.exit(1)


def build_command(prompt, width, height, seed, out_path):
    return [
        str(SD_BINARY),
        "--diffusion-model", str(DIFFUSION_MODEL),
        "--t5xxl", str(TEXT_ENCODER),
        "--clip_l", str(CLIP_L),
        "--vae", str(VAE),
        "-p", prompt,
        "-W", str(width),
        "-H", str(height),
        "--steps", str(STEPS),
        "--cfg-scale", CFG_SCALE,
        "--sampling-method", SAMPLING,
        "--seed", str(seed),
        "-o", str(out_path),
    ]


def main():
    parser = argparse.ArgumentParser(
        prog="gpic",
        description="Генератор случайных картинок для рабочего стола (локально, FLUX.1-schnell)",
    )
    parser.add_argument("-p", "--prompt", help="промпт; без него будет случайный")
    parser.add_argument(
        "-r", "--resolution", type=parse_resolution,
        help="разрешение, например 2560x1440; без него — разрешение экрана",
    )
    parser.add_argument("-s", "--seed", type=int, help="seed для воспроизведения картинки")
    parser.add_argument(
        "file", nargs="?",
        help="путь или просто имя файла; без него — gpic-ГГГГММДД-ЧЧММСС.png",
    )
    args = parser.parse_args()

    check_installed()

    rng = random.Random()
    width, height = args.resolution or detect_screen()
    aligned = (align16(width), align16(height))
    prompt = args.prompt or random_prompt(rng)
    seed = args.seed if args.seed is not None else rng.randrange(0, 2**31)

    out_path = Path(
        args.file or f"gpic-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    )

    print(f"Промпт: {prompt}")
    if aligned != (width, height):
        print(f"Размер: {aligned[0]}x{aligned[1]} (запрошено {width}x{height}, "
              f"выровнено до кратного 16), seed: {seed}")
    else:
        print(f"Размер: {width}x{height}, seed: {seed}")
    print("Генерация идёт локально и занимает несколько минут…")

    started = time.monotonic()
    command = build_command(prompt, aligned[0], aligned[1], seed, out_path)
    # Вывод движка идёт в stderr и показывает прогресс по шагам — не прячем его.
    result = subprocess.run(command, env={**os.environ, "GGML_VK_VISIBLE_DEVICES": "0"})
    elapsed = time.monotonic() - started

    if result.returncode != 0:
        print(f"\nОшибка: движок завершился с кодом {result.returncode}", file=sys.stderr)
        sys.exit(1)
    if not out_path.exists():
        print(f"\nОшибка: движок отработал, но файл {out_path} не появился", file=sys.stderr)
        sys.exit(1)

    print(f"\nГотово за {elapsed:.0f} с: {out_path}")


if __name__ == "__main__":
    main()
