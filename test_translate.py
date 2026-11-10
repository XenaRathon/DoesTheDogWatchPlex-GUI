import os
import importlib
from pathlib import Path
from unittest import mock

def test_translate_cache_path(tmp_path):
    # Test setting DTDD_DATA_DIR
    temp_dir = str(tmp_path / "custom_data")
    os.makedirs(temp_dir)

    with mock.patch.dict(os.environ, {"DTDD_DATA_DIR": temp_dir}):
        # Reload translate module to reflect the new env var
        import translate
        importlib.reload(translate)

        expected_path = Path(temp_dir) / ".cache" / "translations.json"
        assert translate.TRANSLATION_CACHE == expected_path

def test_translate_cache_path_default():
    # Test without DTDD_DATA_DIR
    with mock.patch.dict(os.environ, clear=True):
        if "DTDD_DATA_DIR" in os.environ:
            del os.environ["DTDD_DATA_DIR"]

        import translate
        importlib.reload(translate)

        expected_path = Path(translate.__file__).parent / ".cache" / "translations.json"
        assert translate.TRANSLATION_CACHE == expected_path
