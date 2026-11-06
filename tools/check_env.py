#!/usr/bin/env python
"""CG-WIN: one-screen report of what this checkout will actually use.

    .venv/Scripts/python.exe tools/check_env.py

Prints the interpreter, the CUDA device, the library versions that matter and
where each big file is expected to be (D:/ChatGarment_data by default).
Nothing is loaded onto the GPU, so it takes ~5 s.
"""
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

DATA_ROOT = os.environ.get('CG_DATA_ROOT', 'D:/ChatGarment_data')
CHECKPOINT = os.environ.get('CG_CHECKPOINT', os.path.join(DATA_ROOT, 'chatgarment_weights', 'pytorch_model.bin'))
BASE_CONFIG = os.environ.get('CG_BASE_CONFIG', os.path.join(DATA_ROOT, 'models', 'llava-v1.5-7b-config'))
VISION_TOWER = os.environ.get('CG_VISION_TOWER', os.path.join(DATA_ROOT, 'models', 'clip-vit-large-patch14-336'))


def size(path):
    try:
        if os.path.isdir(path):
            n = sum(os.path.getsize(os.path.join(dp, f))
                    for dp, _, fs in os.walk(path) for f in fs)
            return '%.1f MB' % (n / 1e6)
        return '%.2f GB' % (os.path.getsize(path) / 1e9)
    except OSError:
        return '-'


def ok(path):
    return 'OK' if os.path.exists(path) else 'MISSING'


def main():
    print('python      :', sys.version.split()[0], sys.executable)
    print('repo root   :', REPO_ROOT)

    import torch
    print('torch       :', torch.__version__, '| cuda build', torch.version.cuda)
    avail = torch.cuda.is_available()
    print('cuda        :', 'available' if avail else 'NOT available')
    if avail:
        cap = torch.cuda.get_device_capability(0)
        props = torch.cuda.get_device_properties(0)
        print('device      :', torch.cuda.get_device_name(0), '| sm_%d%d' % cap,
              '| %.1f GiB' % (props.total_memory / 2**30))
        free, total = torch.cuda.mem_get_info(0)
        print('vram        : %.2f GiB free of %.2f GiB' % (free / 2**30, total / 2**30))

    # cairosvg needs libcairo-2.dll on the DLL search path; the repo bundles one
    # under pygarment/pattern/cairo_dlls (llava/win_compat.py registers it too).
    try:
        from llava import win_compat
        win_compat.enable_cairo_dlls()
    except Exception as exc:                          # noqa: BLE001
        print('cairo setup : failed (%s)' % exc)

    for mod in ('transformers', 'peft', 'accelerate', 'bitsandbytes', 'numpy', 'cv2',
                'PIL', 'yaml', 'cairosvg', 'deepspeed'):
        try:
            m = __import__(mod)
            print('%-12s:' % mod, getattr(m, '__version__', 'installed'))
        except Exception as exc:                      # noqa: BLE001 - report, do not raise
            print('%-12s:' % mod, 'absent (%s)' % type(exc).__name__)

    print()
    print('big files (CG_DATA_ROOT=%s)' % DATA_ROOT)
    for label, path in (('checkpoint', CHECKPOINT), ('llava config', BASE_CONFIG),
                        ('CLIP tower', VISION_TOWER)):
        print('  %-13s %-6s %-9s %s' % (label, ok(path), size(path), path))

    assets = os.path.join(REPO_ROOT, 'assets')
    print('  %-13s %-6s %-9s %s' % ('assets', ok(assets), size(assets) if os.path.exists(assets) else '-',
                                   'junction -> ' + os.path.realpath(assets) if os.path.exists(assets) else assets))
    gc = os.path.join(REPO_ROOT, 'repos', 'GarmentCodeRC-main')
    print('  %-13s %-6s %-9s %s' % ('GarmentCode', ok(gc), size(gc) if os.path.exists(gc) else '-', gc))
    print()
    print('cairo DLLs  :', 'found' if os.path.isdir(os.path.join(gc, 'pygarment', 'pattern', 'cairo_dlls')) else 'absent')
    return 0


if __name__ == '__main__':
    sys.exit(main())
