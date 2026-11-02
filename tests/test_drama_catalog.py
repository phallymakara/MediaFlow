"""Tests for drama catalog service and explorer models."""

import pytest
from app.services.drama_catalog_service import (
    DramaCatalogItem,
    DramaCatalogService,
    DramaEpisodeItem,
)


def test_drama_catalog_item_model() -> None:
    item = DramaCatalogItem(
        id="test_123",
        title="Test Short Drama",
        platform="TikTok",
        url="https://www.tiktok.com/shortdrama/episode/test_123",
        cover_url="https://example.com/cover.jpg",
        episodes_count=45,
        description="A dramatic story about a CEO and a student.",
        tags=["Romance", "Drama"],
        author="destinystonedrama",
    )
    assert item.id == "test_123"
    assert item.title == "Test Short Drama"
    assert item.platform == "TikTok"
    assert item.episodes_count == 45
    assert len(item.tags) == 2


def test_drama_catalog_service_fetch_tiktok() -> None:
    service = DramaCatalogService()
    items = service.fetch_tiktok_catalog()
    assert len(items) >= 1
    assert items[0].platform == "TikTok"
    assert "tiktok.com" in items[0].url


def test_drama_catalog_service_fetch_reelshort() -> None:
    service = DramaCatalogService()
    items = service.fetch_reelshort_catalog()
    assert len(items) >= 1
    assert items[0].platform == "ReelShort"
    assert "reelshort.com" in items[0].url


def test_cover_cache_helpers() -> None:
    sample_url = "https://example.com/test_cover_123.jpg"
    data = b"dummy_image_bytes_content_for_testing"
    saved = DramaCatalogService.save_cached_cover(sample_url, data)
    assert saved is not None
    assert saved.is_file()

    retrieved = DramaCatalogService.get_cached_cover_path(sample_url)
    assert retrieved is not None
    assert retrieved == saved


def test_drama_card_widget_preview_only() -> None:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from app.gui.drama_page import DramaCardWidget

    item = DramaCatalogItem(
        id="sample_001",
        title="Sample Drama",
        platform="TikTok",
        url="https://www.tiktok.com/shortdrama/episode/sample_001",
        cover_url="",
        episodes_count=20,
        description="Sample synopsis",
    )
    card = DramaCardWidget(item)
    emitted = []
    card.preview_clicked.connect(lambda it: emitted.append(it))

    # Trigger preview through view button
    for child in card.findChildren(object):
        if getattr(child, "text", None) and child.text() == "View Episodes":
            child.click()
            break

    assert len(emitted) == 1
    assert emitted[0].id == "sample_001"


def test_short_drama_page_segmented_filter() -> None:
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from app.gui.drama_page import ShortDramaPage

    with patch.object(ShortDramaPage, "refresh_catalog"):
        page = ShortDramaPage()
        assert page._active_filter == "All"
        # Switch filter to TikTok
        page._set_platform_filter("TikTok")
        assert page._active_filter == "TikTok"
        page._set_platform_filter("DramaBox")
        assert page._active_filter == "DramaBox"
        page.close()


def test_drama_card_no_nested_containers() -> None:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from app.gui.drama_page import DramaCardWidget

    item = DramaCatalogItem(
        id="sample_002",
        title="Sample Non Nested",
        platform="TikTok",
        url="https://www.tiktok.com/shortdrama/episode/sample_002",
        cover_url="",
        episodes_count=35,
        description="Synopsis",
    )
    card = DramaCardWidget(item)
    layout = card.layout()
    sub_layouts = [layout.itemAt(i).layout() for i in range(layout.count()) if layout.itemAt(i).layout() is not None]
    assert len(sub_layouts) == 0  # Direct layout, no nested containers


def test_responsive_grid_column_calculation() -> None:
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from app.gui.drama_page import ShortDramaPage

    with patch.object(ShortDramaPage, "refresh_catalog"):
        page = ShortDramaPage()
        with patch.object(page._scroll.viewport(), "width", return_value=450):
            assert page._calculate_columns() == 2
        with patch.object(page._scroll.viewport(), "width", return_value=850):
            assert page._calculate_columns() == 3
        with patch.object(page._scroll.viewport(), "width", return_value=1100):
            assert page._calculate_columns() == 5
        with patch.object(page._scroll.viewport(), "width", return_value=1600):
            assert page._calculate_columns() == 7
        page.close()

