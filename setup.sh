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
LAUNCHER="$HOME/.local/bin/gpic"

PACKAGES=(libvulkan-dev glslc vulkan-tools cmake build-essential git curl)

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
    if [ ! -d "$SRC" ]; then
        say "Клонирую stable-diffusion.cpp"
        git clone --recursive --depth 1 \
            https://github.com/leejet/stable-diffusion.cpp "$SRC"
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

    local built
    built="$(find "$SRC/build" -name sd -type f -perm -u+x | head -1)"
    [ -n "$built" ] || { echo "Сборка прошла, но бинарник sd не найден" >&2; exit 1; }
    cp "$built" "$BUILD/sd"
    say "Движок готов: $BUILD/sd"
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
    # Q5_K_S — компромисс: заметно лучше Q4 по качеству и при этом вместе
    # с энкодером укладывается в доступную GPU-память (4 ГБ VRAM + 13.9 ГБ GTT).
    fetch "flux1-schnell-Q5_K_S.gguf" "city96/FLUX.1-schnell-gguf" "flux1-schnell-Q5_K_S.gguf"
    fetch "t5xxl-Q5_0.gguf"           "second-state/FLUX.1-schnell-GGUF" "t5xxl-Q5_0.gguf"
    fetch "clip_l.safetensors"        "second-state/FLUX.1-schnell-GGUF" "clip_l.safetensors"
    fetch "ae.safetensors"            "second-state/FLUX.1-schnell-GGUF" "ae.safetensors"
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
    python3 "$ROOT/gpic.py" -r 1024x640 -s 42 \
        -p "misty mountain lake at golden hour, landscape photography" "$out"
    elapsed=$(( $(date +%s) - started ))
    say "Контрольная картинка 1024x640 сгенерирована за ${elapsed} с"
    warn "Экранное разрешение содержит примерно вдвое больше пикселей,"
    warn "так что реальная генерация займёт ориентировочно $(( elapsed * 2 )) с."
}

main() {
    install_packages
    build_engine
    fetch_models
    install_launcher
    smoke_test
    say "Готово. Запускай: gpic"
}

main "$@"
