"""Tests for GUI widgets logic and styling resolution."""

import pytest

from app.database.models import DownloadStatus
from app.gui.styles import COLORS
from app.gui.widgets.sidebar import format_sidebar_license
from app.gui.widgets.status_badge import get_status_badge_style
from app.services.license import LicenseInfo, LicenseStatus


def test_status_badge_styles_all_states() -> None:
    """Verify get_status_badge_style resolves correct text and colors for all statuses."""
    # Downloading
    dl_style = get_status_badge_style(DownloadStatus.DOWNLOADING)
    assert dl_style.text == "DOWNLOADING"
    assert dl_style.bg_color == COLORS.status_info_bg
    assert dl_style.border_color == COLORS.status_info

    # Completed
    comp_style = get_status_badge_style(DownloadStatus.COMPLETED)
    assert comp_style.text == "COMPLETED"
    assert comp_style.bg_color == COLORS.status_success_bg
    assert comp_style.border_color == COLORS.status_success

    # Processing
    proc_style = get_status_badge_style(DownloadStatus.PROCESSING)
    assert proc_style.text == "PROCESSING"
    assert proc_style.border_color == COLORS.status_warning

    # Failed
    fail_style = get_status_badge_style(DownloadStatus.FAILED)
    assert fail_style.text == "FAILED"
    assert fail_style.bg_color == COLORS.status_danger_bg
    assert fail_style.border_color == COLORS.status_danger

    # Cancelled
    canc_style = get_status_badge_style(DownloadStatus.CANCELLED)
    assert canc_style.text == "CANCELLED"
    assert canc_style.border_color == COLORS.border_subtle

    # Queued
    q_style = get_status_badge_style(DownloadStatus.QUEUED)
    assert q_style.text == "QUEUED"


def test_status_badge_custom_text_override() -> None:
    """Verify custom text override is respected by status badge style."""
    custom = get_status_badge_style(DownloadStatus.DOWNLOADING, custom_text="75% ACTIVE")
    assert custom.text == "75% ACTIVE"
    assert custom.bg_color == COLORS.status_info_bg


def test_sidebar_license_display_active_pro() -> None:
    """Verify sidebar license formatter renders active Pro tier info."""
    info = LicenseInfo(
        status=LicenseStatus.ACTIVE,
        is_valid=True,
        tier="pro",
        days_remaining=28,
        hours_remaining=4,
        is_lifetime=False,
    )
    display = format_sidebar_license(info)
    assert display.title == "PRO TIER"
    assert "28 Days Remaining" in display.subtitle
    assert display.title_color == COLORS.status_success


def test_sidebar_license_display_lifetime() -> None:
    """Verify sidebar license formatter renders permanent Lifetime tier info."""
    info = LicenseInfo(
        status=LicenseStatus.ACTIVE,
        is_valid=True,
        tier="lifetime",
        days_remaining=9999,
        is_lifetime=True,
    )
    display = format_sidebar_license(info)
    assert display.title == "LIFETIME TIER"
    assert display.subtitle == "Permanent License"
    assert display.title_color == COLORS.status_success


def test_sidebar_license_display_clock_tampered() -> None:
    """Verify sidebar license formatter renders tamper warning."""
    info = LicenseInfo(
        status=LicenseStatus.TAMPERED,
        is_valid=False,
        tier="pro",
    )
    display = format_sidebar_license(info)
    assert display.title == "CLOCK ERROR"
    assert "Rollback" in display.subtitle
    assert display.title_color == COLORS.status_danger


def test_sidebar_license_display_expired() -> None:
    """Verify sidebar license formatter renders expired status."""
    info = LicenseInfo(
        status=LicenseStatus.EXPIRED,
        is_valid=False,
        tier="standard",
    )
    display = format_sidebar_license(info)
    assert display.title == "EXPIRED"
    assert "Renew" in display.subtitle
    assert display.title_color == COLORS.status_warning


def test_sidebar_license_display_unactivated() -> None:
    """Verify sidebar license formatter renders unactivated fallback."""
    info = LicenseInfo(
        status=LicenseStatus.UNACTIVATED,
        is_valid=False,
    )
    display = format_sidebar_license(info)
    assert display.title == "FREE MODE"
    assert display.subtitle == "Unactivated"
