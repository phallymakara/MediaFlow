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
