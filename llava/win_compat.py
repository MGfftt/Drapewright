"""CG-WIN compatibility helpers for running ChatGarment on a single Windows GPU.

This module does not exist in the upstream release.  It only holds the helpers
that the patched entry points need; every hunk that touches upstream files is
marked with a "CG-WIN" comment so the changes are easy to find, revert or
delete.  Removing this file and the CG-WIN hunks restores upstream behaviour.

Why it exists
-------------
Upstream targets 4-8x NVIDIA H100 nodes with flash-attention and DeepSpeed.
This machine is a single laptop GPU with 8 GB of VRAM, so:

* flash-attention-2 has no Windows wheel -> use torch's SDPA kernels instead
  (CG_ATTN_IMPL=eager|sdpa|flash_attention_2).
* a 7B model in bf16 is ~15 GB and cannot fit in 8 GB of VRAM -> the linear
  layers are quantized to 4 bit (bitsandbytes NF4) right after the checkpoint
  is loaded, which brings the resident model down to ~3.5 GB
  (CG_DEVICE_MODE=4bit, the default).  cuda|auto|cpu are kept as fallbacks:
  cuda = plain model.cuda(), auto = accelerate layer streaming, cpu = RAM only.
* DeepSpeed has no Windows wheel -> its import is optional.

Everything is controlled by environment variables so the patched code keeps
running unchanged once the weights do fit on the GPU (set CG_DEVICE_MODE=cuda).
"""
import gc
import os

import torch


# --------------------------------------------------------------------------- #
# logging
# --------------------------------------------------------------------------- #
def log(msg):
    print(f"[CG-WIN] {msg}", flush=True)


def _truthy(value):
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


# --------------------------------------------------------------------------- #
# attention backend
# --------------------------------------------------------------------------- #
def attn_implementation(default="sdpa"):
    """Attention kernel used when instantiating the language model.

    Upstream hard-codes 'flash_attention_2'.  That fails on Windows (no wheel)
    and also on this GPU because the flash-attn build would have to target
    sm_120.  SDPA is a drop-in replacement inside torch 2.x.
    """
    return os.environ.get("CG_ATTN_IMPL", default)


# --------------------------------------------------------------------------- #
# generation knobs
# --------------------------------------------------------------------------- #
def use_cache(default=True):
    """Whether generation may keep a KV cache.

    Upstream sets model.config.use_cache = False right before the evaluation
    loop and never restores it, so every generated token re-runs the whole
    prefix (O(n^2) forwards).  On a CPU-offloaded 7B that turns a couple of
    minutes into many hours, so the cache is enabled for inference here.
    CG_USE_CACHE=0 restores upstream behaviour.
    """
    return _truthy(os.environ.get("CG_USE_CACHE", "1" if default else "0"))


def max_new_tokens(default=2048):
    """Upper bound for generated tokens (env CG_MAX_NEW_TOKENS)."""
    return int(os.environ.get("CG_MAX_NEW_TOKENS") or default)


# --------------------------------------------------------------------------- #
# checkpoint helpers
# --------------------------------------------------------------------------- #
def load_checkpoint(path, verbose=True):
    """Load a (possibly 15 GB) state dict without duplicating it in RAM.

    torch.load(mmap=True) memory-maps the zip archive, so the 15 GB checkpoint
    is paged in from disk instead of being copied into anonymous memory; this
    is what makes loading a 15 GB file next to a 15 GB model feasible with
    32 GB of RAM.  weights_only=True avoids executing arbitrary pickles.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(
            "ChatGarment checkpoint not found: " + str(path) + "\n"
            "Set CG_CHECKPOINT to the pytorch_model.bin downloaded from "
            "https://huggingface.co/sy000/chatgarment_extrafiles (see win/README.md)."
        )
    if verbose:
        log("loading checkpoint %s (%.2f GiB, mmap)" % (path, os.path.getsize(path) / 2 ** 30))
    try:
        return torch.load(path, map_location="cpu", mmap=True, weights_only=True)
    except Exception as exc:  # noqa: BLE001 - older pickles may need the slow path
        log("mmap/weights_only load failed (%s: %s); retrying without" % (type(exc).__name__, exc))
        return torch.load(path, map_location="cpu", weights_only=False)


def checkpoint_last_dim(path=None, default=1):
    """Dimension of the [SEG] float head, read from the checkpoint itself.

    float_layer.2 is the last linear layer of the float head.  The released
    "*1float*" checkpoints predict one float per [SEG] token ([1, hidden]), the
    76-float flavour predicts a whole design vector at once.  Reading the shape
    from the file avoids hard-coding either variant.
    """
    path = path or checkpoint_path()
    try:
        sd = torch.load(path, map_location="cpu", mmap=True, weights_only=True)
    except Exception as exc:  # noqa: BLE001 - fall back to the documented default
        log("checkpoint_last_dim: cannot read %s (%s); assuming %d" % (path, exc, default))
        return default
    key = None
    for candidate in ("base_model.model.float_layer.2.weight", "float_layer.2.weight"):
        if candidate in sd:
            key = candidate
            break
    if key is None:
        for name in sd:
            if name.endswith("float_layer.2.weight"):
                key = name
                break
    dim = int(sd[key].shape[0]) if key is not None else default
    del sd
    gc.collect()
    log("checkpoint float head: last_dim=%d (%s)" % (dim, "from file" if key else "default"))
    return dim


def load_state_dict_flexible(model, state_dict, verbose=True):
    """load_state_dict(strict=False) that still fails on real mismatches.

    The released ChatGarment checkpoints are LoRA/PEFT state dicts that contain
    every language-model tensor but *not* the CLIP vision tower (that one is
    loaded from the openai/clip-vit-large-patch14-336 snapshot).  Upstream calls
    load_state_dict(strict=True), which can therefore never succeed with these
    files.  Missing keys are tolerated only for the prefixes listed in
    CG_ALLOW_MISSING (default: vision_tower.); everything else - unexpected
    keys or non-vision missing keys - is reported and raised.
    """
    allow = os.environ.get("CG_ALLOW_MISSING", "vision_tower.").split(",")
    allow = tuple(p for p in (s.strip() for s in allow) if p)

    ret = model.load_state_dict(state_dict, strict=False)
    missing = [k for k in ret.missing_keys if not k.startswith(allow)]
    unexpected = list(ret.unexpected_keys)
    if verbose:
        vision_missing = len(ret.missing_keys) - len(missing)
        log(
            "load_state_dict: %d missing (non-vision), %d missing (vision tower, expected), %d unexpected"
            % (len(missing), vision_missing, len(unexpected))
        )
        for k in missing[:20]:
            log("  missing:    " + k)
        for k in unexpected[:20]:
            log("  unexpected: " + k)
    if missing or unexpected:
        raise RuntimeError(
            "checkpoint does not match the model architecture "
            "(%d missing, %d unexpected keys, see log). "
            "If you know the missing tensors are fine, relax CG_ALLOW_MISSING."
            % (len(missing), len(unexpected))
        )
    return ret


# --------------------------------------------------------------------------- #
# device placement
# --------------------------------------------------------------------------- #
def _gpu_budget_gib(reserve_gib=1.2):
    """How much VRAM we are willing to give to the weights."""
    explicit = os.environ.get("CG_GPU_BUDGET_GB")
    if explicit:
        return float(explicit)
    free, _total = torch.cuda.mem_get_info()
    return max(1.0, free / 2 ** 30 - reserve_gib)


def _no_split_classes(model):
    """Transformer block classes that must stay on a single device.

    accelerate splits a model module by module; if it is allowed to split inside
    a decoder layer the weights of one layer end up on the GPU *and* in RAM and
    every forward pass pays an extra host<->device copy per tensor.  Marking the
    block classes as non-splittable keeps whole layers together.
    """
    names = set()
    for module in model.modules():
        name = type(module).__name__
        if name.endswith("DecoderLayer") or name.endswith("EncoderLayer"):
            names.add(name)
    return sorted(names)


def place_model(model, verbose=True):
    """Move the model to whatever devices are available, quantizing if needed.

    Modes (CG_DEVICE_MODE):
      4bit (default) - quantize the linear layers to NF4 and keep the whole
                       model on the GPU (~4 GB); see quantize_4bit()
      auto           - put as much as fits on the GPU, keep the rest in RAM and
                       let accelerate's hooks move activations per module
      cuda           - plain model.cuda() (needs the bf16 weights to fit)
      cpu            - never touch the GPU (slow, but immune to OOM)
    """
    mode = os.environ.get("CG_DEVICE_MODE", "4bit").strip().lower()
    if mode == "cpu" or not torch.cuda.is_available():
        model.to("cpu")
        log("device placement: cpu only")
        return model

    if mode == "4bit":
        quantize_4bit(model, verbose=verbose)
        model.eval()
        return model

    if mode == "cuda":
        model.to("cuda:0")
        log("device placement: cuda:0 (no offload)")
        return model

    from accelerate import dispatch_model, infer_auto_device_map

    gpu_gib = _gpu_budget_gib()
    try:
        import psutil

        total_gib = psutil.virtual_memory().total / 2 ** 30
    except Exception:  # noqa: BLE001
        total_gib = 24.0
    # The weights that the device map puts on the CPU are allocated *while* the
    # map is being built, so the budget has to be based on the total amount of
    # RAM (minus what Windows needs), not on what is free at this instant -
    # otherwise accelerate concludes that nothing fits and tries to offload the
    # rest of the model to disk (which then demands an offload_dir).
    cpu_gib = max(8.0, total_gib - 6.0)
    max_memory = {0: "%.1fGiB" % gpu_gib, "cpu": "%.1fGiB" % cpu_gib}

    no_split = _no_split_classes(model)
    if verbose:
        log("device placement: auto, gpu=%.1fGiB cpu=%.1fGiB, no_split=%s" % (gpu_gib, cpu_gib, no_split))

    gc.collect()
    torch.cuda.empty_cache()
    device_map = infer_auto_device_map(model, max_memory=max_memory, no_split_module_classes=no_split)
    model = dispatch_model(model, device_map=device_map, force_hooks=True)
    if verbose:
        on_gpu = sum(1 for v in device_map.values() if v in (0, "cuda:0"))
        log("dispatch_model: %d/%d modules on cuda:0" % (on_gpu, len(device_map)))
    model.eval()
    return model

# --------------------------------------------------------------------------- #
# 4-bit quantization (the only way a 7B model fits in 8 GB of VRAM)
# --------------------------------------------------------------------------- #
# NOTE: the LoRA A/B matrices must stay in bf16.  They are trained at r=128 and
# carry a large part of the fine-tune; packing them to NF4 destroys them
# (observed: the model degenerated into multilingual token salad).
_QUANT_SKIP_DEFAULT = "lm_head,float_layer,mm_projector,lora_A,lora_B"


def _quant_skip_patterns():
    raw = os.environ.get("CG_QUANT_SKIP", _QUANT_SKIP_DEFAULT)
    pats = [p.strip() for p in raw.split(",") if p.strip()]
    if not _truthy(os.environ.get("CG_QUANT_VISION", "0")):
        pats.append("vision_tower")
    return pats


def _bnb_linear4bit(lin, device="cuda:0"):
    """Build a bitsandbytes Linear4bit that holds the weights of `lin`."""
    import bitsandbytes as bnb

    q = bnb.nn.Linear4bit(
        lin.in_features,
        lin.out_features,
        bias=lin.bias is not None,
        compute_dtype=torch.bfloat16,
        compress_statistics=True,
        quant_type="nf4",
    )
    w = lin.weight.data
    if w.device.type != "cpu":
        w = w.to("cpu")
    q.weight = bnb.nn.Params4bit(w, requires_grad=False, quant_type="nf4", blocksize=64)
    if lin.bias is not None:
        b = lin.bias.data
        q.bias = torch.nn.Parameter(b.to("cpu") if b.device.type != "cpu" else b)
    # Moving the module is what actually quantizes the weights (Params4bit).
    return q.to(device)


def quantize_4bit(model, verbose=True, device="cuda:0"):
    """Replace every decoder Linear (including the LoRA base layers) with NF4.

    The float weights are dropped one module at a time, so the peak host RAM
    stays at one copy of the bf16 model (~15 GB), and the GPU only ever holds
    the packed 4-bit weights.  `lm_head`, the float head, the mm projector and
    (by default) the CLIP tower keep their bf16 weights because they are small
    and numerically sensitive, and so do the LoRA A/B adapters (see
    _QUANT_SKIP_DEFAULT); set CG_QUANT_VISION=1 to quantize CLIP as well.
    """
    import bitsandbytes as bnb

    pats = _quant_skip_patterns()

    def skipped(name):
        for p in pats:
            if name == p or name.endswith("." + p) or ("." + p + ".") in name:
                return True
        return False

    # NOTE: named_modules() lists both the peft wrapper and its base_layer, so
    # the base layers must be claimed first - otherwise the same Linear would be
    # converted twice (the second pass then sees the packed uint8 tensor).
    modules = list(model.named_modules())
    targets = []
    claimed = set()
    for name, mod in modules:
        if isinstance(mod, bnb.nn.Linear4bit) or skipped(name):
            continue
        base_layer = getattr(mod, "base_layer", None)
        if isinstance(base_layer, torch.nn.Linear):
            claimed.add(id(base_layer))
            targets.append((name, "base_layer"))
    for name, mod in modules:
        if isinstance(mod, bnb.nn.Linear4bit) or skipped(name) or id(mod) in claimed:
            continue
        if isinstance(mod, torch.nn.Linear):
            targets.append((name, None))

    converted = 0
    for name, attr in targets:
        owner = model.get_submodule(name)
        lin = owner if attr is None else getattr(owner, "base_layer")
        new = _bnb_linear4bit(lin, device=device)
        if attr is None:
            parent = model.get_submodule(name.rsplit(".", 1)[0]) if "." in name else model
            setattr(parent, name.rsplit(".", 1)[-1], new)
        else:
            setattr(owner, attr, new)
        del lin
        converted += 1
        if converted % 32 == 0:
            free_memory()

    # Everything that stayed float (embeddings, lm_head, LoRA adapters, norm)
    # lives on the GPU as bf16.
    for name, param in list(model.named_parameters()):
        if param.is_meta:
            raise RuntimeError("[CG-WIN] parameter %s is on the meta device" % name)
        if not name.startswith("base_model.model.") and False:
            pass
    model.to(device)
    free_memory()
    if verbose:
        gpu = torch.cuda.memory_allocated() / 2 ** 30
        log("quantize_4bit: %d linears -> NF4, model on %s (%.2f GiB allocated)" % (converted, device, gpu))
    return model

def report_devices(model, verbose=True):
    """Log where the first/last transformer blocks live (sanity check)."""
    if not verbose:
        return
    try:
        layers = model.get_model().layers
        first = next(layers[0].parameters()).device
        last = next(layers[-1].parameters()).device
        vision_dev = next(model.get_vision_tower().parameters()).device
        log("devices: layer0=%s last_layer=%s vision_tower=%s" % (first, last, vision_dev))
    except Exception as exc:  # noqa: BLE001
        log("report_devices skipped (%s: %s)" % (type(exc).__name__, exc))


# --------------------------------------------------------------------------- #
# misc
# --------------------------------------------------------------------------- #
def free_memory():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()




# --------------------------------------------------------------------------- #
# well-known locations of the downloaded assets
# --------------------------------------------------------------------------- #
# Everything that does not fit in the repo lives under CG_DATA_ROOT (D: on the
# reference machine) and can be deleted in one go - see win/cleanup.md.
def data_root():
    return os.environ.get("CG_DATA_ROOT", "D:/ChatGarment_data")


def checkpoint_path():
    """ChatGarment fine-tuned weights (PEFT state dict, ~15 GB)."""
    return os.environ.get(
        "CG_CHECKPOINT",
        os.path.join(data_root(), "chatgarment_weights", "pytorch_model.bin"),
    )


def vision_tower_path():
    """Local snapshot of openai/clip-vit-large-patch14-336 (no vision_tower keys in the ckpt)."""
    return os.environ.get("CG_VISION_TOWER", os.path.join(data_root(), "models", "clip-vit-large-patch14-336"))


def base_config_path():
    """LLaVA-1.5-7B config+tokenizer only; the weights come from the ckpt itself."""
    return os.environ.get("CG_BASE_CONFIG", os.path.join(data_root(), "models", "llava-v1.5-7b-config"))


# --------------------------------------------------------------------------- #
# native dependencies
# --------------------------------------------------------------------------- #
# pygarment renders patterns with cairosvg, which needs the cairo native library.
# GarmentCodeRC ships the DLLs in pygarment/pattern/cairo_dlls and upstread adds
# that folder to PATH - the PATH trick stopped working in Python 3.8, where the
# DLL search path has to be extended explicitly with os.add_dll_directory().
_DLL_HANDLES = []


def enable_cairo_dlls():
    """Make the bundled cairo DLLs importable by cairocffi (Windows only)."""
    if os.name != "nt":
        return
    root = os.environ.get("GARMENTCODE_ROOT",
                          os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                       "repos", "GarmentCodeRC-main"))
    dll_dir = os.path.join(root, "pygarment", "pattern", "cairo_dlls")
    if not os.path.isdir(dll_dir):
        return
    try:
        handle = os.add_dll_directory(dll_dir)
        _DLL_HANDLES.append(handle)  # keep alive: the folder is removed when it is GCed
    except (AttributeError, OSError) as exc:
        log("could not register cairo DLL directory (%s)" % exc)
    # cairocffi loads the library through cffi, which searches differently from
    # ctypes: also prepend PATH and pre-load the DLL by full path so that the
    # later LoadLibrary("libcairo-2.dll") reuses the already loaded module.
    os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault("OS", "Windows")
    try:
        import ctypes

        _DLL_HANDLES.append(ctypes.WinDLL(os.path.join(dll_dir, "libcairo-2.dll")))
        log("cairo DLL preloaded: " + dll_dir)
    except OSError as exc:
        log("could not preload libcairo-2.dll (%s)" % exc)


def deepspeed_or_none():
    """import deepspeed if it is installed, else return None."""
    try:
        import deepspeed  # noqa: F401

        return deepspeed
    except Exception:  # noqa: BLE001
        return None

# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# diagnostics
# --------------------------------------------------------------------------- #
def _decode_new(tokenizer, seq):
    """Generation with inputs_embeds returns [BOS] + new tokens (no prompt)."""
    ids = seq.tolist()
    bos = tokenizer.bos_token_id
    if ids and ids[0] == bos:
        ids = ids[1:]
    return ids, tokenizer.decode(ids, skip_special_tokens=False)


def diag_probes(model, tokenizer, device, image_clip=None, n_text=24, n_image=64):
    """Greedy generations that separate "bad weights" from "bad multimodal path".

    (1) text-only : images=None -> prepare_inputs_labels_for_multimodal() returns
        early, so this exercises only the (4-bit) language model.
    (2) the exact 2-step-eval prompt with the image token stripped, i.e. text only
        through the same chat template.
    (3) the same prompt with real image features (what the eval actually does).
    (4) cosine similarity between the checkpoint's CLIP tower and a fresh CLIP.
    (5) how many linears were quantised in the decoder vs the vision tower.
    """
    import torch
    from llava.constants import DEFAULT_IMAGE_TOKEN
    from llava.mm_utils import tokenizer_image_token
    from llava import conversation as conversation_lib

    model.eval()
    gpu = torch.cuda.memory_allocated() / 2 ** 30 if torch.cuda.is_available() else 0.0
    log("[CG-WIN][diag] vocab tokenizer=%d model=%d gpu=%.2fGiB" % (
        len(tokenizer), model.config.vocab_size, gpu))

    raw = "USER: What is the capital of France?\nASSISTANT:"
    ids = tokenizer(raw, return_tensors="pt").input_ids.to(device)
    with torch.no_grad():
        out = model.generate(inputs=ids, max_new_tokens=n_text, do_sample=False,
                             use_cache=use_cache(True), inference=True)
    new, txt = _decode_new(tokenizer, out[0])
    log("[CG-WIN][diag] (1) text-only ids=%s" % new)
    log("[CG-WIN][diag] (1) text-only text=%r" % txt)

    q = "Can you describe the geometry features of the garments worn by the model in the Json format?"
    conv = conversation_lib.conv_templates["v1"].copy()
    conv.append_message(conv.roles[0], DEFAULT_IMAGE_TOKEN + "\n" + q)
    conv.append_message(conv.roles[1], None)
    prompt = conv.get_prompt()
    log("[CG-WIN][diag] prompt: %r" % prompt)

    ids_noimg = tokenizer_image_token(prompt.replace(DEFAULT_IMAGE_TOKEN, ""), tokenizer,
                                      return_tensors="pt").unsqueeze(0).to(device)
    with torch.no_grad():
        out = model.generate(inputs=ids_noimg, max_new_tokens=n_image, do_sample=False,
                             use_cache=use_cache(True), inference=True)
    new, txt = _decode_new(tokenizer, out[0])
    log("[CG-WIN][diag] (2) no-image: %d tokens" % len(new))
    log("[CG-WIN][diag] (2) no-image text=%r" % txt)

    if image_clip is None:
        return

    ids = tokenizer_image_token(prompt, tokenizer, return_tensors="pt").unsqueeze(0).to(device)
    image_clip = image_clip.to(device).bfloat16()
    with torch.no_grad():
        out = model.generate(inputs=ids, images=image_clip, max_new_tokens=n_image,
                             do_sample=False, num_beams=1, use_cache=use_cache(True),
                             return_dict_in_generate=True, inference=True)
    new, txt = _decode_new(tokenizer, out.sequences[0])
    log("[CG-WIN][diag] (3) image: %d tokens" % len(new))
    log("[CG-WIN][diag] (3) image text=%r" % txt)

    try:
        import torch.nn.functional as F
        from transformers import CLIPVisionModel

        vision = model.get_vision_tower()
        ref = CLIPVisionModel.from_pretrained(vision_tower_path(), torch_dtype=torch.bfloat16)
        ref = ref.to(device).eval()
        with torch.no_grad():
            f_ckpt = vision.vision_tower(image_clip, output_hidden_states=True)[0].float()
            f_ref = ref(image_clip).last_hidden_state.float()
        cos = F.cosine_similarity(f_ckpt.flatten(), f_ref.flatten(), dim=0).item()
        log("[CG-WIN][diag] (4) vision features vs fresh CLIP: cosine=%.6f shape=%s" %
            (cos, tuple(f_ckpt.shape)))
        del ref
        free_memory()
    except Exception as exc:  # noqa: BLE001
        log("[CG-WIN][diag] (4) vision check failed: %s: %s" % (type(exc).__name__, exc))

    try:
        import bitsandbytes as bnb

        def count(prefix):
            return sum(1 for name, mod in model.named_modules()
                       if isinstance(mod, bnb.nn.Linear4bit) and name.startswith(prefix))

        log("[CG-WIN][diag] (5) Linear4bit: decoder=%d vision=%d" % (
            count("base_model.model.model.layers"), count("base_model.model.model.vision_tower")))
    except Exception as exc:  # noqa: BLE001
        log("[CG-WIN][diag] (5) quant count failed: %s: %s" % (type(exc).__name__, exc))
