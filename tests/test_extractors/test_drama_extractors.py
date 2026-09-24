"""Tests for custom short drama extractors."""

from unittest.mock import MagicMock
import httpx
import pytest

from app.core.extractor_registry import get_default_registry
from app.extractors.base import ExtractionError
from app.extractors.dramabox import DramaBoxExtractor
from app.extractors.dramawave import DramaWaveExtractor
from app.extractors.flickreels import FlickReelsExtractor
from app.extractors.freereels import FreeReelsExtractor
from app.extractors.goodshort import GoodShortExtractor
from app.extractors.netshort import NetShortExtractor
from app.extractors.stardusttv import StardustTVExtractor


SAMPLE_DRAMA_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta property="og:title" content="Billionaire's Secret Bride &amp; Revenge" />
    <meta property="og:image" content="https://example.com/poster.jpg" />
    <meta property="og:description" content="A thrilling romance drama." />
</head>
<body>
    <h1>Billionaire's Secret Bride</h1>
    <video src="https://example.com/streams/ep1.mp4"></video>
    <div class="episodes">
        <a href="/watch/drama-123/ep-1">Episode 1</a>
        <a href="/watch/drama-123/ep-2">Episode 2</a>
        <a href="/watch/drama-123/ep-3">Episode 3</a>
    </div>
</body>
</html>
"""


def test_drama_can_handle() -> None:
    """Verify domain pattern matching across all 7 drama platforms."""
    assert DramaBoxExtractor().can_handle("https://www.dramabox.com/drama/123") is True
    assert DramaBoxExtractor().can_handle("https://dramaboxdb.com/play/456") is True

    assert NetShortExtractor().can_handle("https://netshort.com/watch/1") is True
    assert NetShortExtractor().can_handle("https://app.netshortapp.com/v/2") is True

    assert FlickReelsExtractor().can_handle("https://flickreels.com/series/3") is True
    assert FlickReelsExtractor().can_handle("https://flickreelsapp.com/series/4") is True

    assert StardustTVExtractor().can_handle("https://stardusttv.com/drama/5") is True
    assert StardustTVExtractor().can_handle("https://stardust.tv/drama/6") is True

    assert GoodShortExtractor().can_handle("https://goodshort.com/book/7") is True

    assert DramaWaveExtractor().can_handle("https://dramawave.com/show/8") is True

    assert FreeReelsExtractor().can_handle("https://freereels.com/detail/9") is True
    assert FreeReelsExtractor().can_handle("https://freereelsapp.com/detail/10") is True

    # Other URLs should not match drama extractors
    assert DramaBoxExtractor().can_handle("https://youtube.com/watch?v=123") is False
    assert NetShortExtractor().can_handle("https://tiktok.com/@user") is False


def test_drama_extraction_with_mock_client() -> None:
    """Verify HTML parsing extracts title, thumbnail, streams, and episodes correctly."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.text = SAMPLE_DRAMA_HTML
    mock_client.get.return_value = mock_response

    extractor = DramaBoxExtractor(client=mock_client)
    media_info = extractor.extract("https://www.dramabox.com/watch/drama-123")

    assert media_info.title == "Billionaire's Secret Bride & Revenge"
    assert media_info.platform == "DramaBox"
    assert media_info.thumbnail_url == "https://example.com/poster.jpg"
    assert len(media_info.formats) > 0
    assert len(media_info.episodes) == 3
    assert media_info.episodes[0].episode_number == 1
    assert media_info.episodes[1].episode_number == 2
    assert media_info.episodes[2].episode_number == 3
    assert media_info.is_playlist is True


def test_drama_extraction_http_404_error() -> None:
    """Verify HTTP 404 triggers a clean ExtractionError."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 404

    http_err = httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)
    mock_response.raise_for_status.side_effect = http_err
    mock_client.get.return_value = mock_response

    extractor = NetShortExtractor(client=mock_client)
    with pytest.raises(ExtractionError) as exc_info:
        extractor.extract("https://netshort.com/missing-drama")

    assert "not found" in str(exc_info.value).lower()


def test_drama_extraction_http_403_restricted() -> None:
    """Verify HTTP 403 triggers a restricted access ExtractionError."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 403

    http_err = httpx.HTTPStatusError("Forbidden", request=MagicMock(), response=mock_response)
    mock_response.raise_for_status.side_effect = http_err
    mock_client.get.return_value = mock_response

    extractor = GoodShortExtractor(client=mock_client)
    with pytest.raises(ExtractionError) as exc_info:
        extractor.extract("https://goodshort.com/restricted-drama")

    assert "restricted" in str(exc_info.value).lower()


def test_default_registry_routes_drama_platforms() -> None:
    """Verify default registry correctly prioritizes custom drama extractors over yt-dlp."""
    registry = get_default_registry()

    dramabox_match = registry.find_extractor("https://www.dramabox.com/watch/123")
    assert isinstance(dramabox_match, DramaBoxExtractor)

    netshort_match = registry.find_extractor("https://netshort.com/play/456")
    assert isinstance(netshort_match, NetShortExtractor)

    goodshort_match = registry.find_extractor("https://goodshort.com/book/789")
    assert isinstance(goodshort_match, GoodShortExtractor)

    # General video still falls back to yt-dlp
    youtube_match = registry.find_extractor("https://youtube.com/watch?v=dQw4w9WgXcQ")
    assert youtube_match.platform_name == "Generic Video"


def test_embedded_json_ld_and_next_data_extraction() -> None:
    """Verify that JSON-LD and Next.js state embedded scripts are parsed for media streams."""
    html_with_embedded = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>CEO's Hidden Heiress</title>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "VideoObject",
            "name": "CEO's Hidden Heiress Episode 1",
            "contentUrl": "https://cdn.example.com/stream/master.m3u8",
            "thumbnailUrl": "https://cdn.example.com/thumbs/cover.jpg",
            "hasPart": [
                {"episode_number": 1, "name": "Pilot", "url": "https://example.com/ep1"},
                {"episode_number": 2, "name": "Confrontation", "url": "https://example.com/ep2"}
            ]
        }
        </script>
        <script id="__NEXT_DATA__" type="application/json">
        {
            "props": {
                "pageProps": {
                    "video_url": "https://cdn.example.com/backup.mp4"
                }
            }
        }
        </script>
    </head>
    <body>
        <div>Desktop view without direct video tags</div>
    </body>
    </html>
    """
    mock_client = MagicMock(spec=httpx.Client)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.text = html_with_embedded
    mock_client.get.return_value = mock_response

    extractor = DramaBoxExtractor(client=mock_client)
    media_info = extractor.extract("https://www.dramabox.com/drama/9999")

    assert media_info.title == "CEO's Hidden Heiress"
    assert media_info.thumbnail_url == "https://cdn.example.com/thumbs/cover.jpg"
    assert len(media_info.formats) >= 2
    # Should have discovered m3u8 and mp4 from embedded JSON
    stream_exts = [f.extension for f in media_info.formats]
    assert "m3u8" in stream_exts
    assert "mp4" in stream_exts
    # Discovered episodes from hasPart
    assert len(media_info.episodes) == 2
    assert media_info.episodes[0].title == "Pilot"
    assert media_info.episodes[1].title == "Confrontation"


def test_mobile_profile_fallback_when_desktop_lacks_stream() -> None:
    """Verify that when desktop HTML has no video tags, mobile headers retry discovers mobile streams."""
    desktop_empty_html = """
    <html><head><title>Locked Drama</title></head><body><div class="locked">Please download the mobile app</div></body></html>
    """
    mobile_rich_html = """
    <html>
    <head><title>Locked Drama</title></head>
    <body>
        <video src="https://cdn.example.com/mobile/stream.mp4"></video>
        <a href="/ep-1">Ep 1</a>
        <a href="/ep-2">Ep 2</a>
    </body>
    </html>
    """

    mock_client = MagicMock(spec=httpx.Client)
    desktop_resp = MagicMock(spec=httpx.Response)
    desktop_resp.status_code = 200
    desktop_resp.text = desktop_empty_html

    mobile_resp = MagicMock(spec=httpx.Response)
    mobile_resp.status_code = 200
    mobile_resp.text = mobile_rich_html

    # First call returns desktop HTML, second call (with mobile headers) returns mobile HTML
    mock_client.get.side_effect = [desktop_resp, mobile_resp]

    extractor = NetShortExtractor(client=mock_client)
    media_info = extractor.extract("https://netshort.com/locked/100")

    assert len(media_info.formats) > 0
    assert any("mobile/stream.mp4" in fmt.note or fmt.format_id != "default" for fmt in media_info.formats)
    assert len(media_info.episodes) == 2


def test_dramabox_canonical_id_extraction() -> None:
    """Verify drama ID parser extracts canonical IDs across URL formats."""
    extractor = DramaBoxExtractor()

    assert extractor.extract_drama_id("https://www.dramabox.com/drama/12345/ep-1") == "12345"
    assert extractor.extract_drama_id("https://www.dramabox.com/watch/67890") == "67890"
    assert extractor.extract_drama_id("https://www.dramabox.com/movie/55555") == "55555"
    assert extractor.extract_drama_id("https://www.dramabox.com/play?id=8888") == "8888"
    assert extractor.extract_drama_id("https://dramaboxdb.com/watch/9999") == "9999"


def test_dramabox_mirror_resolution_fallback() -> None:
    """Verify DramaBox triggers mirror resolver when primary page is empty."""
    desktop_empty_html = """
    <html><head><title>Restricted Drama</title></head><body>No media here</body></html>
    """
    mirror_rich_html = """
    <html>
    <head>
        <meta property="og:title" content="Revenge of the Substituted Bride" />
        <meta property="og:image" content="https://dramaboxdb.com/posters/12345.jpg" />
    </head>
    <body>
        <video src="https://cdn.dramaboxdb.com/stream/ep1.mp4"></video>
        <a href="/watch/12345/ep-1">Episode 1</a>
        <a href="/watch/12345/ep-2">Episode 2</a>
    </body>
    </html>
    """

    mock_client = MagicMock(spec=httpx.Client)
    resp_empty = MagicMock(spec=httpx.Response)
    resp_empty.status_code = 200
    resp_empty.text = desktop_empty_html

    resp_mirror = MagicMock(spec=httpx.Response)
    resp_mirror.status_code = 200
    resp_mirror.text = mirror_rich_html

    # Calls: 1. Desktop official, 2. Mobile official, 3. Mirror indexer
    mock_client.get.side_effect = [resp_empty, resp_empty, resp_mirror]

    extractor = DramaBoxExtractor(client=mock_client)
    media_info = extractor.extract("https://www.dramabox.com/drama/12345")

    assert media_info.title == "Revenge of the Substituted Bride"
    assert media_info.thumbnail_url == "https://dramaboxdb.com/posters/12345.jpg"
    assert len(media_info.formats) > 0
    assert len(media_info.episodes) == 2
    assert "dramaboxdb.com" in media_info.url


def test_canonical_id_extraction_across_all_platforms() -> None:
    """Verify canonical ID extraction regex across all drama extractors."""
    assert NetShortExtractor().extract_canonical_id("https://netshort.com/watch/ns_98765") == "ns_98765"
    assert NetShortExtractor().extract_canonical_id("https://app.netshortapp.com/v/v_1234") == "v_1234"

    assert GoodShortExtractor().extract_canonical_id("https://goodshort.com/book/gs_54321") == "gs_54321"
    assert GoodShortExtractor().extract_canonical_id("https://goodshort.com/drama/d_888") == "d_888"

    assert FlickReelsExtractor().extract_canonical_id("https://flickreels.com/series/fr_111") == "fr_111"
    assert FlickReelsExtractor().extract_canonical_id("https://flickreelsapp.com/watch/fr_222") == "fr_222"

    assert FreeReelsExtractor().extract_canonical_id("https://freereels.com/detail/freer_333") == "freer_333"
    assert StardustTVExtractor().extract_canonical_id("https://stardusttv.com/drama/star_444") == "star_444"
    assert DramaWaveExtractor().extract_canonical_id("https://dramawave.com/show/dw_555") == "dw_555"


def test_multi_mirror_rotation_succeeds_on_second_mirror() -> None:
    """Verify rotation continues to mirror 2 if mirror 1 fails or returns 404."""
    desktop_empty = "<html><head><title>Locked</title></head><body>No streams</body></html>"
    mirror_2_content = """
    <html>
    <head><meta property="og:title" content="Reborn Princess" /></head>
    <body>
        <video src="https://cdn.netshortdb.com/stream/ep1.mp4"></video>
        <a href="/ep-1">Episode 1</a>
    </body>
    </html>
    """

    mock_client = MagicMock(spec=httpx.Client)

    resp_empty = MagicMock(spec=httpx.Response)
    resp_empty.status_code = 200
    resp_empty.text = desktop_empty

    resp_mirror1_err = MagicMock(spec=httpx.Response)
    resp_mirror1_err.status_code = 404
    resp_mirror1_err.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Not Found", request=MagicMock(), response=resp_mirror1_err
    )

    resp_mirror2 = MagicMock(spec=httpx.Response)
    resp_mirror2.status_code = 200
    resp_mirror2.text = mirror_2_content

    # Call 1: Desktop, Call 2: Mobile, Call 3: Mirror 1 (fails 404), Call 4: Mirror 2 (succeeds)
    mock_client.get.side_effect = [resp_empty, resp_empty, resp_mirror1_err, resp_mirror2]

    extractor = NetShortExtractor(client=mock_client)
    media_info = extractor.extract("https://netshort.com/watch/drama_xyz")

    assert media_info.title == "Reborn Princess"
    assert len(media_info.formats) > 0
    assert len(media_info.episodes) == 1
    assert "netshortdb.com" in media_info.url


def test_clean_drama_title() -> None:
    """Verify stripping of marketing buzzwords, domain tags, and delimiters."""
    raw = "Deny Me, Dragon King full movie-Deny Me, Dragon King full episodes-DramaBox"
    assert DramaBoxExtractor.clean_drama_title(raw) == "Deny Me, Dragon King"

    raw2 = "Run, Mommy! Daddy Is Coming! | Short Drama All Episodes"
    assert DramaBoxExtractor.clean_drama_title(raw2) == "Run, Mommy! Daddy Is Coming!"

    raw3 = "The Lost CEO & Heiress - Eng Sub Watch Free"
    assert DramaBoxExtractor.clean_drama_title(raw3) == "The Lost CEO & Heiress"


def test_find_syndicated_compilations_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify syndication search parses flat search results into complete series episodes."""
    mock_entries = [
        {
            "title": "Deny Me, Dragon King Full Movie (All Episodes)",
            "url": "https://example.com/watch?v=sample1",
            "duration": 6000,
        },
        {
            "title": "Unrelated Minecraft Video",
            "url": "https://example.com/watch?v=sample2",
            "duration": 500,
        },
    ]

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = {"entries": mock_entries}
    mock_ydl.__enter__.return_value = mock_ydl

    import yt_dlp
    monkeypatch.setattr(yt_dlp, "YoutubeDL", lambda *args, **kwargs: mock_ydl)

    extractor = DramaBoxExtractor()
    comps = extractor.find_syndicated_compilations("Deny Me, Dragon King")

    assert len(comps) == 1
    assert comps[0].episode_number == 0
    assert "[Full Series Complete]" in comps[0].title
    assert "Deny Me, Dragon King" in comps[0].title
    assert comps[0].url == "https://example.com/watch?v=sample1"
    assert comps[0].duration_seconds == 6000

