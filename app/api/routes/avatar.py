"""Local PNG frames for the optional trainer avatar."""
import hashlib
import json
import struct
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Literal

from app.core.config import ROOT

REACTIONS = ("neutral", "listening", "thinking", "positive", "supportive")
SLOTS = {f"{reaction}-{mouth}" for reaction in REACTIONS for mouth in ("closed", "open")}
MAX_BYTES = 6 * 1024 * 1024


def avatar_router(data_dir: Path):
    router = APIRouter(prefix="/api/avatar")
    directory = data_dir / "avatar"
    manifest_path = ROOT / "web/avatars/marin/manifest.json"
    pack = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else None
    if pack:
        pack["files"] = {key: "/static/avatars/marin/" + name for key, name in pack["files"].items()}

    def save_preset(preset):
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f"{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps({"preset": preset}), encoding="utf-8")
            temporary.replace(directory / "preferences.json")
        finally:
            temporary.unlink(missing_ok=True)

    def image_path(slot):
        if slot not in SLOTS:
            raise HTTPException(422, "Неизвестное состояние аватара.")
        return directory / f"{slot}.png"

    def config():
        images = {}
        for slot in sorted(SLOTS):
            path = image_path(slot)
            if path.is_file():
                version = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
                images[slot] = f"/api/avatar/images/{slot}?v={version}"
        try:
            preset = json.loads((directory / "preferences.json").read_text(encoding="utf-8")).get("preset")
        except (OSError, ValueError, AttributeError):
            preset = "custom" if images else "marin" if pack else "custom"
        if preset not in {"marin", "custom"} or (preset == "marin" and not pack):
            preset = "custom"
        if preset == "marin":
            images = {"neutral-closed": pack["files"]["base"], "neutral-open": pack["files"]["mouth"]}
            for reaction in REACTIONS[1:]:
                images[f"{reaction}-closed"] = pack["files"][reaction]
                images[f"{reaction}-open"] = pack["files"][reaction]
        return {"images": images, "preset": preset, "pack": pack if preset == "marin" else None,
                "presets": ([{"id": "marin", "name": "Ментор по ML"}] if pack else []) + [{"id": "custom", "name": "Свои картинки"}]}

    class Preset(BaseModel):
        preset: Literal["marin", "custom"]

    @router.put("/preset")
    def set_preset(body: Preset):
        if body.preset == "marin" and pack is None:
            raise HTTPException(409, "Набор картинок аватара «Ментор по ML» не установлен.")
        save_preset(body.preset)
        return config()

    @router.get("")
    def get_config():
        return config()

    @router.get("/images/{slot}")
    def get_image(slot: str):
        path = image_path(slot)
        if not path.is_file():
            raise HTTPException(404, "Картинка ещё не выбрана.")
        return FileResponse(path, media_type="image/png", headers={"X-Content-Type-Options": "nosniff"})

    @router.put("/images/{slot}")
    async def put_image(slot: str, image: UploadFile = File(...)):
        path = image_path(slot)
        raw = await image.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, "Картинка слишком большая. Лимит — 6 МБ после обработки.")
        # The client decodes and rasterizes images to PNG before uploading them.
        if (len(raw) < 45 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR"
                or raw[-12:] != b"\x00\x00\x00\x00IEND\xaeB`\x82"):
            raise HTTPException(422, "Нужна корректная PNG-картинка.")
        width, height = struct.unpack(">II", raw[16:24])
        if not 1 <= width <= 2048 or not 1 <= height <= 2048:
            raise HTTPException(422, "Размер картинки должен быть от 1 до 2048 пикселей по каждой стороне.")
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f"{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_bytes(raw)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        save_preset("custom")
        return config()

    @router.delete("/images/{slot}")
    def delete_image(slot: str):
        image_path(slot).unlink(missing_ok=True)
        return config()

    return router
