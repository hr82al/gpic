# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Состояние репозитория

`gpic` — новый Rust-бинарник (Cargo, edition 2024), созданный через `cargo new`. На момент написания в репозитории только `src/main.rs` с `Hello, world!`, нет коммитов, зависимостей, тестов и README. Архитектуры, которую стоило бы описывать, пока не существует — этот файл нужно дополнить, как только появится реальный код.

## Команды

```
cargo run                  # сборка и запуск
cargo build --release      # релизная сборка
cargo test                 # все тесты
cargo test <имя_теста>     # один тест (по подстроке имени)
cargo test -- --nocapture  # с выводом println! из тестов
cargo clippy               # линтер
cargo fmt                  # форматирование
```

## Замечания

- `edition = "2024"` требует Rust ≥ 1.85; в окружении стоит 1.97.
- Репозиторий лежит внутри дерева `/home/user/mr`, но является самостоятельным git-репозиторием, а не частью монорепо.
