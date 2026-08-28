#!/usr/bin/env python3
"""gpic — генератор обоев для рабочего стола.

Картинка рождается локально, на этой машине: FLUX.1-schnell через
stable-diffusion.cpp с бэкендом Vulkan. Ни сети, ни ключей, ни лимитов.

Модель умеет любой размер, кратный 16, поэтому изображение генерируется
сразу в разрешении экрана — никакого растягивания.

Только стандартная библиотека: pip install не нужен.
"""

import argparse
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

# Маленькая языковая модель, придумывающая описания «с нуля». Нужна не
# всегда: без неё работает комбинаторика по спискам, просто беднее.
LLAMA_BINARY = ROOT / "build" / "llama-cli"
PROMPTER_MODEL = MODELS / "prompter.gguf"

# FLUX.1-schnell дистиллирована под малое число шагов и не использует
# classifier-free guidance: cfg-scale обязан быть 1.0, шагов хватает четырёх.
STEPS = 4
CFG_SCALE = "1.0"
SAMPLING = "euler"

FALLBACK_RESOLUTION = (1920, 1200)

# Описания придумывает маленькая языковая модель, а не списки слов.
# Перечислять сюжеты руками бессмысленно: сколько ни пиши, получится
# конечный список, который приедается. Модель же внутри темы выдумывает
# бесконечно, и наша задача — только задать направление.
#
# Инструкции модели на английском: FLUX обучался на английских подписях
# и понимает их точнее.

# Широкие области, из которых берётся тема. Намеренно общие: конкретику
# придумывает модель. Добавлять сюда новые темы — самый дешёвый способ
# расширить репертуар.
THEMES = [
    "wild landscapes", "coastlines and open water", "mountains and high places",
    "forests and undergrowth", "deserts and arid land", "polar and frozen places",
    "city architecture", "interiors and quiet rooms", "industrial spaces",
    "bridges, towers and infrastructure", "ruins and abandoned places",
    "space and astronomy", "atmospheric phenomena", "underwater and deep sea",
    "microscopic structures", "minerals, crystals and geology",
    "plants and botanical detail", "animals in their habitat",
    "birds and flight", "insects and small creatures",
    "machines and mechanisms", "vehicles and transport",
    "everyday objects arranged", "textiles, fibres and surfaces",
    "abstract geometry", "flowing organic forms", "light and shadow studies",
    "weather and storms", "gardens and cultivated land",
    "harbours and working shores", "deep forests at night",
    "volcanic and geothermal terrain", "canyons and rock formations",
    "reflections and mirrored scenes", "silhouettes against bright skies",
    "aerial views of terrain", "still life with natural objects",
    "science-fiction environments", "mythic and dreamlike places",
    "seasonal transitions",
]

# Углы захода для творческого режима. Без них маленькая модель
# сваливается в один и тот же «закат над горами» — она сильно
# тяготеет к банальному, и сбить её можно только заданием направления.
CREATIVE_ANGLES = [
    "an unexpected place nobody photographs",
    "two unrelated things merged into one scene",
    "an everyday object seen in an extraordinary way",
    "a moment from an imaginary world",
    "something microscopic treated as a vast landscape",
    "an abandoned structure reclaimed by something unusual",
    "a scene defined entirely by one strange material",
    "a view from an impossible vantage point",
    "an atmospheric phenomenon that does not exist",
    "machinery imagined as a living organism",
    "a landscape built out of an unrelated substance",
    "a familiar place under impossible light",
    "architecture growing like a plant",
    "a still life of objects that should not coexist",
    "the inside of something normally seen from outside",
]

STYLE_HINTS = [
    "photographic realism", "cinematic composition", "painterly and textured",
    "minimalist and graphic", "richly detailed illustration",
    "moody and atmospheric", "clean modern render", "soft impressionistic",
]

THEMED_INSTRUCTION = (
    "Write one vivid caption describing a single photograph or painting. "
    "Subject area: {theme}. Visual treatment: {style}. "
    "One line, under 30 words. Concrete visual nouns and adjectives only. "
    "Describe what is seen, not what it means. "
    "No quotes, no explanation, no title, no text visible in the image."
)

CREATIVE_INSTRUCTION = (
    "Invent one striking, unusual caption describing a single image: {angle}. "
    "Be surprising and specific, avoid the obvious. Visual treatment: {style}. "
    "One line, under 30 words. Concrete visual nouns and adjectives only. "
    "No quotes, no explanation, no title, no text visible in the image."
)

# Хвост, подталкивающий модель рисования к детальному результату.
QUALITY_TAIL = "beautiful desktop wallpaper, intricate detail, fine texture, natural depth"

# Доля описаний, придуманных в творческом режиме на максимальной температуре.
CREATIVE_CHANCE = 0.30

# Температуры подобраны замером, а не на глаз. Творческий режим держится
# на min-p, а не на одной температуре: min-p отсекает токены ниже доли от
# самого вероятного, поэтому связность сохраняется там, где голая
# температура уже даёт бессвязицу.
THEMED_TEMPERATURE = "0.90"
CREATIVE_TEMPERATURE = "1.10"
MIN_P = "0.05"

LLM_MAX_TOKENS = "70"
LLM_TIMEOUT_SECONDS = 120

# Запасные описания на случай, если llama.cpp не собран или модель не
# скачана. Утилита обязана работать и без них, пусть и однообразно.
FALLBACK_PROMPTS = [
    "misty mountain lake at first light, still water, layered ridges fading into haze",
    "snow-covered pine forest under low winter sun, long blue shadows across the drifts",
    "rocky coastline with breaking waves, spray caught in golden backlight",
    "desert dunes with long shadows at dusk, wind-carved ridges, deep amber tones",
    "storm clouds massing over open plains, shafts of light breaking through",
    "frost crystals spreading across dark glass, sharp macro detail",
    "spiral galaxy against deep space, dust lanes and scattered star clusters",
    "rain-slick city street at night, neon reflections stretched across wet asphalt",
    "flowing liquid metal forms, polished highlights on smooth curves",
    "ancient stone bridge over a green river, moss on weathered blocks",
    "bioluminescent jellyfish drifting in black water, translucent bells glowing",
    "terraced fields on a steep hillside at dawn, mist pooling in the valleys",
]


def llm_prompt(rng):
    """Просит языковую модель придумать описание. None, если не вышло.

    Отсутствие модели не ошибка: gpic должен работать и без llama.cpp,
    просто с более бедным разнообразием.
    """
    if not LLAMA_BINARY.exists() or not PROMPTER_MODEL.exists():
        return None

    style = rng.choice(STYLE_HINTS)
    if rng.random() < CREATIVE_CHANCE:
        instruction = CREATIVE_INSTRUCTION.format(
            angle=rng.choice(CREATIVE_ANGLES), style=style)
        temperature = CREATIVE_TEMPERATURE
    else:
        instruction = THEMED_INSTRUCTION.format(
            theme=rng.choice(THEMES), style=style)
        temperature = THEMED_TEMPERATURE

    command = [
        str(LLAMA_BINARY), "-m", str(PROMPTER_MODEL),
        "-p", instruction,
        "-n", LLM_MAX_TOKENS,
        "--temp", temperature,
        "--min-p", MIN_P,
        "--repeat-penalty", "1.1",
        "-s", str(rng.randrange(0, 2**31)),
        "--no-display-prompt",
        "-st",
        "-ngl", "99",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True,
            timeout=LLM_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None

    return clean_llm_output(result.stdout)


def clean_llm_output(text):
    """Вытаскивает описание из вывода llama-cli.

    В этой сборке llama-cli работает только в режиме диалога и печатает
    баннер, эхо промпта со знаком «>» и строку статистики в квадратных
    скобках. Ответ лежит между эхом и статистикой — по этим двум маркерам
    и ориентируемся; если структура не совпала, пробуем эвристику по длине.
    """
    lines = [line.strip() for line in text.replace("\r", "\n").splitlines()]

    answer = []
    seen_echo = False
    for line in lines:
        if not seen_echo:
            if line.startswith(">"):
                seen_echo = True
            continue
        if line.startswith("[") or line.startswith("Exiting"):
            break
        if line:
            answer.append(line)

    candidates = [" ".join(answer)] if answer else []
    candidates.extend(lines)

    for candidate in candidates:
        candidate = candidate.strip().strip('"').strip("'")
        candidate = candidate.lstrip("-*0123456789. ").strip().rstrip('"').strip()
        if not (20 <= len(candidate) <= 300):
            continue
        if candidate.startswith((">", "[", "/")) or candidate.endswith(":"):
            continue
        if candidate.lower().startswith(("here", "sure", "caption", "write ", "invent ")):
            continue
        return candidate
    return None


def compose_prompt(rng):
    """Описание от языковой модели, а при её отсутствии — из запасного списка."""
    generated = llm_prompt(rng)
    if generated:
        return f"{generated}, {QUALITY_TAIL}"
    return f"{rng.choice(FALLBACK_PROMPTS)}, {QUALITY_TAIL}"


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
        str(p)
        for p in (SD_BINARY, DIFFUSION_MODEL, TEXT_ENCODER, CLIP_L, VAE)
        if not p.exists()
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
        # Flash attention здесь не оптимизация, а необходимость: без него
        # тензоры внимания не влезают в лимит буфера Vulkan, движок
        # сваливается на медленный путь и шаг занимает 337 с вместо 88.
        "--diffusion-fa",
        # Тайловое декодирование: латент режется на куски, каждый проходит
        # через полноразмерный VAE отдельно. Без этого декодирование картинки
        # размером с экран требует буфера больше 4 ГБ VRAM, драйвер теряет
        # устройство («device lost on Vulkan0») и результат гибнет уже после
        # того, как все шаги отработали. Качество при этом полное — в отличие
        # от TAESD, который дешевле, но декодирует приближённо.
        "--vae-tiling",
        # Текстовые энкодеры нужны только на первой стадии, для кодирования
        # промпта. Без этого флага их 3.4 ГБ висят в видеопамяти до конца.
        "--params-backend", "te=disk",
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
    prompt = args.prompt or compose_prompt(rng)
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
    # Устройство Vulkan не навязываем: ggml сам отбрасывает программный
    # llvmpipe и выбирает настоящую видеокарту. Зашитый номер устройства
    # сломался бы на машине с другим порядком перечисления.
    result = subprocess.run(command)
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
