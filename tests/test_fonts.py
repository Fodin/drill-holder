"""Тесты подбора шрифта — чистый слой, без FreeCAD."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import drillholder.fonts as fonts  # noqa: E402
from drillholder.fonts import resolve_font  # noqa: E402


def _clear_cache():
    fonts._cache.clear()


def test_preferred_font_used_when_exists(tmp_path):
    _clear_cache()
    f = tmp_path / "my.ttf"
    f.write_bytes(b"\x00\x01")  # содержимое не важно — проверяется только существование пути
    assert resolve_font(str(f)) == str(f)


def test_falls_back_when_preferred_missing(monkeypatch, tmp_path):
    # Заданный шрифт не существует → берём первый существующий из FALLBACK_FONTS.
    _clear_cache()
    fb = tmp_path / "fallback.ttf"
    fb.write_bytes(b"\x00")
    monkeypatch.setattr(fonts, "FALLBACK_FONTS", [str(tmp_path / "nope.ttf"), str(fb)])
    monkeypatch.setattr(fonts, "FONT_DIRS", [])
    assert resolve_font("/definitely/missing.ttf") == str(fb)


def test_scans_dirs_as_last_resort(monkeypatch, tmp_path):
    _clear_cache()
    (tmp_path / "z.otf").write_bytes(b"\x00")
    (tmp_path / "a.ttf").write_bytes(b"\x00")
    monkeypatch.setattr(fonts, "FALLBACK_FONTS", [])
    monkeypatch.setattr(fonts, "FONT_DIRS", [str(tmp_path)])
    # Детерминированно — первый по сортировке имени.
    assert resolve_font("") == str(tmp_path / "a.ttf")


def test_returns_none_when_nothing_found(monkeypatch):
    _clear_cache()
    monkeypatch.setattr(fonts, "FALLBACK_FONTS", [])
    monkeypatch.setattr(fonts, "FONT_DIRS", [])
    assert resolve_font("") is None
