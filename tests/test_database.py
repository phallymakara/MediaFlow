"""Tests for SQLite persistence layer."""

import concurrent.futures
import pytest
from app.database.database import DatabaseManager
from app.database.models import DownloadRecord, DownloadStatus
from app.database.repository import DownloadRepository, SettingsRepository


@pytest.fixture
def db_manager() -> DatabaseManager:
    """Fixture providing an isolated in-memory DatabaseManager."""
    return DatabaseManager(db_path=":memory:")


@pytest.fixture
def download_repo(db_manager: DatabaseManager) -> DownloadRepository:
    """Fixture providing a DownloadRepository connected to in-memory database."""
    return DownloadRepository(db_manager)


@pytest.fixture
def settings_repo(db_manager: DatabaseManager) -> SettingsRepository:
    """Fixture providing a SettingsRepository connected to in-memory database."""
    return SettingsRepository(db_manager)


def test_database_init_creates_tables(db_manager: DatabaseManager) -> None:
    """Verify DatabaseManager schema initialization creates tables and indexes."""
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row["name"] for row in cursor.fetchall()]

        assert "downloads" in tables
        assert "settings" in tables


def test_download_repository_add_and_get(download_repo: DownloadRepository) -> None:
    """Verify insertion and retrieval of DownloadRecord."""
    record = DownloadRecord(
        task_id="test-task-1",
        url="https://youtube.com/watch?v=example1",
        title="Example Video Title",
        platform="YouTube",
        output_path="/downloads/example.mp4",
        status=DownloadStatus.QUEUED,
        quality="1080p",
        file_format="mp4",
    )

    saved = download_repo.add(record)
    assert saved.id is not None
    assert saved.id > 0

    retrieved = download_repo.get_by_id("test-task-1")
    assert retrieved is not None
    assert retrieved.task_id == "test-task-1"
    assert retrieved.title == "Example Video Title"
    assert retrieved.status == DownloadStatus.QUEUED
    assert retrieved.platform == "YouTube"


def test_download_repository_update_progress(download_repo: DownloadRepository) -> None:
    """Verify byte progress updates."""
    record = DownloadRecord(
        task_id="test-task-2",
        url="https://tiktok.com/@user/video/1",
        title="TikTok Dance",
        platform="TikTok",
        output_path="/downloads/tiktok.mp4",
    )
    download_repo.add(record)

    success = download_repo.update_progress("test-task-2", downloaded_bytes=512000, total_bytes=1024000)
    assert success is True

    updated = download_repo.get_by_id("test-task-2")
    assert updated is not None
    assert updated.downloaded_bytes == 512000
    assert updated.total_bytes == 1024000


def test_download_repository_update_status(download_repo: DownloadRepository) -> None:
    """Verify task status and error message updates."""
    record = DownloadRecord(
        task_id="test-task-3",
        url="https://instagram.com/reel/123",
        title="Instagram Reel",
        platform="Instagram",
        output_path="/downloads/reel.mp4",
    )
    download_repo.add(record)

    # Transition to DOWNLOADING
    assert download_repo.update_status("test-task-3", DownloadStatus.DOWNLOADING) is True
    updated = download_repo.get_by_id("test-task-3")
    assert updated is not None
    assert updated.status == DownloadStatus.DOWNLOADING

    # Transition to FAILED with error
    assert download_repo.update_status("test-task-3", DownloadStatus.FAILED, error_message="Network timeout") is True
    failed = download_repo.get_by_id("test-task-3")
    assert failed is not None
    assert failed.status == DownloadStatus.FAILED
    assert failed.error_message == "Network timeout"


def test_download_repository_search_and_filter(download_repo: DownloadRepository) -> None:
    """Verify history filtering by status and title search."""
    download_repo.add(
        DownloadRecord(
            task_id="task-yt-1",
            url="https://youtube.com/watch?v=1",
            title="Cat Playing Piano",
            platform="YouTube",
            output_path="/downloads/cat.mp4",
            status=DownloadStatus.COMPLETED,
        )
    )
    download_repo.add(
        DownloadRecord(
            task_id="task-yt-2",
            url="https://youtube.com/watch?v=2",
            title="Dog Agility Training",
            platform="YouTube",
            output_path="/downloads/dog.mp4",
            status=DownloadStatus.FAILED,
        )
    )
    download_repo.add(
        DownloadRecord(
            task_id="task-db-1",
            url="https://dramabox.com/drama/1",
            title="The Billionaire Cat",
            platform="DramaBox",
            output_path="/downloads/drama.mp4",
            status=DownloadStatus.COMPLETED,
        )
    )

    # Search keyword "Cat"
    cat_results = download_repo.get_all(search="Cat")
    assert len(cat_results) == 2
    assert all("Cat" in r.title for r in cat_results)

    # Filter status COMPLETED
    completed_results = download_repo.get_all(status=DownloadStatus.COMPLETED)
    assert len(completed_results) == 2
    assert all(r.status == DownloadStatus.COMPLETED for r in completed_results)

    # Combined filter
    completed_cat = download_repo.get_all(status=DownloadStatus.COMPLETED, search="Piano")
    assert len(completed_cat) == 1
    assert completed_cat[0].title == "Cat Playing Piano"


def test_download_repository_delete_and_clear(download_repo: DownloadRepository) -> None:
    """Verify single deletion and bulk history cleanup."""
    download_repo.add(
        DownloadRecord(
            task_id="del-1",
            url="https://test.com/1",
            title="Item 1",
            platform="Direct",
            output_path="/downloads/1.mp4",
            status=DownloadStatus.COMPLETED,
        )
    )
    download_repo.add(
        DownloadRecord(
            task_id="del-2",
            url="https://test.com/2",
            title="Item 2",
            platform="Direct",
            output_path="/downloads/2.mp4",
            status=DownloadStatus.QUEUED,
        )
    )

    # Delete single item
    assert download_repo.delete("del-1") is True
    assert download_repo.get_by_id("del-1") is None

    # Clear history should not remove active queued items
    deleted_count = download_repo.clear_history()
    assert deleted_count == 0
    assert download_repo.get_by_id("del-2") is not None


def test_settings_repository_crud(settings_repo: SettingsRepository) -> None:
    """Verify setting, reading, and updating configuration values."""
    assert settings_repo.get("download_dir", default="/default") == "/default"

    # Set new value
    assert settings_repo.set("download_dir", "C:\\Custom\\Downloads") is True
    assert settings_repo.get("download_dir") == "C:\\Custom\\Downloads"

    # Update existing value
    assert settings_repo.set("download_dir", "D:\\NewLocation") is True
    assert settings_repo.get("download_dir") == "D:\\NewLocation"


def test_concurrent_database_access(db_manager: DatabaseManager) -> None:
    """Verify thread-safe concurrent writes to the database."""
    repo = DownloadRepository(db_manager)

    def worker_insert(index: int) -> str:
        task_id = f"concurrent-task-{index}"
        record = DownloadRecord(
            task_id=task_id,
            url=f"https://example.com/{index}",
            title=f"Parallel Video {index}",
            platform="Test",
            output_path=f"/downloads/video_{index}.mp4",
            status=DownloadStatus.QUEUED,
        )
        repo.add(record)
        repo.update_progress(task_id, downloaded_bytes=index * 100, total_bytes=1000)
        return task_id

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker_insert, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 20
    all_records = repo.get_all(limit=100)
    assert len(all_records) == 20
