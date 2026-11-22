"""Read-only configuration for the built-in trainer avatar."""
import json

from fastapi import APIRouter

from app.core.config import ROOT


def avatar_router():
    router = APIRouter(prefix="/api/avatar")
    assets = ROOT / "web/avatars/marin"
    manifest_path = assets / "manifest.json"
    pack = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else None
    if pack:
        pack["files"] = {key: f"/static/avatars/marin/{name}" for key, name in pack["files"].items()}

    @router.get("")
    def get_config():
        return {"pack": pack}

    return router
