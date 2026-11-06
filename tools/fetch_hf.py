#!/usr/bin/env python
"""Parallel, resumable downloader for large HuggingFace files through hf-mirror.com.

hf-mirror answers resolve/ with a 302 to a signed xet-bridge CDN URL and rate limits
a single long connection (HTTP 429). Requesting the redirect with ?download=true and
then issuing many ranged GETs against the signed URL reaches ~8 MB/s and can resume.
"""
import argparse, hashlib, os, shutil, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
ENDPOINT = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")
HDR = {"User-Agent": UA}


def api_json(url):
    r = requests.get(url, headers=HDR, timeout=90)
    r.raise_for_status()
    return r.json()


def file_meta(repo, path, repo_type="model"):
    kind = "datasets" if repo_type == "dataset" else "models"
    data = api_json(ENDPOINT + "/api/" + kind + "/" + repo + "/tree/main?recursive=true")
    for e in data:
        if e.get("path") == path:
            lfs = e.get("lfs") or {}
            return lfs.get("size") or e.get("size"), lfs.get("oid")
    raise SystemExit("file not found in repo tree: " + path)


def signed_url(repo, path, repo_type="model", tries=6):
    kind = "datasets/" if repo_type == "dataset" else ""
    base = ENDPOINT + "/" + kind + repo + "/resolve/main/" + path
    last = None
    for i in range(tries):
        try:
            r = requests.head(base + "?download=true", headers=HDR,
                              allow_redirects=False, timeout=60)
            if r.status_code in (301, 302, 303, 307, 308):
                return r.headers["Location"]
            last = "HTTP " + str(r.status_code)
        except Exception as e:
            last = repr(e)
        time.sleep(2 + 2 * i)
    raise SystemExit("could not resolve signed url: " + str(last))


def download(repo, path, out, conns=16, chunk_mb=48, repo_type="model", sha256=None):
    size, meta_sha = file_meta(repo, path, repo_type)
    sha256 = sha256 or meta_sha
    out = os.path.abspath(out)
    d = os.path.dirname(out)
    if d:
        os.makedirs(d, exist_ok=True)
    parts = out + ".parts"
    os.makedirs(parts, exist_ok=True)
    chunk = chunk_mb * 1024 * 1024
    nchunks = (size + chunk - 1) // chunk
    print("file: " + path)
    print("size: %.3f GB  chunks: %d x %d MB" % (size / 1e9, nchunks, chunk_mb))
    print("sha256: " + str(sha256))
    sys.stdout.flush()

    def part(i):
        return os.path.join(parts, "%05d" % i)

    def want(i):
        return min(chunk, size - i * chunk)

    todo = []
    for i in range(nchunks):
        if not (os.path.exists(part(i)) and os.path.getsize(part(i)) == want(i)):
            todo.append(i)
    print("already done: %d / %d" % (nchunks - len(todo), nchunks))
    sys.stdout.flush()

    def get(idx):
        start = idx * chunk
        end = start + want(idx) - 1
        dst = part(idx)
        for attempt in range(8):
            try:
                url = signed_url(repo, path, repo_type)
                r = requests.get(url, headers=HDR, stream=True, timeout=(30, 300))
                if r.status_code not in (200, 206):
                    raise RuntimeError("HTTP " + str(r.status_code))
                with open(dst, "wb") as f:
                    for blk in r.iter_content(1 << 20):
                        f.write(blk)
                r.close()
                if os.path.getsize(dst) == end - start + 1:
                    return idx, True
            except Exception:
                time.sleep(2 + attempt)
        return idx, False

    t0 = time.time()
    failed = []
    done = nchunks - len(todo)
    with ThreadPoolExecutor(max_workers=conns) as ex:
        futs = [ex.submit(get, i) for i in todo]
        for fut in as_completed(futs):
            idx, ok = fut.result()
            done += 1
            if not ok:
                failed.append(idx)
            if done % 5 == 0 or not ok:
                el = max(time.time() - t0, 1.0)
                got = 0
                for f in os.listdir(parts):
                    got += os.path.getsize(os.path.join(parts, f))
                print("progress %.2f/%.2f GB  %.1f MB/s  failed=%d"
                      % (got / 1e9, size / 1e9, got / el / 1e6, len(failed)))
                sys.stdout.flush()
    if failed:
        print("RETRY NEEDED: %d chunks failed" % len(failed))
        return 2

    print("assembling + hashing ...")
    sys.stdout.flush()
    h = hashlib.sha256()
    with open(out, "wb") as fo:
        for i in range(nchunks):
            with open(part(i), "rb") as fi:
                while True:
                    b = fi.read(1 << 22)
                    if not b:
                        break
                    fo.write(b)
                    h.update(b)
    if sha256 and h.hexdigest() != sha256:
        print("SHA MISMATCH got " + h.hexdigest() + " want " + sha256)
        return 3
    shutil.rmtree(parts, ignore_errors=True)
    print("DONE " + out + " (%.3f GB) in %.0f s" % (os.path.getsize(out) / 1e9, time.time() - t0))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--path", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--conns", type=int, default=16)
    ap.add_argument("--chunk-mb", type=int, default=48)
    ap.add_argument("--repo-type", default="model")
    a = ap.parse_args()
    sys.exit(download(a.repo, a.path, a.out, a.conns, a.chunk_mb, a.repo_type))
