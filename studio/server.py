"""Garment Studio panel server (stdlib only, no build step).

    ./.venv/Scripts/python.exe -m studio.server --port 8765

Routes
  GET  /                        the panel (studio/panel/index.html)
  GET  /api/jobs                list jobs (newest first)
  GET  /api/jobs/<id>           one job: stage, description, approval, files, sim
  POST /api/jobs                create a job: {"title","image_path","session_id","notes"}
  POST /api/jobs/<id>/approval  {"decision":"accept"|"edit","text":"..."}
  POST /api/jobs/<id>/description {"text":"..."}
  GET  /files/<id>/<relpath>    any file inside the job folder (image, svg, glb, ...)

The panel talks to this server only; the DSH plugin watches approval.json and turns
approvals into chat messages, so the browser never needs to know DSH exists.
"""
import argparse
import json
import mimetypes
import os
import socket
import subprocess
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from studio import jobs as jobstore

PANEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel")

mimetypes.add_type("model/gltf-binary", ".glb")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("image/svg+xml", ".svg")


def open_folder(path):
    """Reveal a folder in the OS file browser.

    Returns (ok, method, error).  The old version swallowed every error, so a click that
    did nothing looked identical to a click that worked -- which is exactly the bug the
    panel showed.  Now each strategy is tried in turn and the failure is reported:
    1. os.startfile (the documented Windows way)
    2. explorer.exe <path> (survives sessions where startfile has no usable shell)
    3. xdg-open (linux)
    """
    path = os.path.normpath(path)
    if not os.path.isdir(path):
        return False, "none", "folder does not exist: %s" % path
    errors = []
    if os.name == "nt":
        try:
            os.startfile(path)  # noqa: S606 - intended: reveal the job folder
            return True, "startfile", None
        except OSError as exc:
            errors.append("startfile: %s" % exc)
        try:
            proc = subprocess.Popen(["explorer.exe", path])
            try:
                code = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                code = 0  # explorer keeps running with the window open - that is success
            if code == 0:
                return True, "explorer", None
            errors.append("explorer: exit code %s" % code)
        except OSError as exc:
            errors.append("explorer: %s" % exc)
    else:
        try:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True, "xdg-open", None
        except OSError as exc:
            errors.append("xdg-open: %s" % exc)
    return False, "none", "; ".join(errors)


def _safe_join(root, rel):
    rel = rel.replace("\\", "/").lstrip("/")
    full = os.path.normpath(os.path.join(root, rel))
    if os.path.commonpath([os.path.abspath(root), os.path.abspath(full)]) != os.path.abspath(root):
        raise ValueError("path escapes root")
    return full


class Handler(BaseHTTPRequestHandler):
    server_version = "GarmentStudio/1.0"

    # ------------------------------------------------------------ utilities
    def log_message(self, fmt, *args):
        print("[studio] " + fmt % args, flush=True)

    def _send(self, code, body=b"", ctype="application/json", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("body must be JSON")

    def _file(self, path):
        if not os.path.isfile(path):
            return self._json(404, {"error": "not found", "path": path})
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            data = f.read()
        self._send(200, data, ctype)

    # -------------------------------------------------------------- routing
    def do_GET(self):
        try:
            self._route_get()
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        try:
            self._route_post()
        except FileNotFoundError as exc:
            self._json(404, {"error": f"no such job: {exc}"})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _route_get(self):
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            return self._file(os.path.join(PANEL_DIR, "index.html"))
        if path.startswith("/static/"):
            return self._file(_safe_join(PANEL_DIR, path[len("/static/"):]))
        if path == "/api/jobs":
            return self._json(200, {"jobs": jobstore.list_jobs()})
        if path.startswith("/api/jobs/"):
            job_id = path[len("/api/jobs/"):].strip("/")
            job = jobstore.get_job(job_id)
            if not job:
                return self._json(404, {"error": "no such job", "job_id": job_id})
            return self._json(200, job)
        if path.startswith("/files/"):
            rest = path[len("/files/"):]
            job_id, _, rel = rest.partition("/")
            if not job_id or not rel:
                return self._json(400, {"error": "usage: /files/<job>/<path>"})
            jdir = jobstore._job_dir(job_id)
            if not os.path.isdir(jdir):
                return self._json(404, {"error": "no such job"})
            return self._file(_safe_join(jdir, rel))
        if path == "/api/health":
            return self._json(200, {"ok": True, "jobs": len(jobstore.list_jobs())})
        return self._json(404, {"error": "unknown route", "path": path})

    def _route_post(self):
        path = unquote(urlparse(self.path).path)
        body = self._body()
        if path == "/api/jobs":
            title = (body.get("title") or "").strip() or None
            image_path = body.get("image_path")
            job_id = jobstore.create_job(image_path=image_path, title=title,
                                         session_id=body.get("session_id"),
                                         notes=body.get("notes"))
            return self._json(201, {"job_id": job_id})
        if path.startswith("/api/jobs/"):
            rest = path[len("/api/jobs/"):].strip("/")
            job_id, _, action = rest.partition("/")
            if action == "approval":
                data = jobstore.approve(job_id, body.get("decision", "accept"), body.get("text", ""))
                return self._json(200, {"ok": True, "approval": data})
            if action == "description":
                text = jobstore.set_description(job_id, body.get("text", ""))
                return self._json(200, {"ok": True, "chars": len(text)})
            if action == "open":
                jdir = jobstore._job_dir(job_id)
                if not os.path.isdir(jdir):
                    return self._json(404, {"error": "no such job"})
                ok, method, error = open_folder(jdir)
                # always 200: the panel needs the path either way (to show/copy it)
                return self._json(200, {"ok": ok, "method": method, "path": jdir,
                                        "error": error})
        return self._json(404, {"error": "unknown route", "path": path})


def main():
    ap = argparse.ArgumentParser(description="Garment Studio panel server")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--open", action="store_true", help="open a browser tab")
    args = ap.parse_args()

    os.makedirs(jobstore.JOBS_DIR, exist_ok=True)
    try:
        srv = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        print(f"[studio] cannot bind {args.host}:{args.port}: {exc}", flush=True)
        print("[studio] is another instance already running? try --port 8766", flush=True)
        raise SystemExit(2)
    url = f"http://{args.host}:{args.port}/"
    print(f"[studio] panel on {url}", flush=True)
    print(f"[studio] jobs dir {jobstore.JOBS_DIR}", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[studio] bye", flush=True)
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
