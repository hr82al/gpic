use std::path::Path;

pub const FALLBACK: (u32, u32) = (1920, 1200);

/// Первая строка файла `modes` — предпочитаемый режим выхода.
fn parse_first_mode(contents: &str) -> Option<(u32, u32)> {
    let line = contents.lines().next()?.trim();
    let (w, h) = line.split_once('x')?;
    Some((w.parse().ok()?, h.parse().ok()?))
}

/// Ищет первый подключённый выход в дереве вида /sys/class/drm.
fn detect_in(root: &Path) -> Option<(u32, u32)> {
    let mut outputs: Vec<_> = std::fs::read_dir(root)
        .ok()?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .collect();
    // Порядок read_dir не определён — сортируем ради воспроизводимости.
    outputs.sort();

    outputs.into_iter().find_map(|dir| {
        let status = std::fs::read_to_string(dir.join("status")).ok()?;
        if status.trim() != "connected" {
            return None;
        }
        let modes = std::fs::read_to_string(dir.join("modes")).ok()?;
        parse_first_mode(&modes)
    })
}

/// Разрешение подключённого монитора; при неудаче — FALLBACK.
///
/// Читаем sysfs, а не xrandr: на Wayland xrandr пуст, а sysfs работает
/// и не требует зависимостей.
pub fn detect() -> (u32, u32) {
    detect_in(Path::new("/sys/class/drm")).unwrap_or(FALLBACK)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn parses_first_mode_line() {
        let modes = "1920x1200\n1920x1080\n1600x1200\n";
        assert_eq!(parse_first_mode(modes), Some((1920, 1200)));
    }

    #[test]
    fn ignores_empty_modes_file() {
        assert_eq!(parse_first_mode(""), None);
        assert_eq!(parse_first_mode("\n"), None);
    }

    #[test]
    fn ignores_unparseable_mode() {
        assert_eq!(parse_first_mode("не режим\n"), None);
    }

    #[test]
    fn picks_connected_output_over_disconnected() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path();

        let dead = root.join("card0-DP-1");
        fs::create_dir_all(&dead).unwrap();
        fs::write(dead.join("status"), "disconnected\n").unwrap();
        fs::write(dead.join("modes"), "3840x2160\n").unwrap();

        let live = root.join("card0-HDMI-A-1");
        fs::create_dir_all(&live).unwrap();
        fs::write(live.join("status"), "connected\n").unwrap();
        fs::write(live.join("modes"), "1920x1200\n1280x1024\n").unwrap();

        assert_eq!(detect_in(root), Some((1920, 1200)));
    }

    #[test]
    fn returns_none_when_nothing_connected() {
        let dir = tempfile::tempdir().unwrap();
        let out = dir.path().join("card0-DP-1");
        fs::create_dir_all(&out).unwrap();
        fs::write(out.join("status"), "disconnected\n").unwrap();
        fs::write(out.join("modes"), "1024x768\n").unwrap();

        assert_eq!(detect_in(dir.path()), None);
    }

    #[test]
    fn detect_falls_back_on_missing_root() {
        assert_eq!(
            detect_in(Path::new("/nonexistent-drm-root")).unwrap_or(FALLBACK),
            FALLBACK
        );
    }
}
