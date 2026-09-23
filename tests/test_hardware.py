"""Unit tests for cross-platform hardware identification and verification."""

import pytest
from unittest.mock import patch

from app.services.hardware import (
    get_raw_machine_uuid,
    get_machine_id,
    verify_machine_id,
    _get_macos_uuid,
    _get_linux_uuid,
)


def test_get_machine_id_format() -> None:
    """Verify machine ID conforms to MDFL-HWID-XXXX-XXXX format."""
    hwid = get_machine_id()
    assert hwid.startswith("MDFL-HWID-")
    parts = hwid.split("-")
    assert len(parts) == 4
    assert len(parts[2]) == 4
    assert len(parts[3]) == 4


def test_verify_machine_id_match_and_wildcard() -> None:
    """Verify exact match, short match, and wildcard matching behavior."""
    current_hwid = "MDFL-HWID-ABCD-1234"

    # Exact match
    assert verify_machine_id("MDFL-HWID-ABCD-1234", current_id=current_hwid) is True
    # Short match
    assert verify_machine_id("ABCD-1234", current_id=current_hwid) is True
    assert verify_machine_id("ABCD1234", current_id=current_hwid) is True
    # Wildcards
    assert verify_machine_id("ANY", current_id=current_hwid) is True
    assert verify_machine_id("ALL", current_id=current_hwid) is True
    assert verify_machine_id("*", current_id=current_hwid) is True

    # Mismatches
    assert verify_machine_id("MDFL-HWID-9999-0000", current_id=current_hwid) is False
    assert verify_machine_id("9999-0000", current_id=current_hwid) is False
    assert verify_machine_id("", current_id=current_hwid) is False
    assert verify_machine_id(None, current_id=current_hwid) is False


def test_get_raw_machine_uuid_macos_fallback() -> None:
    """Verify fallback behavior when platform-specific retrieval fails."""
    with patch("platform.system", return_value="Darwin"):
        with patch("app.services.hardware._get_macos_uuid", return_value=None):
            raw = get_raw_machine_uuid()
            assert raw.startswith("fallback-")


def test_get_macos_uuid_parsing() -> None:
    """Verify parsing of ioreg output."""
    mock_output = '    | |   "IOPlatformUUID" = "12345678-ABCD-EF01-2345-6789ABCDEF01"\n'
    with patch("subprocess.check_output", return_value=mock_output):
        val = _get_macos_uuid()
        assert val == "12345678-ABCD-EF01-2345-6789ABCDEF01"
