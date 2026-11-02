"""Custom exceptions for media extraction and DRM handling."""


class ExtractError(Exception):
    """Raised when metadata/video URL cannot be resolved."""


class DRMProtected(ExtractError):
    """Widevine/PlayReady — ffmpeg alone can't finish."""


class LoginRequired(ExtractError):
    """Endpoint needs a valid session cookie."""

