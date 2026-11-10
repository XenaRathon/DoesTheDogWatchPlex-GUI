"""
Optional translation support for topic names.
Uses Google Translate via deep-translator with local file caching.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

if os.environ.get("DTDD_DATA_DIR"):
    CACHE_DIR = Path(os.environ["DTDD_DATA_DIR"]) / ".cache"
else:
    print("Warning: DTDD_DATA_DIR not set, falling back to code directory for translation cache.")
    CACHE_DIR = Path(__file__).parent / ".cache"
TRANSLATION_CACHE = CACHE_DIR / "translations.json"


def _load_cache() -> dict:
    if TRANSLATION_CACHE.exists():
        try:
            return json.loads(TRANSLATION_CACHE.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    return {}


def _save_cache(cache: dict):
    TRANSLATION_CACHE.parent.mkdir(exist_ok=True)
    TRANSLATION_CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def translate_topics(topics: list[str], target_lang: str) -> dict[str, str]:
    """Translate a list of topic strings to the target language.

    Returns a dict mapping original English topic name -> translated string.
    Results are cached locally so each topic is only translated once per language.
    """
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        print("Warning: deep-translator not installed. Run: pip install deep-translator")
        print("Falling back to English.")
        return {t: t for t in topics}

    cache = _load_cache()
    lang_cache = cache.get(target_lang, {})
    result = {}
    to_translate = []

    for topic in topics:
        if topic in lang_cache:
            result[topic] = lang_cache[topic]
        else:
            to_translate.append(topic)

    if to_translate:
        try:
            translator = GoogleTranslator(source="en", target=target_lang)
            translated = translator.translate_batch(to_translate)
            for original, translated_text in zip(to_translate, translated):
                lang_cache[original] = translated_text or original
                result[original] = lang_cache[original]
            cache[target_lang] = lang_cache
            _save_cache(cache)
        except Exception as e:
            print(f"Warning: Translation failed ({e}). Falling back to English.")
            for topic in to_translate:
                result[topic] = topic

    return result
