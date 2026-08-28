use clap::Parser;
use std::path::PathBuf;

#[derive(Parser, Debug)]
#[command(name = "gpic", about = "Генератор случайных картинок для рабочего стола")]
pub struct Args {
    /// Промпт; без него будет случайный
    #[arg(short, long)]
    pub prompt: Option<String>,

    /// Разрешение, например 2560x1440; без него — разрешение экрана
    #[arg(short, long, value_parser = parse_resolution)]
    pub resolution: Option<(u32, u32)>,

    /// Seed для воспроизведения конкретной картинки
    #[arg(short, long)]
    pub seed: Option<u32>,

    /// Путь или просто имя файла; без него — gpic-ГГГГММДД-ЧЧММСС.jpg
    pub file: Option<PathBuf>,
}

pub fn parse_resolution(s: &str) -> Result<(u32, u32), String> {
    let lower = s.to_ascii_lowercase();
    let (w, h) = lower
        .split_once('x')
        .ok_or_else(|| format!("ожидался формат ШИРИНАxВЫСОТА, получено «{s}»"))?;

    let parse_side = |v: &str, name: &str| -> Result<u32, String> {
        let n: u32 = v
            .parse()
            .map_err(|_| format!("{name} должна быть числом, получено «{v}»"))?;
        if n == 0 {
            return Err(format!("{name} должна быть больше нуля"));
        }
        Ok(n)
    };

    Ok((parse_side(w, "ширина")?, parse_side(h, "высота")?))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_valid_resolution() {
        assert_eq!(parse_resolution("1920x1200"), Ok((1920, 1200)));
        assert_eq!(parse_resolution("800x600"), Ok((800, 600)));
    }

    #[test]
    fn accepts_uppercase_separator() {
        assert_eq!(parse_resolution("2560X1440"), Ok((2560, 1440)));
    }

    #[test]
    fn rejects_garbage() {
        assert!(parse_resolution("abc").is_err());
        assert!(parse_resolution("1920*1200").is_err());
        assert!(parse_resolution("1920x").is_err());
        assert!(parse_resolution("x1200").is_err());
        assert!(parse_resolution("1920x1200x3").is_err());
    }

    #[test]
    fn rejects_zero_dimensions() {
        assert!(parse_resolution("0x1200").is_err());
        assert!(parse_resolution("1920x0").is_err());
    }

    #[test]
    fn cli_verifies() {
        use clap::CommandFactory;
        Args::command().debug_assert();
    }
}
