"""Local-only editor for pinned SpatialLM layouts and verified scene exports.

The client selects a server-owned document revision. It cannot replace source
identity, correction history, local file paths, or exported download targets.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import threading
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

try:
    from .scene_import import load_layout, apply_edits, export_mjcf, serialize_layout
    from .validate_scene import validate_scene
except ImportError:
    from scene_import import load_layout, apply_edits, export_mjcf, serialize_layout
    from validate_scene import validate_scene


_MAX_REQUEST_BYTES = 2_000_000
_MAX_DOCUMENTS = 64
_MAX_DOWNLOAD_SETS = 128
_MAX_EDITOR_ENTITIES = 2_000
_MAX_OPENINGS_PER_WALL = 64
_SAMPLE_SHA256 = "2f3314cee1c864061b20459793a91aafa49bce111325a199f5dbe0340b918893"
_PCD_SHA256 = "12d8cf9c239791260166837d090334915f7056537a2e35c97959d9842a6c5f92"
_SOURCE_COMMIT = "8913c44d84a450c53e9340b13317f8cf7144a738"
_DATA_REVISION = "60bab76febb0c9635f58e156f32e906afc91a499"
_STATIC = Path(__file__).resolve().parent / "static"


@dataclass(frozen=True)
class EditorConfig:
    source_dir: Path
    sample_layout: Path
    sample_point_cloud: Path
    output_dir: Path
    fishbot_project: Path
    render: bool = False


class ImportRequest(BaseModel):
    layout_text: str = Field(min_length=1, max_length=1_000_000)
    filename: str = Field(default="pasted-layout.txt", min_length=1, max_length=128)
    source_kind: Literal["user-provided", "user-declared-gt", "user-declared-prediction"] = "user-provided"


class CorrectRequest(BaseModel):
    document: dict
    edits: list[dict] = Field(min_length=1, max_length=10_000)


class ExportRequest(BaseModel):
    document: dict
    robot: dict | None = None


class LocalRequestPolicy:
    """Bound JSON bodies and reject browser writes from another origin."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def guarded_send(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend([
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store"),
                    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
                ])
            await send(message)

        if scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await self.app(scope, receive, guarded_send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        origin = headers.get("origin")
        expected_origin = f"{scope.get('scheme', 'http')}://{headers.get('host', '')}"
        if (origin and origin != expected_origin) or headers.get("sec-fetch-site") == "cross-site":
            return await JSONResponse({"detail": "Only this editor's own origin may change a document."}, 403)(scope, receive, guarded_send)
        if headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            return await JSONResponse({"detail": "Use an application/json request."}, 415)(scope, receive, guarded_send)
        chunks, size = [], 0
        while True:
            item = await receive()
            if item["type"] == "http.disconnect":
                return
            chunk = item.get("body", b"")
            size += len(chunk)
            if size > _MAX_REQUEST_BYTES:
                return await JSONResponse({"detail": "Request exceeds the 2 MB editor limit."}, 413)(scope, receive, guarded_send)
            chunks.append(chunk)
            if not item.get("more_body", False):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, guarded_send)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_text(value) -> str:
    return str(value).encode("utf-8", errors="backslashreplace").decode("utf-8")


def create_app(config: EditorConfig) -> FastAPI:
    """Create an app with explicit, startup-owned source and output paths."""
    source_dir = Path(config.source_dir).resolve()
    sample = Path(config.sample_layout).resolve()
    point_cloud = Path(config.sample_point_cloud).resolve()
    output_base = Path(config.output_dir).resolve()
    fishbot_project = Path(config.fishbot_project).resolve()
    if not sample.is_file() or _sha(sample) != _SAMPLE_SHA256:
        raise ValueError("sample_layout differs from the pinned official GT sample")
    if not point_cloud.is_file() or _sha(point_cloud) != _PCD_SHA256:
        raise ValueError("sample_point_cloud differs from the pinned official point cloud")
    if not fishbot_project.is_dir():
        raise ValueError("fishbot_project must be an existing project directory")
    output_base.mkdir(parents=True, exist_ok=True)
    # Startup verifies the official geometry modules without a model import.
    load_layout(sample.read_text(encoding="utf-8"), source_dir, {"kind": "startup-check"})
    app = FastAPI(title="FishBot offline scene editor", docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.add_middleware(LocalRequestPolicy)
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_, exc: RequestValidationError):
        # Avoid reflecting invalid Unicode or an entire uploaded body in errors.
        errors = [{"loc": [_safe_text(part) for part in e.get("loc", ())],
                   "type": _safe_text(e.get("type", "invalid")),
                   "msg": _safe_text(e.get("msg", "Invalid request"))}
                  for e in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)
    documents: dict[str, tuple[int, dict]] = {}
    exports: dict[str, dict[str, dict]] = {}
    document_lock = threading.RLock()
    export_lock = threading.Lock()

    def present(document_id: str, revision: int, doc: dict) -> dict:
        result = copy.deepcopy(doc)
        result.update(document_id=document_id, revision=revision)
        return result

    def remember(doc: dict) -> dict:
        enforce_editor_budget(doc)
        document_id = str(uuid4())
        with document_lock:
            if len(documents) >= _MAX_DOCUMENTS:
                documents.pop(next(iter(documents)))
            documents[document_id] = (1, copy.deepcopy(doc))
        return present(document_id, 1, doc)

    def enforce_editor_budget(doc: dict) -> None:
        if len(doc["entities"]) > _MAX_EDITOR_ENTITIES:
            raise HTTPException(400, "This editor accepts at most 2000 entities per layout.")
        openings = {}
        for entity in doc["entities"]:
            if entity["kind"] in {"door", "window"}:
                wall_id = entity["params"]["wall_id"]
                openings[wall_id] = openings.get(wall_id, 0) + 1
                if openings[wall_id] > _MAX_OPENINGS_PER_WALL:
                    raise HTTPException(400, "A wall may have at most 64 openings in this editor.")
            for key, value in entity["params"].items():
                if isinstance(value, str):
                    try:
                        value.encode("utf-8")
                    except UnicodeEncodeError as exc:
                        raise HTTPException(400, f"{entity['id']}.{key}: text must be valid UTF-8.") from exc
                if key not in {"class_name", "wall_id"} and abs(value) > 100_000:
                    raise HTTPException(400, f"{entity['id']}.{key}: value exceeds the indoor editor's 100000-unit limit.")

    def current(client_doc: dict) -> tuple[str, int, dict]:
        document_id, revision = client_doc.get("document_id"), client_doc.get("revision")
        if not isinstance(document_id, str) or type(revision) is not int:
            raise HTTPException(400, "Load a layout before editing or exporting.")
        stored = documents.get(document_id)
        if stored is None:
            raise HTTPException(410, "Document expired or editor restarted; import the layout again.")
        if stored[0] != revision:
            raise HTTPException(409, "Document revision changed; use the latest saved document.")
        # Never trust entities, source or history supplied in the client's copy.
        return document_id, revision, copy.deepcopy(stored[1])

    @app.get("/")
    def homepage():
        return FileResponse(_STATIC / "index.html", media_type="text/html")

    @app.get("/api/health")
    def health():
        return {"status": "ready", "mode": "offline", "model_inference": "not_run", "render_requested": config.render}

    @app.get("/api/example")
    def example():
        # Check again so a cache edit cannot silently acquire an official label.
        if (not sample.is_file() or not point_cloud.is_file()
                or _sha(sample) != _SAMPLE_SHA256 or _sha(point_cloud) != _PCD_SHA256):
            raise HTTPException(409, "Official sample changed after startup; restore the pinned downloads.")
        metadata = {
            "kind": "official-ground-truth", "title": "SpatialLM-Testset / scene0000_00",
            "filename": "scene0000_00.txt", "revision": _DATA_REVISION,
            "url": f"https://huggingface.co/datasets/manycore-research/SpatialLM-Testset/blob/{_DATA_REVISION}/layout/scene0000_00.txt",
            "license": "CC-BY-NC-4.0", "attribution": "Manycore Research / SpatialLM-Testset",
            "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
            "point_cloud_sha256": _PCD_SHA256, "official_source_commit": _SOURCE_COMMIT,
            "model_inference": "not_run; this input is official ground truth",
        }
        try:
            doc = load_layout(sample.read_text(encoding="utf-8"), source_dir, metadata)
        except ValueError as exc:
            raise HTTPException(400, _safe_text(exc)) from exc
        return {"document": remember(doc)}

    @app.post("/api/import")
    def import_document(request: ImportRequest):
        try:
            text_bytes = request.layout_text.encode("utf-8")
            request.filename.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise HTTPException(400, "Layout text and filename must be valid UTF-8.") from exc
        if len(text_bytes) > 1_000_000:
            raise HTTPException(413, "Layout text exceeds the 1 MB import limit.")
        metadata = {"kind": request.source_kind, "filename": Path(request.filename).name,
                    "title": Path(request.filename).name, "license": "Unverified; supplied by the user",
                    "official_source_commit": _SOURCE_COMMIT, "model_inference": "not verified"}
        try:
            doc = load_layout(request.layout_text, source_dir, metadata)
        except ValueError as exc:
            raise HTTPException(400, _safe_text(exc)) from exc
        return {"document": remember(doc)}

    @app.post("/api/correct")
    def correct(request: CorrectRequest):
        with document_lock:
            document_id, revision, doc = current(request.document)
            try:
                updated = apply_edits(doc, request.edits)
            except ValueError as exc:
                raise HTTPException(400, _safe_text(exc)) from exc
            enforce_editor_budget(updated)
            revision += 1
            documents[document_id] = (revision, copy.deepcopy(updated))
        return {"document": present(document_id, revision, updated)}

    @app.post("/api/export")
    def export(request: ExportRequest):
        with document_lock:
            _, revision, doc = current(request.document)
        if not export_lock.acquire(blocking=False):
            raise HTTPException(409, "Another scene is being verified; wait for that export to finish.")
        export_id = str(uuid4())
        output_dir = output_base / export_id
        try:
            corrected_text = serialize_layout(doc, source_dir)
            manifest = export_mjcf(doc, output_dir, fishbot_project, request.robot)
            with (output_dir / "layout.txt").open("x", encoding="utf-8") as handle:
                handle.write(corrected_text + "\n")
            manifest["files"].append("layout.txt")
            scene = Path(manifest["mjcf_path"]).resolve()
            if scene.parent != output_dir:
                raise RuntimeError("Exporter returned a scene outside its new export directory")
            report = validate_scene(scene, output_dir, steps=20, render=config.render)
            if report.get("compiled") is not True or report.get("finite_physical_state") is not True:
                raise RuntimeError("MuJoCo did not confirm compilation and finite physical state")
            manifest["validation"] = report
            manifest["editor_revision"] = revision
            allowed = {}
            for name in [*manifest["files"], "validation.json", *(["scene.png"] if report.get("rendered") is True else [])]:
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                    raise RuntimeError("Exporter returned a nonlocal download filename")
                path = (output_dir / name).resolve()
                if path.parent != output_dir or not path.is_file():
                    raise RuntimeError(f"Missing or invalid verified export file: {name}")
                allowed[name] = path
            manifest["files"] = list(allowed)
            manifest["outputs"].update({name: {"sha256": _sha(path), "bytes": path.stat().st_size}
                                        for name, path in allowed.items() if name != "manifest.json"})
            Path(manifest["manifest_path"]).write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            with document_lock:
                if len(exports) >= _MAX_DOWNLOAD_SETS:
                    exports.pop(next(iter(exports)))
                exports[export_id] = {name: {"path": path, "sha256": _sha(path)}
                                      for name, path in allowed.items()}
            downloads = [{"name": name, "url": f"/api/exports/{export_id}/{name}", "bytes": path.stat().st_size}
                         for name, path in allowed.items()]
            report_for_view = {**report, "simulation_time": report["elapsed_simulation_s"]}
            render_status = {"status": "passed" if report.get("rendered") else "failed" if config.render else "not_requested",
                             "error": report.get("render_error", "No verified render was produced.")}
            return {"export_id": export_id, "manifest": manifest, "validation": report_for_view,
                    "downloads": downloads, "render": render_status,
                    "preview_url": f"/api/exports/{export_id}/scene.png" if report.get("rendered") else None}
        except ValueError as exc:
            raise HTTPException(400, _safe_text(exc)) from exc
        except (RuntimeError, OSError, ImportError) as exc:
            raise HTTPException(503, f"Scene export was not verified: {exc}") from exc
        finally:
            export_lock.release()

    @app.get("/api/exports/{export_id}/{filename}")
    def download(export_id: UUID, filename: str):
        with document_lock:
            recorded = exports.get(str(export_id), {}).get(filename)
        if recorded is None:
            raise HTTPException(404, "File is not in a verified export's download allowlist.")
        path = recorded["path"]
        # Serve the checked bytes themselves; a late FileResponse read could
        # otherwise return different bytes after the digest check.
        try:
            if path.resolve(strict=True).parent != output_base / str(export_id):
                raise OSError("Export path changed")
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as handle:
                data = handle.read()
        except OSError as exc:
            raise HTTPException(409, "Export file changed after verification.") from exc
        if hashlib.sha256(data).hexdigest() != recorded["sha256"]:
            raise HTTPException(409, "Export bytes changed after verification.")
        disposition = "inline" if filename.endswith(".png") else "attachment"
        return Response(data, media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
                        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'})

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local offline SpatialLM editor")
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--sample-layout", type=Path, required=True)
    parser.add_argument("--sample-point-cloud", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fishbot-project", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--render", action="store_true", help="Request an actual MuJoCo PNG render")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    import uvicorn
    app = create_app(EditorConfig(args.source_dir, args.sample_layout, args.sample_point_cloud,
                                 args.output_dir, args.fishbot_project, args.render))
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
