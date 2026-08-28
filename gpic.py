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
import zlib
import time
from datetime import datetime
from pathlib import Path

# Корень репозитория: движок и веса лежат рядом с этим файлом.
ROOT = Path(__file__).resolve().parent
SD_BINARY = ROOT / "build" / "sd"
MODELS = ROOT / "models"

# Веса от лучшего к запасному: берётся первый ДОКАЧАННЫЙ. Ожидаемый размер
# указан именно для этого — на оборванном файле движок выдаёт невнятное
# «read tensor data failed», и понять причину без подсказки трудно.
#
# Q8_0 против Q5_K_S: сравнение на одном сюжете видимой разницы не показало,
# а по показателям детализации Q5 был даже чуть выше. Но время у них
# одинаковое (упор в вычисления, а не в перекачку весов), так что Q8 стоит
# только памяти — пик 17.4 ГБ против 11.1. При 27 ГБ это приемлемо.
DIFFUSION_WEIGHTS = [
    ("flux1-schnell-Q8_0.gguf", 12_690_000_000),
    ("flux1-schnell-Q5_K_S.gguf", 8_260_000_000),
]

TEXT_ENCODERS = [
    ("t5xxl-Q8_0.gguf", 5_200_000_000),
    ("t5xxl-Q5_0.gguf", 3_360_000_000),
]
CLIP_L = MODELS / "clip_l.safetensors"
VAE = MODELS / "ae.safetensors"

# Быстрый режим: SDXL-Turbo вместо FLUX. Вчетверо меньше параметров и
# дистиллирован под один-два шага.
#
# Рисуем в четверть целевого размера и увеличиваем нейросетевым ESRGAN.
# Прямая генерация в разрешении экрана НЕ работает: модель обучена на
# 512x512, и на площади в девять раз большей она достраивает композицию
# повторением — сросшиеся фигуры, лишние руки, два горизонта. На пейзаже
# это незаметно (лишняя гряда сходит за гряду), на людях видно сразу.
#
# Негативным промптом это не лечится: у Turbo cfg-scale равен 1.0, а при
# единице classifier-free guidance выключен и негативный промпт не
# действует. Поднять cfg нельзя — модель под него не дистиллирована.
FAST_MODEL = MODELS / "sdxl-turbo-fp16.safetensors"
UPSCALER = MODELS / "RealESRGAN_x4.pth"
FAST_STEPS = 2
FAST_CFG_SCALE = "1.0"
FAST_UPSCALE = 4

# Маленькая языковая модель, придумывающая описания «с нуля». Нужна не
# всегда: без неё работает запасной список описаний, просто беднее.
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


def llm_prompt(rng, force_creative=False):
    """Просит языковую модель придумать описание. None, если не вышло.

    Отсутствие модели не ошибка: gpic должен работать и без llama.cpp,
    просто с более бедным разнообразием.
    """
    if not LLAMA_BINARY.exists() or not PROMPTER_MODEL.exists():
        return None

    style = rng.choice(STYLE_HINTS)
    if force_creative or rng.random() < CREATIVE_CHANCE:
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


def compose_prompt(rng, force_creative=False):
    """Описание от языковой модели, а при её отсутствии — из запасного списка."""
    generated = llm_prompt(rng, force_creative)
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


def _png_chunks(data):
    """Разбирает PNG на чанки. Возвращает пары (тип, содержимое)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("не PNG")
    pos = 8
    while pos < len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        yield kind, body
        pos += 12 + length


def _unfilter(raw, width, height, channels):
    """Снимает построчные фильтры PNG, возвращает плоский массив пикселей."""
    stride = width * channels
    out = bytearray(stride * height)
    prev = bytearray(stride)
    pos = 0
    for row in range(height):
        filter_type = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if filter_type == 1:  # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up = prev[i]
                upleft = prev[i - channels] if i >= channels else 0
                p = left + up - upleft
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upleft)
                if pa <= pb and pa <= pc:
                    pred = left
                elif pb <= pc:
                    pred = up
                else:
                    pred = upleft
                line[i] = (line[i] + pred) & 0xFF
        elif filter_type != 0:
            raise ValueError(f"неизвестный фильтр PNG: {filter_type}")
        out[row * stride:(row + 1) * stride] = line
        prev = line
    return out


def _write_png(path, pixels, width, height, channels):
    """Пишет PNG без фильтрации — короче кода и достаточно быстро."""
    color_type = {3: 2, 4: 6}[channels]
    stride = width * channels
    raw = bytearray()
    for row in range(height):
        raw.append(0)
        raw += pixels[row * stride:(row + 1) * stride]

    def chunk(kind, body):
        return (len(body).to_bytes(4, "big") + kind + body
                + zlib.crc32(kind + body).to_bytes(4, "big"))

    header = (width.to_bytes(4, "big") + height.to_bytes(4, "big")
              + bytes([8, color_type, 0, 0, 0]))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


def crop_png(path, target_width, target_height):
    """Подрезает PNG по центру до точного размера.

    Нужно потому, что движок выравнивает размеры: SDXL до кратного 64,
    FLUX до кратного 16. Запрошенные 1920x1200 превращаются в 1920x1216,
    и без подрезки на экране оказывались бы обои не того размера.

    Разбор PNG написан руками ради обещания «только стандартная
    библиотека»: тянуть Pillow ради обрезки шестнадцати строк пикселей
    несоразмерно. Поддерживается ровно то, что пишет движок — 8 бит,
    RGB или RGBA, без чересстрочности.
    """
    data = path.read_bytes()
    idat = bytearray()
    width = height = channels = None
    for kind, body in _png_chunks(data):
        if kind == b"IHDR":
            width = int.from_bytes(body[0:4], "big")
            height = int.from_bytes(body[4:8], "big")
            depth, color_type, _, _, interlace = body[8:13]
            if depth != 8 or interlace != 0 or color_type not in (2, 6):
                return False
            channels = 3 if color_type == 2 else 4
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break

    if width is None or (width, height) == (target_width, target_height):
        return False
    if width < target_width or height < target_height:
        return False

    pixels = _unfilter(zlib.decompress(bytes(idat)), width, height, channels)

    left = (width - target_width) // 2
    top = (height - target_height) // 2
    stride = width * channels
    new_stride = target_width * channels
    cropped = bytearray(new_stride * target_height)
    for row in range(target_height):
        start = (top + row) * stride + left * channels
        cropped[row * new_stride:(row + 1) * new_stride] = \
            pixels[start:start + new_stride]

    _write_png(path, cropped, target_width, target_height, channels)
    return True


def align_up(value, step):
    """Округляет размер ВВЕРХ до кратного step.

    Движок всё равно выровняет размер сам, поэтому лучше сделать это
    заранее и вверх: тогда лишнее можно подрезать, а не дорисовывать.
    """
    return max(step, -(-value // step) * step)


def pick_complete(candidates):
    """Первый из файлов, который есть на диске и докачан целиком.

    Допуск в процент: у зеркал размер иногда отличается на десятки байт.
    """
    for name, expected in candidates:
        path = MODELS / name
        if path.exists() and path.stat().st_size >= expected * 0.99:
            return path
    return None


def check_installed(fast):
    """Понятная ошибка вместо загадочного падения, если setup.sh не запускали."""
    needed = [SD_BINARY]
    model = encoder = None
    if fast:
        needed += [FAST_MODEL, UPSCALER]
    else:
        needed += [CLIP_L, VAE]
        model = pick_complete(DIFFUSION_WEIGHTS)
        encoder = pick_complete(TEXT_ENCODERS)

    missing = [str(p) for p in needed if not p.exists()]
    if not fast:
        if model is None:
            missing.append(f"{MODELS}/{DIFFUSION_WEIGHTS[-1][0]} (или Q8_0)")
        if encoder is None:
            missing.append(f"{MODELS}/{TEXT_ENCODERS[-1][0]} (или Q8_0)")

    if missing:
        print("Не хватает файлов движка или весов "
              "(или они докачаны не полностью):", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        print(f"\nЗапусти установку: {ROOT / 'setup.sh'}", file=sys.stderr)
        sys.exit(1)

    return model, encoder


def build_fast_command(prompt, width, height, seed, out_path):
    """SDXL-Turbo в четверти размера плюс нейросетевое увеличение вчетверо."""
    return [
        str(SD_BINARY),
        "-m", str(FAST_MODEL),
        "--upscale-model", str(UPSCALER),
        "--diffusion-fa",
        "--vae-tiling",
        "--params-backend", "te=disk",
        "-p", prompt,
        "-W", str(width),
        "-H", str(height),
        "--steps", str(FAST_STEPS),
        "--cfg-scale", FAST_CFG_SCALE,
        "--sampling-method", SAMPLING,
        "--seed", str(seed),
        "-o", str(out_path),
    ]


def build_command(model, encoder, prompt, width, height, seed, out_path):
    return [
        str(SD_BINARY),
        "--diffusion-model", str(model),
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
        "--t5xxl", str(encoder),
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
        "--random", action="store_true",
        help="всегда творческий режим вместо 30%% случаев: необычные, "
             "неожиданные сюжеты",
    )
    parser.add_argument(
        "-f", "--fast", action="store_true",
        help="быстрый режим: SDXL-Turbo вместо FLUX, десятки секунд вместо минут",
    )
    parser.add_argument(
        "file", nargs="?",
        help="путь или просто имя файла; без него — gpic-ГГГГММДД-ЧЧММСС.png",
    )
    args = parser.parse_args()

    model, encoder = check_installed(args.fast)

    rng = random.Random()
    width, height = args.resolution or detect_screen()
    # Движок выравнивает размеры: SDXL до кратного 64, FLUX до 16. Округляем
    # ВВЕРХ, чтобы потом подрезать до запрошенного, а не растягивать.
    # В быстром режиме рисуем в четверть — увеличение вернёт размер.
    if args.fast:
        aligned = (align_up(width // FAST_UPSCALE, 64),
                   align_up(height // FAST_UPSCALE, 64))
    else:
        aligned = (align_up(width, 16), align_up(height, 16))
    prompt = args.prompt or compose_prompt(rng, args.random)
    seed = args.seed if args.seed is not None else rng.randrange(0, 2**31)

    out_path = Path(
        args.file or f"gpic-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    )

    print(f"Промпт: {prompt}")
    print(f"Размер: {width}x{height}, seed: {seed}")
    if args.fast:
        print(f"Быстрый режим: SDXL-Turbo рисует {aligned[0]}x{aligned[1]}, "
              f"ESRGAN увеличивает до {aligned[0] * FAST_UPSCALE}x"
              f"{aligned[1] * FAST_UPSCALE}")
        command = build_fast_command(prompt, aligned[0], aligned[1], seed, out_path)
    else:
        print(f"Модель: {model.name}, энкодер: {encoder.name}")
        print("Генерация идёт локально и занимает несколько минут…")
        command = build_command(model, encoder, prompt,
                                aligned[0], aligned[1], seed, out_path)

    started = time.monotonic()
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

    # Движок округлил размер вверх — возвращаем ровно то, что просили.
    try:
        crop_png(out_path, width, height)
    except (OSError, ValueError, zlib.error) as e:
        print(f"Предупреждение: не удалось подрезать до {width}x{height}: {e}",
              file=sys.stderr)

    print(f"\nГотово за {elapsed:.0f} с: {out_path}")


if __name__ == "__main__":
    main()
