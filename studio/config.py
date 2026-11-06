"""Where the heavy binaries live (Blender, the project venv, the repo root).

Override with environment variables when the machine layout changes:
    GCSTUDIO_BLENDER=/path/to/blender.exe
    GCSTUDIO_PYTHON=/path/to/python.exe
"""
import glob
import os
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_blender():
    env = os.environ.get("GCSTUDIO_BLENDER")
    if env and os.path.isfile(env):
        return env
    on_path = shutil.which("blender")
    if on_path:
        return on_path
    patterns = [
        os.path.join(os.path.expanduser("~"), "Desktop", "blender*", "blender.exe"),
        r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
        r"C:\Program Files\Blender Foundation\blender*.exe",
    ]
    found = []
    for pat in patterns:
        found.extend(glob.glob(pat))
    found = [f for f in found if os.path.isfile(f)]
    if found:
        found.sort()
        return found[-1]
    return None


def venv_python():
    cand = os.path.join(REPO_ROOT, ".venv", "Scripts", "python.exe")
    if os.name != "nt":
        cand = os.path.join(REPO_ROOT, ".venv", "bin", "python")
    return cand if os.path.isfile(cand) else sys.executable


if __name__ == "__main__":
    print("repo   ", REPO_ROOT)
    print("python ", venv_python())
    print("blender", find_blender() or "NOT FOUND")
