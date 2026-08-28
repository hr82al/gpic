use image::DynamicImage;
use image::imageops::FilterType;

/// Приводит картинку ровно к w×h. Пропорция уже задана запросом к API,
/// поэтому растягивания не происходит и кадрировать нечего.
pub fn to(img: DynamicImage, w: u32, h: u32) -> DynamicImage {
    if img.width() == w && img.height() == h {
        return img;
    }
    img.resize_exact(w, h, FilterType::Lanczos3)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample(w: u32, h: u32) -> DynamicImage {
        DynamicImage::ImageRgb8(image::RgbImage::new(w, h))
    }

    #[test]
    fn enlarges_to_exact_size() {
        let out = to(sample(971, 607), 1920, 1200);
        assert_eq!((out.width(), out.height()), (1920, 1200));
    }

    #[test]
    fn shrinks_to_exact_size() {
        let out = to(sample(1024, 576), 800, 600);
        assert_eq!((out.width(), out.height()), (800, 600));
    }

    #[test]
    fn keeps_identical_size() {
        let out = to(sample(640, 480), 640, 480);
        assert_eq!((out.width(), out.height()), (640, 480));
    }
}
