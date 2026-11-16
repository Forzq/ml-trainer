import struct
import zlib
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.catalog import load_cards
from app.server import create_app
from test_app import authenticated, settings_at


def png(width=1, height=1):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\0\xff\0\xff\xff")) + chunk(b"IEND", b""))


def test_avatar_upload_persistence_and_delete_are_local_and_authenticated(tmp_path):
    settings = settings_at(tmp_path)
    with patch("app.store.load_cards", return_value=load_cards()[:2]):
        with TestClient(create_app(settings)) as client:
            assert client.get("/api/avatar").json()["preset"] == "marin"
            assert client.put("/api/avatar/images/neutral-closed", files={"image": ("photo.png", png())}).status_code == 403
            headers = authenticated(client)
            assert client.put("/api/avatar/preset", json={"preset": "custom"}, headers=headers).json()["images"] == {}
            for slot in ("neutral-closed", "neutral-open", "positive-closed"):
                result = client.put(f"/api/avatar/images/{slot}", files={"image": ("../../photo.png", png())}, headers=headers)
                assert result.status_code == 200
                url = result.json()["images"][slot]
                response = client.get(url)
                assert response.content == png() and response.headers["content-type"] == "image/png"
            assert len(list((tmp_path / "avatar").glob("*.png"))) == 3
            assert not (tmp_path / "photo.png").exists()
        with TestClient(create_app(settings)) as client:
            assert len(client.get("/api/avatar").json()["images"]) == 3
            assert client.delete("/api/avatar/images/neutral-open").status_code == 403
            result = client.delete("/api/avatar/images/neutral-open", headers=authenticated(client))
            assert "neutral-open" not in result.json()["images"]
            assert client.get("/api/avatar/images/neutral-open").status_code == 404


def test_invalid_images_and_slot_names_do_not_overwrite_existing_frames(tmp_path):
    with patch("app.store.load_cards", return_value=load_cards()[:2]), TestClient(create_app(settings_at(tmp_path))) as client:
        headers = authenticated(client)
        endpoint = "/api/avatar/images/neutral-closed"
        assert client.put(endpoint, files={"image": ("image.png", png())}, headers=headers).status_code == 200
        for data, status in ((b"<svg onload='alert(1)'></svg>", 422), (png(4096), 422), (png(0), 422),
                             (b"x" * (6 * 1024 * 1024 + 1), 413), (png()[:-12], 422)):
            response = client.put(endpoint, files={"image": ("image.png", data)}, headers=headers)
            assert response.status_code == status
            assert client.get(endpoint).content == png()
        assert client.put("/api/avatar/images/unknown", files={"image": ("image.png", png())}, headers=headers).status_code == 422
        assert client.delete("/api/avatar/images/unknown", headers=headers).status_code == 422


def test_marin_preset_keeps_custom_images_and_uses_only_local_assets(tmp_path):
    with patch("app.store.load_cards", return_value=load_cards()[:2]), TestClient(create_app(settings_at(tmp_path))) as client:
        headers = authenticated(client)
        assert client.put("/api/avatar/preset", json={"preset": "marin"}).status_code == 403
        assert client.put("/api/avatar/preset", json={"preset": "unknown"}, headers=headers).status_code == 422
        client.put("/api/avatar/images/neutral-closed", files={"image": ("user.png", png())}, headers=headers)
        assert client.get("/api/avatar").json()["preset"] == "custom"
        config = client.put("/api/avatar/preset", json={"preset": "marin"}, headers=headers).json()
        assert config["preset"] == "marin" and config["pack"]["id"] == "marin"
        assert len(config["pack"]["files"]) == 7
        for url in config["pack"]["files"].values():
            assert url.startswith("/static/avatars/marin/")
            assert client.get(url).status_code == 200
        config = client.put("/api/avatar/preset", json={"preset": "custom"}, headers=headers).json()
        assert client.get(config["images"]["neutral-closed"]).content == png()
