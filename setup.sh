#!/usr/bin/env bash
# setup.sh — разворачивает gpic целиком: пакеты, движок, веса, лаунчер.
#
# Скрипт идемпотентен: повторный запуск пропускает уже сделанные шаги,
# так что прерванную загрузку можно продолжить, просто запустив снова.
#
# Всё тяжёлое (движок и веса) остаётся в build/ и models/, которые
# перечислены в .gitignore. Чтобы откатить установку целиком:
#     rm -rf build models ~/.local/bin/gpic

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD="$ROOT/build"
MODELS="$ROOT/models"
SRC="$BUILD/stable-diffusion.cpp"
LLAMA_SRC="$BUILD/llama.cpp"
LAUNCHER="$HOME/.local/bin/gpic"

# spirv-headers, glslang-dev и libshaderc-dev нужны именно для Vulkan-бэкенда:
# без них cmake падает на поиске SPIRV-Headers. Проверено на Debian 13.
PACKAGES=(
    libvulkan-dev glslc vulkan-tools
    spirv-headers spirv-tools glslang-dev libshaderc-dev
    cmake build-essential git curl
)

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m    %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- пакеты

install_packages() {
    local missing=()
    for pkg in "${PACKAGES[@]}"; do
        dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
    done
    if [ ${#missing[@]} -eq 0 ]; then
        say "Системные пакеты уже на месте"
        return
    fi
    say "Ставлю пакеты: ${missing[*]}"
    sudo apt-get update -qq
    sudo apt-get install -y "${missing[@]}"
}

# ----------------------------------------------------------------- движок

build_engine() {
    if [ -x "$BUILD/sd" ]; then
        say "Движок уже собран: $BUILD/sd"
        return
    fi

    mkdir -p "$BUILD"
    if [ ! -d "$SRC/.git" ]; then
        say "Клонирую stable-diffusion.cpp"
        git clone https://github.com/leejet/stable-diffusion.cpp "$SRC"
    fi

    # Подмодули клонируются на полную глубину намеренно. С --depth 1 git
    # тянет только вершину ветки, а закреплённый коммит ggml в такую
    # историю не попадает — получается «Unable to find current revision».
    if [ ! -f "$SRC/ggml/CMakeLists.txt" ]; then
        say "Подтягиваю подмодули (ggml, libwebp, libwebm)"
        git -C "$SRC" submodule update --init --recursive
    fi

    # Vulkan — основной путь: на встроенной Radeon он работает без ROCm,
    # который для gfx1103 официально не поддерживается.
    say "Собираю движок с Vulkan"
    if cmake -S "$SRC" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release -DSD_VULKAN=ON \
         && cmake --build "$SRC/build" --config Release -j"$(nproc)"; then
        :
    else
        warn "Сборка с Vulkan не удалась — пересобираю в режиме CPU."
        warn "Работать будет, но заметно медленнее."
        rm -rf "$SRC/build"
        cmake -S "$SRC" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release
        cmake --build "$SRC/build" --config Release -j"$(nproc)"
    fi

    # В свежих версиях бинарник называется sd-cli; в старых — sd.
    local built
    built="$(find "$SRC/build" \( -name sd-cli -o -name sd \) -type f -perm -u+x | head -1)"
    [ -n "$built" ] || { echo "Сборка прошла, но бинарник sd-cli не найден" >&2; exit 1; }
    cp "$built" "$BUILD/sd"
    say "Движок готов: $BUILD/sd"
}

# ------------------------------------------------------- модель-промптер

# Описания картинок придумывает маленькая языковая модель через llama.cpp.
# Без неё gpic работает по запасному списку из десятка описаний — то есть
# остаётся рабочим, но однообразным.
build_prompter() {
    if [ -x "$BUILD/llama-cli" ]; then
        say "Промптер уже собран: $BUILD/llama-cli"
        return
    fi

    mkdir -p "$BUILD"
    if [ ! -d "$LLAMA_SRC/.git" ]; then
        say "Клонирую llama.cpp"
        git clone https://github.com/ggml-org/llama.cpp "$LLAMA_SRC"
    fi

    say "Собираю llama.cpp с Vulkan"
    # LLAMA_CURL=OFF: скачивание моделей нам не нужно, а зависимость от
    # libcurl лишняя.
    if cmake -S "$LLAMA_SRC" -B "$LLAMA_SRC/build" -DCMAKE_BUILD_TYPE=Release \
             -DGGML_VULKAN=ON -DLLAMA_CURL=OFF \
         && cmake --build "$LLAMA_SRC/build" --config Release \
                  -j"$(nproc)" --target llama-cli; then
        :
    else
        warn "Сборка промптера с Vulkan не удалась — пробую режим CPU."
        rm -rf "$LLAMA_SRC/build"
        cmake -S "$LLAMA_SRC" -B "$LLAMA_SRC/build" -DCMAKE_BUILD_TYPE=Release \
              -DLLAMA_CURL=OFF
        cmake --build "$LLAMA_SRC/build" --config Release -j"$(nproc)" --target llama-cli
    fi

    local built
    built="$(find "$LLAMA_SRC/build" -name llama-cli -type f -perm -u+x | head -1)"
    if [ -z "$built" ]; then
        warn "llama-cli не собрался. gpic будет работать по запасному списку описаний."
        return
    fi
    cp "$built" "$BUILD/llama-cli"
    say "Промптер готов: $BUILD/llama-cli"
}

# ------------------------------------------------------------------- веса

# Один файл: имя, репозиторий, путь внутри репозитория.
# FLUX — не один файл, а четыре части одной модели: диффузионная модель,
# текстовый энкодер T5, CLIP-L и VAE-декодер. Без любой из них не запустится.
fetch() {
    local name="$1" repo="$2" path="$3"
    local dest="$MODELS/$name"
    if [ -s "$dest" ]; then
        say "Уже скачано: $name ($(du -h "$dest" | cut -f1))"
        return
    fi
    say "Качаю $name из $repo"
    # --continue-at позволяет продолжить прерванную загрузку.
    curl -L --fail --continue-at - --progress-bar \
        -o "$dest" "https://huggingface.co/$repo/resolve/main/$path"
    say "Готово: $name ($(du -h "$dest" | cut -f1))"
}

fetch_models() {
    mkdir -p "$MODELS"
    # Q8_0: пик памяти при генерации 1920x1200 — 17.4 ГБ из 27. Q5_K_S
    # обошёлся бы 11.1 ГБ при неотличимой картинке и том же времени, но
    # выбран более точный вес. Ключевое здесь не квантование, а флаги в
    # gpic.py (тайловый VAE и выгрузка энкодеров): без них любой вес
    # требовал 27 ГБ и ронял драйвер.
    fetch "flux1-schnell-Q8_0.gguf" "city96/FLUX.1-schnell-gguf" "flux1-schnell-Q8_0.gguf"
    fetch "t5xxl-Q8_0.gguf"          "second-state/FLUX.1-schnell-GGUF" "t5xxl-Q8_0.gguf"
    fetch "clip_l.safetensors"        "second-state/FLUX.1-schnell-GGUF" "clip_l.safetensors"
    fetch "ae.safetensors"            "second-state/FLUX.1-schnell-GGUF" "ae.safetensors"
    # Модель, придумывающая описания. Полтора миллиарда параметров: на
    # 0.5B заметно беднее фантазия, а генерация тридцати токенов на фоне
    # шестиминутной отрисовки картинки ничего не стоит.
    fetch "prompter.gguf" "Qwen/Qwen2.5-1.5B-Instruct-GGUF" "qwen2.5-1.5b-instruct-q4_k_m.gguf"
    # Быстрый режим (--fast): 1920x1216 за минуту против шести с половиной
    # у FLUX. Опасение, что модель, обученная на 512x512, начнёт дублировать
    # объекты в полном размере, замером не подтвердилось.
    fetch "sdxl-turbo-fp16.safetensors" "stabilityai/sdxl-turbo" "sd_xl_turbo_1.0_fp16.safetensors"
    say "Веса на месте, суммарно $(du -sh "$MODELS" | cut -f1)"
}

# --------------------------------------------------------------- лаунчер

install_launcher() {
    mkdir -p "$(dirname "$LAUNCHER")"
    cat > "$LAUNCHER" <<EOF
#!/bin/sh
# Лаунчер gpic — сгенерирован setup.sh, правь gpic.py вместо него.
exec python3 "$ROOT/gpic.py" "\$@"
EOF
    chmod +x "$LAUNCHER"
    say "Лаунчер установлен: $LAUNCHER"
    case ":$PATH:" in
        *":$(dirname "$LAUNCHER"):"*) ;;
        *) warn "$(dirname "$LAUNCHER") не в PATH — добавь его в ~/.bashrc" ;;
    esac
}

# ------------------------------------------------------------ проверка

smoke_test() {
    say "Контрольная генерация — засекаю время"
    local out="$ROOT/build/smoke.png"
    rm -f "$out"
    local started elapsed
    started="$(date +%s)"
    python3 "$ROOT/gpic.py" -r 512x320 -s 42 \
        -p "misty mountain lake at golden hour, landscape photography" "$out"
    elapsed=$(( $(date +%s) - started ))

    say "Контрольная картинка 512x320 готова за ${elapsed} с"
    # Время растёт быстрее числа пикселей: встроенная видеокарта упирается
    # в пропускную способность памяти. На эталонной машине 512x320 занимает
    # 29 с, а 1920x1200 — 387 с, то есть в 13 раз дольше при 14-кратном
    # росте площади. Этим отношением и пересчитываем.
    warn "Картинка в разрешении экрана займёт примерно $(( elapsed * 13 / 60 )) мин."
    warn "Проверить: gpic"
}

main() {
    install_packages
    build_engine
    build_prompter
    fetch_models
    install_launcher
    smoke_test
    say "Готово. Запускай: gpic"
}

main "$@"
