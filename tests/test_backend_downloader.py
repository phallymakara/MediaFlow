import asyncio
import pathlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.downloader import direct, remux, hls


@pytest.mark.asyncio
async def test_direct_download(tmp_path):
    dest = tmp_path / "test.mp4"

    class AsyncStreamMock:
        def raise_for_status(self):
            pass

        async def aiter_bytes(self, chunk_size):
            yield b"chunk1"
            yield b"chunk2"

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class MockClient:
        def stream(self, method, url):
            return AsyncStreamMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("app.downloader.direct.make_client", return_value=MockClient()):
        res = await direct.download("https://example.com/video.mp4", dest)
        assert res.exists()
        assert res.read_bytes() == b"chunk1chunk2"


@pytest.mark.asyncio
async def test_remux_to_mp4(tmp_path):
    src = tmp_path / "sample.ts"
    src.write_bytes(b"dummy_ts_data")
    dst = tmp_path / "sample.mp4"

    mock_proc = AsyncMock()
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        res = await remux.to_mp4(src, dst)
        assert res == dst
        assert not src.exists()  # src unlinked on success


@pytest.mark.asyncio
async def test_hls_download_aes128(tmp_path):
    # Prepare AES-128 key & plaintext
    key = b"0123456789abcdef"  # 16 bytes
    iv = b"\x00" * 15 + b"\x01"  # 16 bytes (seq 1)
    plaintext = b"MPEG_TS_CONTENT_PAYLOAD_TESTING"
    # PKCS#7 pad plaintext to 32 bytes (multiple of 16)
    pad_len = 16 - (len(plaintext) % 16)
    padded = plaintext + bytes([pad_len] * pad_len)

    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    m3u8_content = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:10
#EXT-X-MEDIA-SEQUENCE:1
#EXT-X-KEY:METHOD=AES-128,URI="https://example.com/key.bin"
#EXTINF:10.0,
https://example.com/seg1.ts
#EXT-X-ENDLIST
"""

    async def mock_get(client, url, **kw):
        mock_r = MagicMock()
        mock_r.raise_for_status = lambda: None
        if url.endswith(".m3u8"):
            mock_r.text = m3u8_content
        elif url.endswith("key.bin"):
            mock_r.content = key
        elif url.endswith("seg1.ts"):
            mock_r.content = ciphertext
        return mock_r

    dest = tmp_path / "out.ts"

    with patch("app.downloader.hls.get", side_effect=mock_get):
        raw = await hls.download("https://example.com/stream.m3u8", dest)
        assert raw.exists()
        assert raw.read_bytes() == plaintext
