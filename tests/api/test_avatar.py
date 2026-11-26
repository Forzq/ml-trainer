from unittest.mock import patch

from fastapi.testclient import TestClient

from app.questions.catalog import load_cards
from app.server import create_app
from test_app import authenticated, settings_at


def test_avatar_defaults_to_the_builtin_pack_for_existing_users(tmp_path):
    directory = tmp_path / "avatar"
    directory.mkdir()
    preferences = directory / "preferences.json"
    old_photo = directory / "neutral-closed.png"
    preferences.write_text('{"preset": "custom"}', encoding="utf-8")
    old_photo.write_bytes(b"existing local image")

    with patch("app.storage.store.load_cards", return_value=load_cards()[:2]), TestClient(create_app(settings_at(tmp_path))) as client:
        config = client.get("/api/avatar").json()
        pack = config["pack"]
        assert pack["id"] == "marin"
        assert pack["name"] == "Ментор по ML"
        assert len(pack["files"]) == 7
        for url in pack["files"].values():
            assert url.startswith("/static/avatars/marin/")
            assert client.get(url).status_code == 200
        mentor, cat = config["packs"]
        assert mentor == pack and mentor["voices"] == ["female"]
        assert cat["id"] == "oiia" and cat["kind"] == "turntable"
        assert cat["voices"] == ["female", "male"] and cat["frames"] == 36
        for url in cat["files"].values():
            response = client.get(url)
            assert response.status_code == 200
            assert response.content[:4] == b"RIFF" and response.content[8:12] == b"WEBP"

        headers = authenticated(client)
        assert client.put("/api/avatar/preset", headers=headers, json={"preset": "custom"}).status_code == 404
        assert client.put("/api/avatar/images/neutral-closed", headers=headers,
                          files={"image": ("photo.png", b"new image")}).status_code == 404
        assert client.delete("/api/avatar/images/neutral-closed", headers=headers).status_code == 404

    assert preferences.read_text(encoding="utf-8") == '{"preset": "custom"}'
    assert old_photo.read_bytes() == b"existing local image"
