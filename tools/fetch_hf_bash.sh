#!/usr/bin/env bash
# Parallel, resumable downloader for big HF files through hf-mirror.com (bash+curl).
# usage: fetch_hf_bash.sh <repo> <path-in-repo> <out-file> [conns] [chunk_mb]
set -uo pipefail
REPO="$1"; RPATH="$2"; OUT="$3"; CONNS="${4:-16}"; CHUNK_MB="${5:-48}"; REPO_TYPE="${6:-model}"
if [ "$REPO_TYPE" = "dataset" ]; then KIND="datasets"; PREFIX="datasets/"; else KIND="models"; PREFIX=""; fi
EP="${HF_ENDPOINT:-https://hf-mirror.com}"
PY="${PYTHON:-./.venv/Scripts/python.exe}"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"

META=$(curl -s -m 180 -A "$UA" "$EP/api/$KIND/$REPO/tree/main?recursive=true" | "$PY" -c 'import sys,json
p=sys.argv[1]
d=json.load(sys.stdin)
for e in d:
    if e.get("path")==p:
        lfs=e.get("lfs") or {}
        print(lfs.get("size") or e.get("size"), lfs.get("oid") or "-")
        break' "$RPATH")
SIZE=$(echo "$META" | cut -d" " -f1)
SHA=$(echo "$META" | cut -d" " -f2)
if [ -z "${SIZE:-}" ]; then echo "FATAL: no metadata for $RPATH"; exit 1; fi
CHUNK=$((CHUNK_MB*1024*1024))
N=$(( (SIZE + CHUNK - 1) / CHUNK ))
PARTS="$OUT.parts"
mkdir -p "$PARTS"
echo "repo=$REPO"
echo "file=$RPATH"
echo "size=$SIZE bytes ($((SIZE/1000000)) MB) sha256=$SHA chunks=$N x ${CHUNK_MB}MB"

dl() {
  local i=$1
  local start=$((i*CHUNK))
  local want=$(( SIZE - i*CHUNK ))
  [ "$want" -gt "$CHUNK" ] && want=$CHUNK
  local end=$((start+want-1))
  local f
  f=$(printf "%s/%06d" "$PARTS" "$i")
  local loc sz a
  for a in 1 2 3 4 5 6 7 8; do
    loc=$(curl -sI -m 90 -A "$UA" "$EP/$PREFIX$REPO/resolve/main/$RPATH?download=true" | sed -n "s/^[Ll]ocation: //p" | tr -d "\r")
    if [ -z "$loc" ]; then sleep 2; continue; fi
    curl -s -m 2400 -A "$UA" -r "$start-$end" -o "$f" "$loc"
    sz=$(stat -c%s "$f" 2>/dev/null || echo 0)
    if [ "$sz" = "$want" ]; then echo "ok $i"; return 0; fi
    sleep 2
  done
  echo "FAIL $i"
  return 1
}
export -f dl
export CHUNK SIZE PARTS EP REPO RPATH UA PREFIX

missing() {
  local i want f
  for ((i=0;i<N;i++)); do
    want=$(( SIZE - i*CHUNK ))
    [ "$want" -gt "$CHUNK" ] && want=$CHUNK
    f=$(printf "%s/%06d" "$PARTS" "$i")
    if [ ! -f "$f" ] || [ "$(stat -c%s "$f")" != "$want" ]; then echo "$i"; fi
  done
}

TODO=$(missing | wc -l)
echo "missing chunks: $TODO / $N"
if [ "$TODO" -gt 0 ]; then
  missing | xargs -P "$CONNS" -I{} bash -c "dl {}"
fi

LEFT=$(missing | wc -l)
if [ "$LEFT" -gt 0 ]; then echo "STILL MISSING: $LEFT chunks, rerun to resume"; exit 2; fi

echo "assembling $OUT ..."
TMPOUT="$OUT.assembling"
cat "$PARTS"/* > "$TMPOUT" || { echo "assemble failed"; exit 3; }
GOT=$(stat -c%s "$TMPOUT")
if [ "$GOT" != "$SIZE" ]; then echo "SIZE MISMATCH got=$GOT want=$SIZE"; exit 4; fi
if [ "$SHA" != "-" ]; then
  ACT=$(sha256sum "$TMPOUT" | cut -d" " -f1)
  if [ "$ACT" != "$SHA" ]; then echo "SHA MISMATCH got=$ACT want=$SHA"; exit 5; fi
  echo "sha256 verified"
fi
mv -f "$TMPOUT" "$OUT"
rm -rf "$PARTS"
echo "DONE $OUT"
