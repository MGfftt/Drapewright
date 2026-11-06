"""The model-side CLI for Garment Studio: everything the assistant does to one job.

The panel (studio/panel) is for the human; this CLI is for the assistant.  Both touch
the same folder (studio/jobs/<id>/), so neither side needs the other to be alive.

    python -m studio.agent new --image <png> --title "抹胸短裙" [--session <id>]
    python -m studio.agent describe <job_id> --file desc.txt      # or --text "..."
    python -m studio.agent wait <job_id> [--stage approved] [--timeout 900]
    python -m studio.agent run <job_id> [--frames 96] [--quality 8]
    python -m studio.agent show <job_id>
    python -m studio.agent list

Exit codes: 0 ok, 1 usage/not found, 2 design rejected, 3 pattern rejected,
4 simulation failed, 5 timeout while waiting.
"""
import argparse
import json
import os
import subprocess
import sys
import time

from studio import jobs as jobstore
from studio.core import paths as pathmod

REPO_ROOT = jobstore.REPO_ROOT


def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def _job(job_id):
    job = jobstore.get_job(job_id, include_log=False)
    if not job:
        print(f"no such job: {job_id}", file=sys.stderr)
        raise SystemExit(1)
    return job


def cmd_new(args):
    image = os.path.abspath(args.image) if args.image else None
    if image and not os.path.isfile(image):
        print(f"image not found: {image}", file=sys.stderr)
        raise SystemExit(1)
    job_id = jobstore.create_job(image_path=image, title=args.title,
                                 session_id=args.session, notes=args.notes)
    jobstore.log(job_id, "assistant created the job" + (f" from {os.path.basename(image)}" if image else ""))
    _print({"job_id": job_id, "stage": jobstore.stage(job_id), "image": image})


def cmd_describe(args):
    job = _job(args.job_id)
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = args.text or ""
    if not text.strip():
        print("empty description", file=sys.stderr)
        raise SystemExit(1)
    jobstore.set_description(args.job_id, text)
    _print({"job_id": args.job_id, "stage": jobstore.stage(args.job_id), "chars": len(text)})


def cmd_show(args):
    job = _job(args.job_id)
    keep = ("job_id", "stage", "title", "description", "approval", "design", "result",
            "images", "files", "log_tail")
    _print({k: job.get(k) for k in keep if job.get(k) is not None})


def cmd_template(args):
    """Print a design skeleton for a garment block: every float path, all at 0.5."""
    with open(args.file, "r", encoding="utf-8") as f:
        doc = json.load(f)
    garment = doc.get("garment", doc)
    per_part = pathmod.ordered_paths(garment)
    floats = {}
    for part_paths in per_part.values():
        for path in part_paths:
            floats[path] = 0.5
    _print({"schema": "gcstudio/design/1",
            "label": "fill in: what the human asked for",
            "garment": garment,
            "floats": floats,
            "note": "0.5 is a neutral placeholder - replace every value; keep the keys exactly"})
    return 0


def cmd_list(args):
    rows = jobstore.list_jobs()
    _print([{"job_id": j["job_id"], "stage": j["stage"], "title": j["title"],
             "created_at": j["created_at"]} for j in rows])


def cmd_wait(args):
    """Block until the human has approved / edited the description (or timeout)."""
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        stage = jobstore.stage(args.job_id)
        if stage in ("approved", "designed", "packaged", "simulated") or (
                stage == "described" and args.stage == "described"):
            approval = jobstore.get_job(args.job_id, include_log=False).get("approval")
            _print({"job_id": args.job_id, "stage": stage, "approval": approval})
            return 0
        if stage == "failed":
            _print({"job_id": args.job_id, "stage": stage, "error": "job failed"})
            return 4
        time.sleep(2)
    print(f"timeout after {args.timeout}s waiting for approval of {args.job_id}", file=sys.stderr)
    return 5


def cmd_run(args):
    cmd = [sys.executable, "-m", "studio.job_runner", args.job_id,
           "--frames", str(args.frames), "--quality", str(args.quality)]
    if args.no_sim:
        cmd.append("--no-sim")
    proc = subprocess.run(cmd, cwd=REPO_ROOT)
    if proc.returncode == 0:
        job = jobstore.get_job(args.job_id, include_log=False)
        _print({"job_id": args.job_id, "stage": job["stage"], "result": job.get("result")})
    return proc.returncode


def main(argv=None):
    ap = argparse.ArgumentParser(prog="studio.agent", description="assistant-side CLI for Garment Studio")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="create a job (copies the image into the job folder)")
    p.add_argument("--image")
    p.add_argument("--title", default="未命名款式")
    p.add_argument("--session", default=None, help="DSH session id, so the plugin can relay approvals")
    p.add_argument("--notes", default="")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("describe", help="write description.txt (shows up in the panel)")
    p.add_argument("job_id")
    p.add_argument("--file")
    p.add_argument("--text")
    p.set_defaults(func=cmd_describe)

    p = sub.add_parser("template", help="skeleton design (all float paths) for a garment block")
    p.add_argument("--file", required=True, help="JSON with a 'garment' block (or a bare garment block)")
    p.set_defaults(func=cmd_template)

    p = sub.add_parser("show", help="dump one job as JSON")
    p.add_argument("job_id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("list", help="list jobs")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("wait", help="wait until the human approved/edited the description")
    p.add_argument("job_id")
    p.add_argument("--stage", default="approved")
    p.add_argument("--timeout", type=int, default=900)
    p.set_defaults(func=cmd_wait)

    p = sub.add_parser("run", help="build the package and drape it in Blender")
    p.add_argument("job_id")
    p.add_argument("--frames", type=int, default=96)
    p.add_argument("--quality", type=int, default=8)
    p.add_argument("--no-sim", action="store_true")
    p.set_defaults(func=cmd_run)

    args = ap.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
