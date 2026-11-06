# ChatGarment on Windows - RTX 5060 Laptop (sm_120), 8 GB VRAM

Status: **end-to-end verified** - one photo goes in, a sewing pattern comes out.
Verified 2026-10-27 on `example_data/example_imgs`-style input (a black sleeveless
A-line midi dress):

```
photo (736x981) -> Q0: garment description JSON
                -> Q1: sewing-pattern design JSON with 26 x [SEG] float slots
                -> 4-bit LLaVA decodes the [SEG] hidden states -> 26 floats
                -> GarmentCode assembles the pattern
                -> valid_garment_wholebody_pattern.svg / .png  (508x190 px)
```

```
$ bash win/run_eval_imggen.sh runs/win_1img          # ~5 min, 4.5 min of it is loading
...
[CG-WIN] quantize_4bit: 224 linears -> NF4, model on cuda:0 (4.43 GiB allocated)
[CG-WIN] question 0: 78 new tokens in 12.0 s (6.48 tok/s)
[CG-WIN] question 1: 474 new tokens in 29.3 s (16.15 tok/s)
[CG-WIN] float mapping: 26 [SEG] predictions -> the 26 float paths of the emitted components
Success! Garment wholebody saved to ./runs/.../valid_garment_win_1img/<image-id>/valid_garment_wholebody
```

---

## 0. 中文速览

**跑一张图**（图片放一个文件夹里，png/jpg 都行）：

```bash
cd /c/Users/41239/Desktop/科研/ChatGarment-main
bash win/run_eval_imggen.sh example_data/example_imgs     # 或你自己的图片文件夹
```

结果在 `runs/<权重名>/<图片文件夹>_img_recon/vis_new/valid_garment_<id>/`：
剪纸样的 `*_pattern.svg` / `*_pattern.png`、可再编辑的 `design.yaml`、
以及给 3D 仿真用的 `*_specification.json`，模型原始输出在 `output.txt`。

**全部删除**（本项目和它产生的一切，包括 D 盘的 19 GB 权重）：

```powershell
powershell -ExecutionPolicy Bypass -File win\cleanup.ps1           # 只看会删什么
powershell -ExecutionPolicy Bypass -File win\cleanup.ps1 -Execute  # 真删
```
删完约回收 **26 GB**（D 盘 19.1 GB + 仓库内 7.3 GB）。不会动源码、不会动系统。

**改代码**：所有 Windows 改动都标了 `CG-WIN`，可 diff、可回退：

```bash
grep -rn 'CG-WIN' --include='*.py' --include='*.sh' .   # 我改了什么
git log --oneline                                       # e66b2e4 上游原样 + 后续补丁 commit
git diff e66b2e4 --stat                                 # 相对上游的全部改动
```

---

## 1. TL;DR

```bash
cd /c/Users/41239/Desktop/科研/ChatGarment-main

# full run: loads the 15 GB checkpoint, quantises it to 4-bit, writes patterns
bash win/run_eval_imggen.sh example_data/example_imgs

# cap the length (e.g. a 30-token smoke test: the JSON is truncated, the pattern
# parser will complain - that is expected, only the plumbing is being tested)
CG_MAX_NEW_TOKENS=32 bash win/run_eval_imggen.sh runs/win_1img
```

Outputs: `runs/<checkpoint-name>/<image-folder>_img_recon/vis_new/`.

All 10 images of `example_data/example_imgs` were processed in one process (~13 min,
the 15 GB load is paid once) -> **15 patterns**; the released checkpoint decides per image
whether the outfit is one piece or two:

| image | shape | `[SEG]` floats | patterns |
|---|---|---|---|
| `1aee14a8…` | upper + lower | 24 + 6 | 2 |
| `1dde6afe…` | upper + lower | 26 + 9 | 2 |
| `62bb809f…` | upper + lower | 19 + 13 | 2 |
| `6fe14e1f…` | wholebody | 33 | 1 |
| `72b08642…` | wholebody | 33 | 1 |
| `80141ce7…` | wholebody | 26 | 1 (the dress shown above) |
| `8e3c458d…` | upper + lower | 28 + 7 | 2 |
| `c2b582eb…` | upper + lower | 19 + 7 | 2 |
| `d77c6f5d…` | upper + lower | 24 + 9 | 1 - the lower one is a `Pants` + `CuffBand` whose predicted `cuff_len` sits at the bottom of its range; GarmentCode refuses that degenerate geometry and the item is reported as a warning (see 6.3) |
| `e918651c…` | wholebody | 28 | 1 |

A batch of N images therefore takes ~5 min + ~50 s per image.

The working reference mode is **image -> JSON garment description -> sewing pattern**
(`scripts/evaluate_garment_v2_imggen_1float.py`, a 2-step chain of thought). It needs no
OpenAI key and no DeepSpeed. Everything is inside this folder or `D:/ChatGarment_data`;
nothing was installed system-wide (no conda env, no registry changes, no global pip
packages, no CUDA toolkit, no Visual Studio components).

---

## 2. Where everything lives (and what is safe to delete)

| Path | Size (dry run) | What it is | Deletable? |
|---|---|---|---|
| `ChatGarment-main/` | ~200 MB source | this repo (upstream + `CG-WIN` patches) | it *is* the project |
| `.venv/` | 6.4 GB | Python 3.11.9 venv: torch 2.7.1+cu128, transformers, bitsandbytes, cairo deps... | yes, recreate (section 3) |
| `repos/GarmentCodeRC-main/` | 82 MB | GarmentCode (pygarment) parser + `assets/` pattern data | yes, recreate (3.5) |
| `assets` (junction) | - | -> `repos/GarmentCodeRC-main/assets` | yes, recreate (3.5) |
| `win/` | - | **all Windows-specific code/docs** (this file, runner, cleanup) | no |
| `llava/win_compat.py` | 22 KB | compatibility layer (4-bit quantiser, flexible load, memory) | no |
| `tools/render_pattern.py` | 6 KB | design.yaml -> pattern, **no model, ~1 s** (section 5.1) | no |
| `runs/`, `Logs/` | grows | generated patterns + run logs | yes |
| `.pip-cache/`, `.tmp/` | 445 MB + 334 MB | pip cache / TMP for torch and tokenizer | yes |
| `torchinductor_<user>/` | - | torch.compile cache | yes |
| `.git/` | 8.7 MB | baseline commit + patch commits | yes (loses the history only) |
| `D:/ChatGarment_data/` | 19.1 GB | **all big files**: checkpoint, CLIP, llava config, wheels, pip cache | yes (3.4) |

`win/cleanup.ps1` encodes exactly this list (dry run by default). Removing the repo folder
plus `D:/ChatGarment_data` returns the machine to its previous state.

---

## 3. How it was installed (reproducible from scratch)

### 3.1 Python 3.11
Python **3.11.9** - the newest interpreter on this box that has a cu128 PyTorch wheel
(upstream asks for 3.10 via conda, which is not installed here).

```bash
cd /c/Users/41239/Desktop/科研/ChatGarment-main
D:/models/python311/python.exe -m venv .venv
```

### 3.2 PyTorch for sm_120 (RTX 5060 Laptop)
`download.pytorch.org` is unreachable from this network and the upstream pin
(`torch==2.1.2`) has no kernel for compute capability 12.0 (`torch.cuda.is_available()`
returns False / 'no kernel image is available'). The wheels came from the SJTU mirror:

```bash
# D:/ChatGarment_data/wheels/:
#   torch-2.7.1+cu128-cp311-cp311-win_amd64.whl        (3.27 GB)
#   torchvision-0.22.1+cu128-cp311-cp311-win_amd64.whl (7.6 MB)
.venv/Scripts/python.exe -m pip install \
  --find-links /d/ChatGarment_data/wheels \
  --index-url https://mirrors.aliyun.com/pypi/simple/ \
  "torch==2.7.1+cu128" "torchvision==0.22.1+cu128"
```

Verified: `torch 2.7.1+cu128 | cuda True | cap (12, 0) | NVIDIA GeForce RTX 5060 Laptop GPU`.

### 3.3 Python dependencies
```bash
.venv/Scripts/python.exe -m pip install \
  --index-url https://mirrors.aliyun.com/pypi/simple/ -r win/requirements-win.txt
```

`win/requirements-win.txt` keeps the upstream pins where they still work (transformers 4.37.2,
peft 0.10.0, accelerate 0.32.0, tokenizers 0.15.1, numpy 1.26.4) and deviates only where
Windows/sm_120 forces it: `opencv-python-headless==4.10.0.84` (newer versions force numpy>=2),
`huggingface_hub==0.23.5` (accelerate 0.32 requires >=0.21), **`bitsandbytes==0.50.2`**
(section 4). DeepSpeed and flash-attn are **not** installed (no Windows wheels); the code was
patched to run without them.

`cairosvg` is in the list because GarmentCode writes the pattern **PNG** through
`pygarment/pattern/wrappers.py` (`cairosvg.svg2png`); the SVG is written by GarmentCode itself.
On Windows a bare `pip install cairosvg` is not enough - `import cairosvg` then fails with
`cannot load library 'libcairo-2.dll'`. The repo ships the DLLs in
`repos/GarmentCodeRC-main/pygarment/pattern/cairo_dlls`, and
`llava/win_compat.py::enable_cairo_dlls()` registers that folder (called at import time by
`llava/garment_utils_v2.py` and by `tools/check_env.py`), so importing the pattern module
before `cairosvg` is enough. `tools/check_env.py` proves it: it prints `cairosvg: 2.9.1`.

### 3.4 Big files (`D:/ChatGarment_data`)

All downloaded from **hf-mirror.com** (huggingface.co is blocked here: curl exits 35/000).
`tools/fetch_hf_bash.sh` is a resumable parallel downloader for multi-GB files:

```bash
bash tools/fetch_hf_bash.sh <hf-repo> <path/in/repo> <local-file> [conns] [chunk_mb] [model|dataset]
```

| File | Size | Source |
|---|---|---|
| `chatgarment_weights/pytorch_model.bin` | 14.99 GB | `sy000/chatgarment_extrafiles` : `try_lr1e_4_wholebody_pose_v2_detailT2_upd_possibleDebug_v3_garmentcontrol_addFTdata/pytorch_model.bin` |
| `models/clip-vit-large-patch14-336/` | 1.7 GB | `openai/clip-vit-large-patch14-336` |
| `models/llava-v1.5-7b-config/` | 1 MB | `liuhaotian/llava-v1.5-7b` - **config.json + tokenizer only** |
| `wheels/*.whl` | 3.3 GB | mirror.sjtu.edu.cn/pytorch-wheels/cu128 |

```bash
export CG_DATA_ROOT=D:/ChatGarment_data          # default, override if you move things
bash tools/fetch_hf_bash.sh sy000/chatgarment_extrafiles \
  try_lr1e_4_wholebody_pose_v2_detailT2_upd_possibleDebug_v3_garmentcontrol_addFTdata/pytorch_model.bin \
  $CG_DATA_ROOT/chatgarment_weights/pytorch_model.bin 20 48
bash tools/fetch_hf_files.sh openai/clip-vit-large-patch14-336 $CG_DATA_ROOT/models/clip-vit-large-patch14-336 \
  config.json preprocessor_config.json tokenizer.json vocab.json merges.txt tokenizer_config.json \
  special_tokens_map.json pytorch_model.bin
bash tools/fetch_hf_files.sh liuhaotian/llava-v1.5-7b $CG_DATA_ROOT/models/llava-v1.5-7b-config \
  config.json generation_config.json tokenizer.model tokenizer_config.json special_tokens_map.json
```

Notes
* The official SharePoint link in `docs/Installation.md` is **dead** (HTTP 302 to
  `PolicyViolationThrottle.htm`, 'file scheduled for deletion'), and the `..._v4_final` folder
  named there does not exist on the mirror. The variant above is the closest released one
  (`v3_garmentcontrol + addFTdata`). It loads with **0 missing / 0 unexpected** keys against
  this code, which is the strongest available check of that choice (section 6, `last_dim=1`).
* The 13.6 GB LLaVA base weights are **not** needed: the ChatGarment checkpoint is a full PEFT
  state_dict that contains the backbone, `mm_projector`, `float_layer` **and** the whole CLIP
  vision tower. Only `config.json` + tokenizer are taken from `llava-v1.5-7b`, and the model
  is built from that config (`GarmentGPTFloat50ForCausalLM(config, ...)`).
* The other checkpoint on the mirror, `try_lr1e_4_wholebody_pose_v2_detailT2_1float_upd/`
  (14.99 GB) is **not** downloaded; see section 6 for why it might be the one upstream's
  hard-coded 76-float path list was written for.

### 3.5 GarmentCode (sewing-pattern parser) + assets junction
```bash
curl -L -o repos/gcr.zip https://codeload.github.com/biansy000/GarmentCodeRC/zip/refs/heads/main
cd repos && unzip -q gcr.zip && cd ..
cp repos/GarmentCodeRC-main/system.template.json repos/GarmentCodeRC-main/system.json
# Windows junction instead of the upstream  ln -s <GarmentCodeRC>/assets assets
powershell -NoProfile -Command "New-Item -ItemType Junction -Path 'assets' -Target 'repos/GarmentCodeRC-main/assets'"
```

Notes
* `git clone` over HTTPS fails on this network (`schannel: server closed abruptly
  (missing close_notify)`); the codeload ZIP works.
* A junction created from cmd with a forward-slash path (`mklink /J C:/cg <path>`) produced a
  **broken** link; `New-Item -ItemType Junction` with the real path is fine.
* `assets/` is git-ignored upstream too, and pygarment resolves its data relative to the
  **current working directory**, so always run from the repo root.

---

## 4. Fitting a 7B VLM into 8 GB of VRAM

Three options were evaluated on the real model:

| Approach | Result |
|---|---|
| bf16 on GPU | 14 GB of weights - OOM on an 8 GB card |
| `accelerate` device map + CPU offload | structurally broken here: accelerate offloads to the `meta` device and re-uploads on every forward; `llava/model/multimodal_encoder/clip_encoder.py:54` then calls `images.to(device)` on a meta module -> `NotImplementedError: Cannot copy out of meta tensor`. Even if fixed it would stream ~13 GB per token. |
| **4-bit NF4 (chosen)** | `llava/win_compat.py::quantize_4bit()` rewrites every decoder `nn.Linear` (including each LoRA `base_layer`) to `bitsandbytes.nn.Linear4bit` (NF4, blocksize 64, bf16 compute, `compress_statistics=True`). **224 linears quantised, 4.43 GiB resident; measured peak over a full run 6881 MiB / 8151 MiB** (the peak happens while the checkpoint is uploaded, not during generation). |

Loading uses `torch.load(..., mmap=True, weights_only=True)`: the 15 GB file is memory-mapped,
not read into RAM, and every tensor is dropped as soon as it has been quantised.

### 4.1 Measured timings (RTX 5060 Laptop, 8 GB; weights on D:)

| Phase | Time |
|---|---|
| python + torch + transformers imports | ~10 s |
| `torch.load` (mmap) + flexible `load_state_dict` of 15 GB | **3 min 37 s** (disk-bound) |
| 4-bit quantisation of 224 linears | 51 s |
| Q0 - garment description (78-164 tokens) | 4.9-15.9 s -> 6.5-16 tok/s |
| Q1 - pattern JSON (474-547 tokens) | 23.8-36.7 s -> 15-20 tok/s |
| GarmentCode assembly + SVG/PNG write | < 1 s |
| per additional image in the same process | ~50 s |
| **total, first image** | **~5 min** (`WALL=294 s`), CPU/GPU idle otherwise |

The 4.5 min load is paid **per process**, not per image: a batch of N images in one run pays
it once. The GPU is only busy during generation (~45-55 s per image).

Because a long unexplained GPU load was explicitly unwanted, every run in this setup was
launched as `timeout -k 20 1200 bash win/run_eval_imggen.sh ...` (20 min hard cap, SIGKILL after
20 s); the runner itself never loops. `CG_MAX_NEW_TOKENS` bounds the length of a single answer.

---

## 5. Running

```bash
bash win/run_eval_imggen.sh <image-folder-with-pngs> [extra eval args...]
```

The script `cd`s to the repo root and invokes `scripts/evaluate_garment_v2_imggen_1float.py`
with the Linux flags translated (no `--deepspeed`, no distributed launcher, `--image_folder ./`,
local paths for the config and the CLIP tower). Environment knobs:

| Variable | Default | Meaning |
|---|---|---|
| `CG_DATA_ROOT` | `D:/ChatGarment_data` | where weights/CLIP live |
| `CG_CHECKPOINT` | `$CG_DATA_ROOT/chatgarment_weights/pytorch_model.bin` | ChatGarment weights |
| `CG_BASE_CONFIG` | `$CG_DATA_ROOT/models/llava-v1.5-7b-config` | config + tokenizer only |
| `CG_VISION_TOWER` | `$CG_DATA_ROOT/models/clip-vit-large-patch14-336` | CLIP snapshot (its weights are overwritten by the checkpoint) |
| `CG_DEVICE_MODE` | `4bit` | `4bit` / `cuda` / `cpu` / `auto` (accelerate; known-broken, section 4) |
| `CG_QUANT_SKIP` | `lm_head,float_layer,mm_projector,lora_A,lora_B` | comma list kept in bf16 - **do not remove `lora_A,lora_B`**, section 6 |
| `CG_QUANT_VISION` | `0` | `1` = quantise the CLIP tower too (saves ~0.45 GiB) |
| `CG_MAX_NEW_TOKENS` | `2048` | generation cap |
| `CG_USE_CACHE` | `1` | keep the KV cache (upstream forces it off) |
| `CG_ATTN_IMPL` | `sdpa` | `sdpa` / `eager` (`flash_attention_2` if you ever install flash-attn) |
| `CG_GPU_BUDGET_GB` | auto | only used by `CG_DEVICE_MODE=auto` |
| `CG_ALLOW_MISSING` | `vision_tower.` | checkpoint key prefixes allowed to be absent |
| `CG_DIAG` | - | `1` = run the four model self-checks instead of the eval (section 8) |
| `PYTHONIOENCODING` / `PYTHONUTF8` | `utf-8` / `1` (set by the runner) | the prompt templates contain non-ASCII text |

### Outputs
```
runs/<checkpoint-name>/<image-folder>_img_recon/
  raw_q1.txt                              # CG-WIN debug: the exact generated text + ids
  vis_new/all_json_spec_files.json        # index over all items
  vis_new/valid_garment_<image-id>/
    output.txt                            # prompt + raw model answer + repaired JSON
    gt_image.png                          # input image
    valid_garment_wholebody/              # one-piece outfit ...
      design.yaml                         # the parsed design parameters (editable!)
      body_measurements.yaml
      valid_garment_wholebody_pattern.svg # the sewing pattern
      valid_garment_wholebody_pattern.png
      valid_garment_wholebody_specification.json  # pattern program for GarmentCode / 3D
    valid_garment_upper/  valid_garment_lower/    # ... or these two, for tops+bottoms
      valid_garment_upper_pattern.svg / .png      # (same file names per prefix)
```

`design.yaml` is the interesting file for 'improve the project': it holds the whole design
tree (which components, and a concrete `v:` for every parameter), so a pattern can be rebuilt
from it without the model at all.

### 5.1 Re-rendering a saved design (no model, ~1 s)

```bash
# identical pattern to the one the model produced (geometry identical, only the stitch
# enumeration order differs - verified by comparing the specification.json)
./.venv/Scripts/python.exe tools/render_pattern.py \
    runs/chatgarment_weights/example_imgs_img_recon/vis_new/valid_garment_example_imgs/<id>/valid_garment_wholebody

# edit a parameter and see the result immediately
./.venv/Scripts/python.exe tools/render_pattern.py <the same dir> --out /tmp/long_skirt
#   ... after setting design.pencil-skirt.length.v: 0.2 -> 0.9 in design.yaml
```

The tool prints which components are active - that is the part that matters, because a
parameter of an unused component does nothing (the dress above has `bottom: PencilSkirt`, so
`design.skirt.length` is ignored while `design.pencil-skirt.length` is not):

```
[render] wholebody: 76 float parameters, 12 design nodes
[render] active components: upper=Shirt bottom=PencilSkirt waistband=None
```

This is also the fastest way to try *architectural* ideas: change the `design.yaml` structure
(`meta.bottom: Pants`, add `design.pants.cuff.type: CuffSkirt`, ...), re-render, and only
then decide whether the model needs retraining. Float values are clipped to their declared
`range` (`--no-clip` disables that) - the usual way to avoid GarmentCode's degenerate-geometry
assertion.

---

## 6. The three bugs that had to be fixed before the output was usable

### 6.1 The 4-bit quantiser was destroying the LoRA fine-tune

Symptom: the model answered a `<image>` prompt with token salad
(`!!!!!!!!!!!!!!!!!!!!!!` and similar), while the same weights are known to work.

Cause: the checkpoint is a LoRA fine-tune (`r=128, alpha=256`) and `quantize_4bit()` was
quantising the adapter matrices `lora_A` / `lora_B` to NF4 as well - 352 linears -> NF4, of
which 128 were `lora_A`/`lora_B`. The adapter, which carries *all* of the fine-tuned
behaviour, was destroyed (and `float_layer`, the 1-float regression head, is unusable at NF4).

Fix: the skip list is now `lm_head,float_layer,mm_projector,lora_A,lora_B`
(`llava/win_compat.py:261`), so exactly **224** linears are quantised = 32 layers x 7
(q,k,v,o,gate,up,down); the vision tower stays bf16 unless `CG_QUANT_VISION=1`.

Proof (`CG_DIAG=1`, log `Logs/diag4.log`: 4 self-checks run before the eval):
1. text-only prompt `The capital of France is` -> ` The capital of France is Paris.</s>`
2. no-image garment prompt -> valid JSON: `{'upperbody_garment': {'garment_name': 'Coat', ...`
3. prompt + image -> valid JSON: `{'wholebody_garment': {'garment_name': 'Dress', ...`
4. checkpoint CLIP tower vs a freshly loaded CLIP: `cosine=1.000000 shape=(1,577,1024)`

Lesson for anyone re-quantising a PEFT checkpoint: **never quantise `lora_A`/`lora_B`**;
quantise the merged base weights, or skip the adapters as done here.

### 6.2 The released checkpoint emits a *variable* number of `[SEG]` tokens

Symptom: `AssertionError` at `llava/garment_utils_v2.py` - 26 `[SEG]` floats generated, 76
expected. Upstream zips `docs/all_float_paths.json` (a fixed list of 76 design leaves) with the
predictions *positionally*, which only works if the answer contains `[SEG]-000 ... [SEG]-075`
index-suffixed slots for the whole design (`recursive_simplify_params` in
`llava/garmentcode_utils.py:120-140` produces exactly those for training).

What the released checkpoint actually does (proof: `runs/.../raw_q1.txt`): it emits **bare**
`[SEG]` only for the components it selected - 26 of them for this dress: collar 9,
pencil-skirt 7, shirt 3, sleeve 7 - and then stops with EOS (`generated_ids=473`, last id 2).
The answer is complete, it is simply a *simplified* design (no waistband, no cuffs, no
asymmetric sleeve) where upstream's 76-slot layout assumes the full GarmentCode design.

Fixes in `llava/garment_utils_v2.py` (marked `CG-WIN`):
* `ordered_float_paths_from_pred()` derives the float leaves from the prediction itself, in the
  **text order of the answer** (the model may describe the collar before the shirt, and the
  float values are positional).
* `_float_dict_for_1float()` uses that list when the count differs from 76, and raises a
  descriptive `AssertionError` when the numbers cannot match.
* both branches of `run_garmentcode_parser_float50()` (wholebody and upper+lower) use it, and the
  upper+lower split is derived the same way instead of the hard-coded 152 (verified splits:
  24+6 upper/lower, 19+7 upper/lower, 33 wholebody, 26 wholebody - all valid patterns);
* `float_preds` is moved to the CPU once at the top of the parser function (it is a `cuda:0`
  tensor and every branch calls `np.asarray` on it).
* `float_preds` is moved to the CPU before `np.asarray` (it is a `cuda:0` tensor).

And in the eval script: the answer is parsed from a copy where each `[SEG]` is replaced by
`0.0` instead of being deleted. Deleting the marker leaves `'width':   ,`, which
`llava/json_fixer.py` 'repairs' by shifting keys around - the repaired dict then describes a
*different* design (measured: only 5 float paths visited instead of 26). The placeholder value
is never used: the real floats come from the `[SEG]` hidden states.

Result: `[CG-WIN] float mapping: 26 [SEG] predictions -> the 26 float paths of the emitted
components` and a real pattern on disk.

Note: the same code path also carries the `evaluate()` fix in
`llava/model/language_model/llava_garment_float50.py` - the float head must read the hidden
state *of the `[SEG]` token as an input token*, so the generated ids are spliced back into the
prompt and one extra forward is run (`hidden_states[1:]` vs `output_ids[:,2:]` upstream only
works for a 1-token prompt).

### 6.3 One bad prediction used to abort the whole batch

Symptom, on the 9th of the 10 example images:

```
AssertionError: Start and end of an edge should differ
  ... pygarment/garmentcode/edge.py line 37, in __init__
  ... bands.py line 13 (StraightBandPanel) <- pants.py line 252 (cuff) <- pants.py line 285
```

The model predicted `{'meta': {'bottom': 'Pants'}, 'pants': {..., 'cuff': {'type': 'CuffBand',
'cuff_len': <bottom of range>}}}`: a trouser cuff band of zero length, i.e. a GarmentCode edge
whose start and end coincide. GarmentCode asserts on it, and because upstream has no
`try/except` the exception propagates out of `main()` - every image *after* the bad one is
lost, and on a 10-image batch that also means 5 minutes of model loading are wasted.

Fix: `_safe_try_generate()` in `llava/garment_utils_v2.py` wraps each garment assembly (both
branches), prints

```
[CG-WIN] WARNING: could not assemble the lower garment from the predicted floats
(AssertionError: Start and end of an edge should differ). The design is kept in
design.yaml; no pattern was written for this item.
```

and continues; the `*_specification.json` path is only registered for the garments that
actually rendered. The degenerate `design.yaml` stays on disk, so you can open it, fix the
value or re-render with `tools/render_pattern.py` (section 5.1) instead of re-running the model.

---

## 7. Source changes (`CG-WIN`)

Search for `CG-WIN` to find every edit: `grep -rn 'CG-WIN' --include='*.py' --include='*.sh' .`.
Commit `e66b2e4` holds the pristine upstream tree, so `git diff e66b2e4` reviews everything.

| File | Change |
|---|---|
| `llava/win_compat.py` **(new)** | all Windows glue: `attn_implementation()`, `load_checkpoint()` (mmap), `load_state_dict_flexible()`, `checkpoint_last_dim()`, `quantize_4bit()`, `place_model()`, `free_memory()`, `enable_cairo_dlls()`, `_decode_new()`, path resolvers |
| `scripts/evaluate_garment_v2_imggen_1float.py` | optional DeepSpeed, sdpa attention, build model from config, 4-bit placement, Windows-safe `exp_name`/`dataset_name`, per-question timing, `raw_q<k>.txt` dump, `[SEG]`->`0.0` parse |
| `scripts/evaluate_garment_v2_eva_edit_1float.py` | same treatment (the only other mode that needs **no** OpenAI key) |
| `scripts/evaluate_garment_v2_textgen_1float.py`, `..._textgen_fromimg_1float.py`, `..._demo_edit_1float.py` | optional DeepSpeed only (they call the GPT-4o API for the description; section 10) |
| `llava/model/language_model/llava_garment_float50.py` | `last_dim` is a constructor argument (the released checkpoint has a **1**-float head, upstream hard-codes 76); `evaluate()` hidden-state/`[SEG]` alignment fixed for multi-token prompts |
| `llava/garment_utils_v2.py` | repo-root path anchors instead of `/is/cluster/...`, `system.json` next to GarmentCodeRC, `sys.executable` for the sub-process, cairo DLL preload, `ordered_float_paths_from_pred()` + `_float_dict_for_1float()` (section 6.2), `_safe_try_generate()` (section 6.3) |
| `run_garmentcode_sim.py` | same path anchors |
| `llava/train/train_garmentcode_outfit.py` | optional DeepSpeed (training itself is out of scope here) |
| `win/run_eval_imggen.sh` | the runner described in section 5 |
| `win/cleanup.ps1` | removes every artefact this setup created (section 2) |
| `tools/render_pattern.py` **(new)** | design.yaml -> pattern without the model (section 5.1) |
| `tools/*.py`, `tools/*.sh` | checkpoint inspector, HF downloader, GEMM benchmark, 4-bit smoke tests, `[SEG]` counter, offline float-mapping test |

Nothing else in the upstream tree was modified. `assets` is a junction, not a copy.

---

## 8. Sanity checks

```bash
.venv/Scripts/python.exe tools/check_env.py        # torch/cuda/versions/asset paths
.venv/Scripts/python.exe tools/test_q4_tiny.py     # 4-bit quantiser vs bf16 (seconds)
.venv/Scripts/python.exe tools/ckpt_shapes.py D:/ChatGarment_data/chatgarment_weights/pytorch_model.bin  # key/shape inspection (mmap, ~10 s)
.venv/Scripts/python.exe tools/test_float_mapping.py  # offline test of 6.2 (no GPU needed)
.venv/Scripts/python.exe tools/render_pattern.py runs/chatgarment_weights/win_1img_img_recon/vis_new/valid_garment_win_1img/80141ce740f489f1d2f57a03f32c7577a28b62a6ac790a0d9ed8a18d961c2918/valid_garment_wholebody --out .tmp/pat  # 5.1, needs no GPU
```

`check_env.py` should end with every big file `OK` and `cairosvg: 2.9.1` (see section 3.3);
`test_q4_tiny.py` prints `14 linears -> NF4` and a logit `maxdiff` well under 0.5;
`test_float_mapping.py` prints the 26 float paths of the `raw_q1.txt` answer;
`render_pattern.py` prints `[render] active components: upper=Shirt bottom=PencilSkirt waistband=None`
and `Success! Garment wholebody saved to ...`.

The load log must contain:
```
[CG-WIN] checkpoint float head: last_dim=1 (from file)
[CG-WIN] load_state_dict: 0 missing (non-vision), 0 missing (vision tower, expected), 0 unexpected
[CG-WIN] quantize_4bit: 224 linears -> NF4, model on cuda:0 (4.43 GiB allocated)
```

`CG_DIAG=1 bash win/run_eval_imggen.sh runs/win_1img` runs the four self-checks of section 6.1
instead of the evaluation (about 60 s after loading) - the quickest way to tell a broken model
from a broken parser.

---

## 9. Troubleshooting (the actual errors that came up)

| Symptom | Cause / fix |
|---|---|
| `UnicodeEncodeError: 'gbk' codec can't encode character` | Windows console is GBK, the prompt templates are UTF-8. The runner exports `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. |
| `ImportError: flash_attn` / wants `flash_attention_2` | no flash-attn on Windows; patched to `sdpa` (`CG_ATTN_IMPL`). |
| `NotImplementedError: Cannot copy out of meta tensor` | accelerate CPU offload; use `CG_DEVICE_MODE=4bit` (default). |
| `size mismatch for float_layer.2.weight: [1,4096] vs [76,4096]` | upstream hard-codes `self.last_dim = 76`; now read from the checkpoint (`last_dim=1`). |
| `load_state_dict(strict=True)` fails on `vision_tower.*` | checkpoint keys are `base_model.model.model.vision_tower...`; flexible loader + allow-list (`CG_ALLOW_MISSING`). |
| `PermissionError: [WinError 5] 'D:...'` when creating the run dir | upstream `resume_path.split('/')[-2]` yields `D:` for Windows paths; patched with `normpath/dirname/basename`. |
| `We need an offload_dir to dispatch this model` | the auto device map could not fit anything else; only relevant for `CG_DEVICE_MODE=auto`. |
| `OSError: We couldn't connect to 'https://huggingface.co'` | the config names `openai/clip-vit-large-patch14-336`; patched to the local snapshot (`CG_VISION_TOWER`). |
| opencv wants numpy>=2 | pin `opencv-python-headless==4.10.0.84`. |
| venv python cannot write outside the repo (`PermissionError [Errno 13]`) | sandbox artefact of this machine; all Python-side writes stay inside the repo (`.tmp`, `.pip-cache`, `runs/`, `Logs/`), the big downloads are done by bash into `D:/ChatGarment_data`. |
| `--- !!` token salad from a `<image>` prompt | the LoRA adapter got quantised - section 6.1. |
| `AssertionError` 26 != 76 after a good-looking answer | variable `[SEG]` count - section 6.2. |
| `AssertionError: Start and end of an edge should differ` | the predicted floats make degenerate geometry (e.g. a zero-length `CuffBand`); now a per-garment warning, the batch continues - section 6.3. Open the item's `design.yaml`, fix the value, re-render with `tools/render_pattern.py`. |
| `TypeError: can't convert cuda:0 device type tensor to numpy` | `float_preds` must be moved to the CPU first (fixed in `_float_dict_for_1float`). |
| `IndexError: The shape of the mask [1, 473] ... does not match [1, 1187, 1]` | the old `evaluate()` alignment; fixed by the splice-and-extra-forward (section 6.2). |
| `mklink /J` produced a broken junction | use `powershell -Command "New-Item -ItemType Junction ..."`. |
| first forward takes minutes | 15 GB mmap read + 224 on-GPU quantisations; one-time per process. |
| `hf-mirror.com` SSL error / HTTP 000 | the mirror is flaky; retry, or use `tools/fetch_hf_bash.sh` (resumable, 20 connections). |

---

## 10. Out of scope on this machine (and why)

| Feature | Why not |
|---|---|
| `scripts/postprocess/*` (3D mesh registration, renders) | needs `pytorch3d` - no Windows wheel for torch 2.7/sm_120 and no MSVC/CUDA toolkit to build it. Not imported by the pattern pipeline. |
| 3D simulation (`run_garmentcode_sim.py` -> ContourCraft-CG, `pygarment.meshgen.simulation`) | needs Blender + a CUDA extension build; the GitHub clone also fails on this network (`schannel: server closed abruptly (missing close_notify)`). |
| `evaluate_garment_v2_textgen_1float.py`, `..._textgen_fromimg_1float.py`, `..._demo_edit_1float.py` | call the OpenAI GPT-4o API to invent a garment description; need `OPENAI_API_KEY`. `imggen` and `eva_edit` do not. |
| training (`llava/train/*`, `scripts/v1_5/*.sh`) | DeepSpeed + multi-GPU; the imports were only made optional so the eval code can import the module. |

---

## 11. Uninstalling

```powershell
powershell -ExecutionPolicy Bypass -File win\cleanup.ps1            # dry run: what, how big
powershell -ExecutionPolicy Bypass -File win\cleanup.ps1 -Execute   # delete
powershell -ExecutionPolicy Bypass -File win\cleanup.ps1 -Execute -KeepData   # keep the 19 GB of weights
powershell -ExecutionPolicy Bypass -File win\cleanup.ps1 -Execute -KeepGit   # keep the patch history
```

It removes `.venv`, `.pip-cache`, `.tmp`, `repos`, the `assets` junction, `runs`, `Logs`,
`checkpoints`, `output`, `torchinductor_*`, optionally `.git`, and `D:\ChatGarment_data`
(unless `-KeepData`). Measured dry run: **7.3 GB inside the repo + 19.1 GB in `D:/`**.
Nothing system-wide was ever installed, so there is nothing else to undo.
