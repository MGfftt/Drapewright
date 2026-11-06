#!/usr/bin/env bash
# Download a list of (mostly small) files from a HF repo through hf-mirror.com.
# usage: fetch_hf_files.sh <repo> <dest-dir> <path-in-repo> [<path> ...]
# Uses a single stream per file (fine for <100 MB); for big files use fetch_hf_bash.sh.
# Set REPO_TYPE=dataset for datasets.
set -uo pipefail
REPO="$1"; DEST="$2"; shift 2
if [ "${REPO_TYPE:-model}" = "dataset" ]; then KIND="datasets"; PREFIX="datasets/"; else KIND="models"; PREFIX=""; fi
EP="${HF_ENDPOINT:-https://hf-mirror.com}"
PY="${PYTHON:-D:/models/python311/python.exe}"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
mkdir -p "$DEST"
TREE=$(curl -s -m 180 -A "$UA" "$EP/api/$KIND/$REPO/tree/main?recursive=true")
rc=0
for P in "$@"; do
  WANT=$(printf '%s' "$TREE" | "$PY" -c 'import sys,json
p=sys.argv[1]
try: d=json.load(sys.stdin)
except Exception: d=[]
for e in d:
    if e.get("path")==p:
        lfs=e.get("lfs") or {}
        print(lfs.get("size") or e.get("size") or 0); break
else: print(-1)' "$P")
  if [ "$WANT" = "-1" ] || [ -z "$WANT" ]; then echo "SKIP (not in repo): $P"; continue; fi
  OUT="$DEST/$P"
  mkdir -p "$(dirname "$OUT")"
  GOT=0
  [ -f "$OUT" ] && GOT=$(stat -c%s "$OUT")
  if [ "$GOT" = "$WANT" ]; then echo "have $P ($WANT B)"; continue; fi
  for a in 1 2 3; do
    curl -sL -m 900 -A "$UA" -o "$OUT" "$EP/$PREFIX$REPO/resolve/main/$P?download=true"
    GOT=$(stat -c%s "$OUT" 2>/dev/null || echo 0)
    if [ "$GOT" = "$WANT" ]; then echo "ok $P ($WANT B)"; break; fi
    echo "retry $a: $P got=$GOT want=$WANT"; sleep 3
  done
  if [ "$GOT" != "$WANT" ]; then echo "FAILED $P got=$GOT want=$WANT"; rc=1; fi
done
exit $rc
