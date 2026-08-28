mod cli;
mod output;
mod prompt;
mod provider;
mod resize;
mod screen;

use anyhow::Result;
use clap::Parser;
use rand::prelude::*;

fn main() {
    if let Err(e) = run() {
        eprintln!("Ошибка: {e:#}");
        std::process::exit(1);
    }
}

fn run() -> Result<()> {
    let args = cli::Args::parse();
    let mut rng = rand::rng();

    let (width, height) = args.resolution.unwrap_or_else(screen::detect);
    let text = args.prompt.unwrap_or_else(|| prompt::random(&mut rng));
    // Одинаковый seed возвращает закешированную картинку, поэтому
    // без явного значения он обязан быть случайным. Сервис принимает
    // seed не больше i32::MAX, поэтому генерируем в этом диапазоне.
    let seed = args
        .seed
        .unwrap_or_else(|| rng.random_range(0..=2_147_483_647));
    let path = output::resolve_path(args.file, &output::timestamp());

    println!("Промпт: {text}");
    println!("Размер: {width}x{height}, seed: {seed}");
    println!("Генерация занимает около 40 секунд…");

    let (img, used_seed) = provider::fetch(&text, width, height, seed)?;
    if used_seed != seed {
        println!("Повтор удался с seed: {used_seed}");
    }
    println!("Получено {}x{}, масштабирую…", img.width(), img.height());

    let scaled = resize::to(img, width, height);
    output::save(&scaled, &path)?;

    println!("Готово: {}", path.display());
    Ok(())
}
