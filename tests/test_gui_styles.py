"""Tests for GUI styles, theme tokens, and native asset resolution."""

import pytest
from PySide6.QtGui import QImage

from app.gui.assets import create_vector_image, get_logo_image
from app.gui.styles import COLORS, get_application_stylesheet


def test_theme_colors_integrity() -> None:
    """Verify theme color tokens are valid hex color values."""
    for field_name in (
        "bg_window",
        "bg_surface",
        "border_subtle",
        "border_focus",
        "accent_primary",
        "text_primary",
        "status_success",
        "status_danger",
    ):
        val = getattr(COLORS, field_name)
        assert val.startswith("#"), f"{field_name} must be a valid hex color starting with #"
        assert len(val) in (4, 7), f"{field_name} must be a valid 3 or 6 digit hex color"


def test_get_application_stylesheet() -> None:
    """Verify complete application stylesheet generation."""
    qss = get_application_stylesheet()
    assert isinstance(qss, str)
    assert "QMainWindow" in qss
    assert "QLineEdit" in qss
    assert "QPushButton" in qss
    assert "QTableWidget" in qss
    assert "QProgressBar" in qss
    assert "box-shadow" not in qss


def test_assets_logo_image() -> None:
    """Verify logo image generation with clean dimensions and non-null status."""
    image = get_logo_image(size=64)
    assert isinstance(image, QImage)
    assert not image.isNull()
    assert image.width() == 64
    assert image.height() == 64


def test_create_vector_images() -> None:
    """Verify programmatic vector icon rendering for navigation and table actions."""
    icon_names = [
        "downloader",
        "history",
        "settings",
        "license",
        "folder",
        "play",
        "cancel",
        "retry",
    ]

    for name in icon_names:
        image = create_vector_image(name, size=24)
        assert isinstance(image, QImage), f"Image {name} must return a QImage"
        assert not image.isNull(), f"Image {name} must not be null"
        assert image.width() == 24
        assert image.height() == 24
