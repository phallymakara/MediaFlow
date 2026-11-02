import pytest
from unittest.mock import AsyncMock, MagicMock
from app.signatures.bili_wbi import _mixin, sign
from app.signatures.douyin_sign import a_bogus, signed_query


def test_bili_wbi_mixin():
    raw = "abcdefghijklmnopqrstuvwxyz1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    res = _mixin(raw)
    assert len(res) == 32
    assert isinstance(res, str)


@pytest.mark.asyncio
async def test_bili_wbi_sign():
    mock_nav_response = MagicMock()
    mock_nav_response.json.return_value = {
        "data": {
            "wbi_img": {
                "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084481368485c96b28d80b0e2a163.png",
                "sub_url": "https://i0.hdslb.com/bfs/wbi/529e2574fa404b13bd10f8604d49d207.png",
            }
        }
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_nav_response

    params = {"bvid": "BV1xx411c7mD", "cid": "123456"}
    signed = await sign(mock_client, params)

    assert "w_rid" in signed
    assert "wts" in signed
    assert signed["bvid"] == "BV1xx411c7mD"
    assert signed["cid"] == "123456"


def test_douyin_sign():
    query = "aweme_id=1234567890&aid=6383"
    bogus = a_bogus(query)
    assert isinstance(bogus, str)
    assert len(bogus) > 10

    signed = signed_query({"aweme_id": "1234567890", "aid": "6383"})
    assert "a_bogus=" in signed
    assert "aweme_id=1234567890" in signed
