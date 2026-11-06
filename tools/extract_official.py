"""Pull the RAW= payload out of the demo's raw_qN.txt debug dumps."""
import sys

src, dst = sys.argv[1], sys.argv[2]
for line in open(src, encoding="utf-8").read().splitlines():
    if line.startswith("RAW="):
        open(dst, "w", encoding="utf-8").write(line[4:])
        print("wrote", dst, len(line) - 4, "chars")
        break
else:
    raise SystemExit("no RAW= line in " + src)
