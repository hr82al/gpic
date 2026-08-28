use anyhow::{Context, Result};
use image::{DynamicImage, ImageFormat};
use std::path::{Path, PathBuf};

/// Метка времени вида 20260828-153012 в локальной зоне.
pub fn timestamp() -> String {
    chrono::Local::now().format("%Y%m%d-%H%M%S").to_string()
}

/// Голое имя остаётся относительным, то есть попадает в текущий каталог.
pub fn resolve_path(arg: Option<PathBuf>, now: &str) -> PathBuf {
    arg.unwrap_or_else(|| PathBuf::from(format!("gpic-{now}.jpg")))
}

/// Формат по расширению из ограниченного набора спецификации
/// (`.png`, `.jpg`/`.jpeg`); всё незнакомое и безрасширенное — JPEG.
/// Не используем `ImageFormat::from_extension` — он распознаёт куда
/// больше форматов, чем есть кодировщиков, и это всплывает только
/// после полной генерации картинки.
fn format_for(path: &Path) -> ImageFormat {
    match path
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| e.to_ascii_lowercase())
        .as_deref()
    {
        Some("png") => ImageFormat::Png,
        _ => ImageFormat::Jpeg,
    }
}

pub fn save(img: &DynamicImage, path: &Path) -> Result<()> {
    let format = format_for(path);
    // JPEG не умеет альфу — приводим к RGB8, иначе запись падает.
    let to_write = if format == ImageFormat::Jpeg {
        DynamicImage::ImageRgb8(img.to_rgb8())
    } else {
        img.clone()
    };
    to_write
        .save_with_format(path, format)
        .with_context(|| format!("не удалось записать файл {}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn uses_timestamp_when_no_file_given() {
        let p = resolve_path(None, "20260828-153012");
        assert_eq!(p, PathBuf::from("gpic-20260828-153012.jpg"));
    }

    #[test]
    fn keeps_bare_name_relative_to_cwd() {
        let p = resolve_path(Some(PathBuf::from("wall.png")), "20260828-153012");
        assert_eq!(p, PathBuf::from("wall.png"));
        assert!(p.is_relative());
    }

    #[test]
    fn keeps_explicit_path_untouched() {
        let p = resolve_path(Some(PathBuf::from("/tmp/pics/a.jpg")), "20260828-153012");
        assert_eq!(p, PathBuf::from("/tmp/pics/a.jpg"));
    }

    #[test]
    fn chooses_format_from_extension() {
        assert_eq!(format_for(Path::new("a.png")), ImageFormat::Png);
        assert_eq!(format_for(Path::new("a.jpg")), ImageFormat::Jpeg);
        assert_eq!(format_for(Path::new("a.JPEG")), ImageFormat::Jpeg);
    }

    #[test]
    fn falls_back_to_jpeg_for_unknown_extension() {
        assert_eq!(format_for(Path::new("a.xyz")), ImageFormat::Jpeg);
        assert_eq!(format_for(Path::new("noext")), ImageFormat::Jpeg);
    }

    #[test]
    fn falls_back_to_jpeg_for_extensions_outside_the_whitelist() {
        // `ImageFormat::from_extension` узнало бы оба этих расширения,
        // но спецификация ограничивает набор до png/jpg/jpeg — всё
        // остальное должно тихо стать JPEG, а не падать после генерации.
        assert_eq!(format_for(Path::new("a.dds")), ImageFormat::Jpeg);
        assert_eq!(format_for(Path::new("a.webp")), ImageFormat::Jpeg);
    }

    #[test]
    fn timestamp_has_expected_shape() {
        let t = timestamp();
        assert_eq!(t.len(), 15, "получено «{t}»");
        assert_eq!(t.as_bytes()[8], b'-');
        assert!(t.chars().filter(|c| c.is_ascii_digit()).count() == 14);
    }

    #[test]
    fn writes_a_readable_file() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("out.png");
        let img = DynamicImage::ImageRgb8(image::RgbImage::new(8, 6));
        save(&img, &path).unwrap();

        let reread = image::open(&path).unwrap();
        assert_eq!((reread.width(), reread.height()), (8, 6));
    }

    #[test]
    fn reports_missing_directory_clearly() {
        let img = DynamicImage::ImageRgb8(image::RgbImage::new(4, 4));
        let err = save(&img, Path::new("/nonexistent-dir-xyz/out.jpg")).unwrap_err();
        assert!(
            format!("{err:#}").contains("nonexistent-dir-xyz"),
            "ошибка не называет путь: {err:#}"
        );
    }
}
