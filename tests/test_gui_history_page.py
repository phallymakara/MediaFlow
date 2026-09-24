"""Tests for HistoryPage formatting, search filtering, and record management."""

import pytest

from app.database.models import DownloadRecord, DownloadStatus
from app.gui.history_page import filter_records, format_history_date


def test_format_history_date() -> None:
    """Verify ISO timestamp formatting to human readable date."""
    assert format_history_date(None) == "--"
    assert format_history_date("") == "--"

    formatted = format_history_date("2026-09-23T16:45:00+00:00")
    assert formatted.startswith("2026-09-23")


def test_filter_records_by_search_title() -> None:
    """Verify search filter matches video title case-insensitively."""
    records = [
        DownloadRecord(task_id="t1", url="https://yt.com/1", title="Python Programming Tutorial", platform="youtube", output_path="d/1.mp4"),
        DownloadRecord(task_id="t2", url="https://db.com/2", title="The Heiress Episode 12", platform="dramabox", output_path="d/2.mp4"),
        DownloadRecord(task_id="t3", url="https://tt.com/3", title="Viral Dance Video", platform="tiktok", output_path="d/3.mp4"),
    ]

    res = filter_records(records, search="python")
    assert len(res) == 1
    assert res[0].task_id == "t1"

    res_heiress = filter_records(records, search="HEIRESS")
    assert len(res_heiress) == 1
    assert res_heiress[0].task_id == "t2"


def test_filter_records_by_search_url() -> None:
    """Verify search filter matches URL substrings."""
    records = [
        DownloadRecord(task_id="t1", url="https://youtube.com/watch?v=abc", title="Video A", platform="youtube", output_path="d/1.mp4"),
        DownloadRecord(task_id="t2", url="https://dramabox.com/watch/123", title="Video B", platform="dramabox", output_path="d/2.mp4"),
    ]

    res = filter_records(records, search="dramabox.com")
    assert len(res) == 1
    assert res[0].task_id == "t2"


def test_filter_records_by_platform() -> None:
    """Verify platform filter isolates matching platform records."""
    records = [
        DownloadRecord(task_id="t1", url="https://yt.com/1", title="V1", platform="youtube", output_path="d/1.mp4"),
        DownloadRecord(task_id="t2", url="https://yt.com/2", title="V2", platform="youtube", output_path="d/2.mp4"),
        DownloadRecord(task_id="t3", url="https://db.com/3", title="V3", platform="dramabox", output_path="d/3.mp4"),
    ]

    res_all = filter_records(records, platform="All Platforms")
    assert len(res_all) == 3

    res_yt = filter_records(records, platform="YouTube")
    assert len(res_yt) == 2

    res_db = filter_records(records, platform="DramaBox")
    assert len(res_db) == 1
    assert res_db[0].task_id == "t3"


def test_filter_records_by_status() -> None:
    """Verify status filter correctly separates completed, failed, and cancelled tasks."""
    records = [
        DownloadRecord(task_id="t1", url="https://yt.com/1", title="V1", platform="youtube", output_path="d/1.mp4", status=DownloadStatus.COMPLETED),
        DownloadRecord(task_id="t2", url="https://yt.com/2", title="V2", platform="youtube", output_path="d/2.mp4", status=DownloadStatus.FAILED),
        DownloadRecord(task_id="t3", url="https://db.com/3", title="V3", platform="dramabox", output_path="d/3.mp4", status=DownloadStatus.CANCELLED),
    ]

    res_comp = filter_records(records, status="Completed")
    assert len(res_comp) == 1
    assert res_comp[0].task_id == "t1"

    res_failed = filter_records(records, status="Failed")
    assert len(res_failed) == 1
    assert res_failed[0].task_id == "t2"

    res_all = filter_records(records, status="All Status")
    assert len(res_all) == 3


def test_filter_records_combined() -> None:
    """Verify combined search, platform, and status filtering."""
    records = [
        DownloadRecord(task_id="t1", url="https://yt.com/1", title="React Tutorial", platform="youtube", output_path="d/1.mp4", status=DownloadStatus.COMPLETED),
        DownloadRecord(task_id="t2", url="https://yt.com/2", title="Python Tutorial", platform="youtube", output_path="d/2.mp4", status=DownloadStatus.COMPLETED),
        DownloadRecord(task_id="t3", url="https://yt.com/3", title="Python Guide", platform="youtube", output_path="d/3.mp4", status=DownloadStatus.FAILED),
        DownloadRecord(task_id="t4", url="https://db.com/4", title="Python Drama", platform="dramabox", output_path="d/4.mp4", status=DownloadStatus.COMPLETED),
    ]

    # Search for "python" on YouTube that is Completed
    res = filter_records(records, search="python", platform="YouTube", status="Completed")
    assert len(res) == 1
    assert res[0].task_id == "t2"


def test_history_page_table_rendering_and_interaction(tmp_path) -> None:
    """Verify HistoryPage fast table population, date & time formatting, and title display."""
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    from app.gui.history_page import HistoryPage

    app = QApplication.instance() or QApplication([])

    repo = MagicMock()
    records = [
        DownloadRecord(
            task_id="t1",
            url="https://youtube.com/watch?v=sample",
            title="Sample Downloaded Video",
            platform="youtube",
            output_path=str(tmp_path / "sample.mp4"),
            file_format="mp4",
            quality="1080p",
            downloaded_bytes=1024 * 1024 * 50,
            total_bytes=1024 * 1024 * 50,
            created_at="2026-09-24T10:15:30+00:00",
            status=DownloadStatus.COMPLETED,
        )
    ]
    repo.get_all.return_value = records

    page = HistoryPage(repository=repo)

    # Check headers
    assert page._table.columnCount() == 6
    assert page._table.horizontalHeaderItem(0).text() == "Title"
    assert page._table.horizontalHeaderItem(4).text() == "Date & Time"

    # Check row count
    assert page._table.rowCount() == 1

    # Check Title item
    title_item = page._table.item(0, 0)
    assert title_item is not None
    assert title_item.text() == "Sample Downloaded Video"
    assert "Sample Downloaded Video" in title_item.toolTip()

    # Check Date & Time item
    date_item = page._table.item(0, 4)
    assert date_item is not None
    assert "2026-09-24" in date_item.text()
    assert "10:15" in date_item.text()

    # Check double-click action
    page._play_file = MagicMock()
    page._on_group_cell_double_clicked(0, 0)
    # Double-click switches to detail view
    assert page._view_stack.currentIndex() == 1
    assert page._detail_table.rowCount() == 1


def test_grouping_and_drill_down_view(tmp_path) -> None:
    """Verify series grouping by title and date time, stats banner, and drill down."""
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    from app.gui.history_page import HistoryPage, extract_base_title, group_records

    assert extract_base_title("Sabse Bada Maker - Shorts - Ep 01") == "Sabse Bada Maker - Shorts"
    assert extract_base_title("The Heiress - Episode 12") == "The Heiress"
    assert extract_base_title("Normal Video") == "Normal Video"

    app = QApplication.instance() or QApplication([])

    repo = MagicMock()
    records = [
        DownloadRecord(
            task_id="ep1",
            url="https://youtube.com/watch?v=1",
            title="Sabse Bada Maker - Shorts - Ep 01",
            platform="youtube",
            output_path=str(tmp_path / "ep1.mp4"),
            file_format="mp4",
            quality="1080p",
            downloaded_bytes=1000,
            total_bytes=1000,
            created_at="2026-09-24T10:15:00+00:00",
            status=DownloadStatus.COMPLETED,
        ),
        DownloadRecord(
            task_id="ep2",
            url="https://youtube.com/watch?v=2",
            title="Sabse Bada Maker - Shorts - Ep 02",
            platform="youtube",
            output_path=str(tmp_path / "ep2.mp4"),
            file_format="mp4",
            quality="1080p",
            downloaded_bytes=1000,
            total_bytes=1000,
            created_at="2026-09-24T10:15:05+00:00",
            status=DownloadStatus.COMPLETED,
        ),
        DownloadRecord(
            task_id="ep3",
            url="https://youtube.com/watch?v=3",
            title="Sabse Bada Maker - Shorts - Ep 03",
            platform="youtube",
            output_path=str(tmp_path / "ep3.mp4"),
            file_format="mp4",
            quality="1080p",
            downloaded_bytes=0,
            total_bytes=1000,
            created_at="2026-09-24T10:15:10+00:00",
            status=DownloadStatus.FAILED,
        ),
    ]
    repo.get_all.return_value = records

    groups = group_records(records)
    assert len(groups) == 1
    assert groups[0].base_title == "Sabse Bada Maker - Shorts"
    assert groups[0].total_count == 3
    assert groups[0].completed_count == 2
    assert groups[0].failed_count == 1

    page = HistoryPage(repository=repo)
    # The 3 episodes are grouped into 1 clean row!
    assert page._table.rowCount() == 1
    assert "Sabse Bada Maker - Shorts" in page._table.item(0, 0).text()

    # Click on the group to drill down into the episode details
    page._show_group_details(groups[0])
    assert page._view_stack.currentIndex() == 1

    # Verify stats banner
    assert "3" in page._stat_total.text()
    assert "2" in page._stat_completed.text()
    assert "1" in page._stat_failed.text()

    # Verify detail table shows all 3 episodes
    assert page._detail_table.rowCount() == 3
    assert "Ep 01" in page._detail_table.item(0, 0).text()
    assert "Ep 02" in page._detail_table.item(1, 0).text()
    assert "Ep 03" in page._detail_table.item(2, 0).text()

    # Verify action column in detail table contains Folder and Delete only (NO Play button)
    from PySide6.QtWidgets import QPushButton
    action_widget = page._detail_table.cellWidget(0, 6)
    assert action_widget is not None
    action_buttons = action_widget.findChildren(QPushButton)
    btn_labels = [b.text() for b in action_buttons]
    assert "Play" not in btn_labels
    assert "Folder" in btn_labels
    assert "Delete" in btn_labels

    # Verify alternating colors are disabled for uniform solid selection
    assert page._table.alternatingRowColors() is False
    assert page._detail_table.alternatingRowColors() is False

    # Navigate back to groups
    page._navigate_back_to_groups()
    assert page._view_stack.currentIndex() == 0


