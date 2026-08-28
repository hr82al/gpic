use anyhow::{Context, Result, bail};
use image::DynamicImage;
use reqwest::Url;
use std::time::Duration;

const BASE: &str = "https://image.pollinations.ai/";
const TIMEOUT: Duration = Duration::from_secs(120);

fn build_url(prompt: &str, w: u32, h: u32, seed: u32) -> Result<Url> {
    let mut url = Url::parse(BASE).context("некорректный базовый URL")?;
    url.path_segments_mut()
        .map_err(|_| anyhow::anyhow!("базовый URL не поддерживает сегменты пути"))?
        .push("prompt")
        .push(prompt);
    url.query_pairs_mut()
        .append_pair("width", &w.to_string())
        .append_pair("height", &h.to_string())
        .append_pair("seed", &seed.to_string())
        .append_pair("nologo", "true");
    Ok(url)
}

fn get_bytes(client: &reqwest::blocking::Client, url: Url) -> Result<Vec<u8>> {
    let response = client.get(url).send().context("сеть недоступна")?;
    let status = response.status();
    if !status.is_success() {
        let body = response.text().unwrap_or_default();
        let head: String = body.chars().take(200).collect();
        bail!("сервис ответил {status}: {head}");
    }
    Ok(response
        .bytes()
        .context("не удалось прочитать ответ")?
        .to_vec())
}

/// Запрашивает картинку. Пропорция соблюдается сервисом, абсолютный
/// размер — нет: ответ приходит с бюджетом около 0.59 Мп.
///
/// Прокси настраивать не нужно: reqwest с фичей system-proxy сам читает
/// HTTP_PROXY и HTTPS_PROXY из окружения.
pub fn fetch(prompt: &str, w: u32, h: u32, seed: u32) -> Result<DynamicImage> {
    let client = reqwest::blocking::Client::builder()
        .timeout(TIMEOUT)
        .build()
        .context("не удалось создать HTTP-клиент")?;

    let bytes = match get_bytes(&client, build_url(prompt, w, h, seed)?) {
        Ok(b) => b,
        Err(first) => {
            // Сервис периодически залипает. Повторяем с другим seed:
            // это заодно обходит возможный застрявший кеш.
            eprintln!("Первая попытка не удалась ({first:#}). Повторяю…");
            let retry_seed = seed.wrapping_add(1);
            get_bytes(&client, build_url(prompt, w, h, retry_seed)?)
                .with_context(|| format!("повтор тоже не удался (первая ошибка: {first:#})"))?
        }
    };

    image::load_from_memory(&bytes).context("ответ сервиса не является картинкой")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_url_with_all_parameters() {
        let url = build_url("mountain lake", 1920, 1200, 42).unwrap();
        assert_eq!(url.path(), "/prompt/mountain%20lake");

        let q: std::collections::HashMap<_, _> = url.query_pairs().into_owned().collect();
        assert_eq!(q["width"], "1920");
        assert_eq!(q["height"], "1200");
        assert_eq!(q["seed"], "42");
        assert_eq!(q["nologo"], "true");
    }

    #[test]
    fn percent_encodes_non_ascii_prompt() {
        let url = build_url("ночной город", 800, 600, 1).unwrap();
        assert!(
            url.as_str()
                .starts_with("https://image.pollinations.ai/prompt/%D0%BD")
        );
        assert!(!url.as_str().contains(' '));
    }

    #[test]
    fn encodes_slashes_inside_the_prompt() {
        // Слеш в промпте не должен создавать лишний сегмент пути.
        let url = build_url("a/b", 800, 600, 1).unwrap();
        assert_eq!(url.path(), "/prompt/a%2Fb");
    }

    /// Настоящий сетевой запрос. Запускать вручную:
    /// cargo test -- --ignored provider::tests::fetches_a_real_image
    #[test]
    #[ignore]
    fn fetches_a_real_image() {
        let img = fetch("quiet mountain lake", 1920, 1200, 12345).unwrap();
        assert!(img.width() > 100 && img.height() > 100);
        // Сервис держит пропорцию, а не абсолютный размер.
        let ratio = img.width() as f64 / img.height() as f64;
        assert!((ratio - 1920.0 / 1200.0).abs() < 0.02, "пропорция {ratio}");
    }
}
