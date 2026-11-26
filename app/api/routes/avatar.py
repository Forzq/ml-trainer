"""Read-only configuration for the built-in trainer avatars."""
import json

from fastapi import APIRouter

from app.core.config import ROOT


def load_pack(preset):
    manifest = ROOT / "web" / "avatars" / preset / "manifest.json"
    if not manifest.is_file():
        return None
    pack = json.loads(manifest.read_text(encoding="utf-8"))
    pack["files"] = {key: f"/static/avatars/{preset}/{name}" for key, name in pack["files"].items()}
    return pack


def avatar_router():
    router = APIRouter(prefix="/api/avatar")
    mentor = load_pack("marin")
    packs = [pack for pack in (mentor, load_pack("oiia")) if pack is not None]

    @router.get("")
    def get_config():
        return {"pack": mentor, "packs": packs}

    return router
