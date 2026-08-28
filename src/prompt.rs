use rand::prelude::*;

const SUBJECTS: &[&str] = &[
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
];

const LIGHT: &[&str] = &[
    "golden hour",
    "blue hour",
    "soft morning fog",
    "dramatic sunset",
    "overcast diffused light",
    "clear starry night",
    "low winter sun",
    "after the rain",
];

const STYLES: &[&str] = &[
    "landscape photography, sharp detail",
    "cinematic wide shot",
    "painterly, rich colors",
    "minimalist composition",
    "high dynamic range photograph",
    "serene and atmospheric",
];

/// Собирает промпт из трёх независимых списков — сотни комбинаций
/// из компактного кода.
pub fn random(rng: &mut impl Rng) -> String {
    let subject = SUBJECTS.choose(rng).expect("SUBJECTS не пуст");
    let light = LIGHT.choose(rng).expect("LIGHT не пуст");
    let style = STYLES.choose(rng).expect("STYLES не пуст");
    format!("{subject}, {light}, {style}, beautiful wallpaper")
}

#[cfg(test)]
mod tests {
    use super::*;
    use rand::rngs::StdRng;

    #[test]
    fn is_deterministic_for_a_fixed_seed() {
        let a = random(&mut StdRng::seed_from_u64(7));
        let b = random(&mut StdRng::seed_from_u64(7));
        assert_eq!(a, b);
    }

    #[test]
    fn is_not_empty() {
        let p = random(&mut StdRng::seed_from_u64(1));
        assert!(!p.trim().is_empty());
    }

    #[test]
    fn varies_across_seeds() {
        let variants: std::collections::HashSet<String> =
            (0..50).map(|s| random(&mut StdRng::seed_from_u64(s))).collect();
        assert!(variants.len() > 10, "получено всего {} вариантов", variants.len());
    }

    #[test]
    fn all_lists_are_non_empty() {
        assert!(!SUBJECTS.is_empty());
        assert!(!LIGHT.is_empty());
        assert!(!STYLES.is_empty());
    }
}
