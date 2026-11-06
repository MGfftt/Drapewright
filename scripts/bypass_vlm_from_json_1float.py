"""CG-WIN: run ChatGarment's numeric head on a hand-written JSON ("VLM bypass").

The released 7B checkpoint does two jobs:
  (1) the language model *writes* a garment JSON, and
  (2) `float_layer` regresses the continuous design parameters from the hidden
      state at every [SEG] token (one float per [SEG] for the "*1float*" ckpt).

This script keeps (2) and skips (1): the answer text is supplied by the caller,
the image still goes through CLIP, and a *single forward pass* (no
autoregressive generation) turns the [SEG] slots into numbers.  Everything
downstream (JSON -> design.yaml -> GarmentCodeRC pattern -> 3D) is the official
pipeline, so the result is directly comparable with the full model.

Usage:
  bash win/run_bypass_json.sh --image R-C.jpg \
       --answer_json cases/rc_dress/answer.json --tag rc_dress
"""
import copy
import json
import os
import sys
import time
from dataclasses import dataclass, field

import numpy as np
import torch
import transformers

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from PIL import Image  # noqa: E402

from llava.constants import DEFAULT_IMAGE_TOKEN  # noqa: E402
from llava import conversation as conversation_lib  # noqa: E402
from llava.model import *  # noqa: E402,F401,F403  (registers llava_llama / GarmentGPTFloat50ForCausalLM)
from llava.mm_utils import tokenizer_image_token  # noqa: E402
from llava import win_compat  # noqa: E402
from llava.json_fixer import repair_json  # noqa: E402
from llava.train.train_garmentcode_outfit import (  # noqa: E402
    ModelArguments, DataArguments, TrainingArguments)
from llava.garment_utils_v2 import (  # noqa: E402
    designs_config, ordered_float_paths_from_pred, run_garmentcode_parser_float50)

QUESTION2 = ("Can you estimate the sewing pattern code based on the image and "
             "Json format garment geometry description?")


@dataclass
class BypassArguments:
    """Extra knobs; the model/dataset args are the ones the launcher already sets."""

    image: str = field(default="./R-C.jpg", metadata={"help": "input photograph"})
    answer_json: str = field(default="", metadata={"help": "hand-written JSON with [SEG] slots"})
    tag: str = field(default="bypass", metadata={"help": "name of the produced garment"})
    out_dir: str = field(default="./runs/bypass_rc", metadata={"help": "where everything is written"})
    dry_floats: str = field(default="", metadata={"help": "comma separated floats; skips the model entirely"})
    skip_garmentcode: int = field(default=0, metadata={"help": "1 = stop after the floats"})
    answer_mode: str = field(default="assistant", metadata={
        "help": "assistant = the JSON is teacher-forced as the model's own reply "
                "(the [SEG] slots then sit in the same place they were trained on); "
                "user = the JSON is appended to the question (legacy behaviour)"})
    description: str = field(default="", metadata={
        "help": "geometry description text put in the user turn before the answer, "
                "exactly like round 2 of the official demo"})
    description_file: str = field(default="", metadata={"help": "file with that description"})


def log(msg):
    print("[CG-BYPASS] " + str(msg), flush=True)


def find_all_linear_names(model, lora_target_modules=("q_proj", "v_proj")):
    cls = torch.nn.Linear
    names = set()
    skip = ["mm_projector", "vision_tower", "vision_resampler", "float_layer"]
    for name, module in model.named_modules():
        if (isinstance(module, cls)
                and all(x not in name for x in skip)
                and any(x in name for x in lora_target_modules)):
            names.add(name)
    return sorted(names)


def _float_layer(model):
    """float_layer sits behind peft / accelerate wrappers."""
    cur = model
    for _ in range(8):
        if hasattr(cur, "float_layer"):
            return cur.float_layer
        cur = getattr(cur, "base_model", None) or getattr(cur, "model", None)
        if cur is None:
            break
    raise AttributeError("float_layer not reachable from %s" % type(model).__name__)


def load_image_pixels(path, processor):
    """Same preprocessing as the eval script (image_aspect_ratio == "pad")."""
    image = Image.open(path).convert("RGB")
    w, h = image.size
    if w != h:
        side = max(w, h)
        bg = tuple(int(x * 255) for x in processor.image_mean)
        canvas = Image.new("RGB", (side, side), bg)
        canvas.paste(image, ((side - w) // 2, (side - h) // 2))
        image = canvas
    return processor.preprocess(image, return_tensors="pt")["pixel_values"][0]


def load_model(model_args, training_args):
    """Mirrors scripts/evaluate_garment_v2_imggen_1float.py: build from config,
    add the LoRA shell, then load the released PEFT checkpoint and let
    win_compat.place_model() decide what lives on the 8 GB GPU."""
    attn = win_compat.attn_implementation()
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        model_args.model_name_or_path,
        cache_dir=training_args.cache_dir,
        model_max_length=training_args.model_max_length,
        padding_side="right",
        use_fast=False,
    )
    tokenizer.pad_token = tokenizer.unk_token
    tokenizer.add_tokens("[SEG]")
    seg_token_idx = tokenizer("[SEG]", add_special_tokens=False).input_ids[-1]

    cfg = LlavaConfig.from_pretrained(model_args.model_name_or_path,
                                      cache_dir=training_args.cache_dir)
    cfg.mm_vision_tower = model_args.vision_tower
    cfg._attn_implementation = attn
    if training_args.bf16:
        cfg.torch_dtype = torch.bfloat16
    model = GarmentGPTFloat50ForCausalLM(
        cfg,
        seg_token_idx=seg_token_idx,
        last_dim=win_compat.checkpoint_last_dim(),
    )
    model.config.eos_token_id = tokenizer.eos_token_id
    model.config.bos_token_id = tokenizer.bos_token_id
    model.config.pad_token_id = tokenizer.pad_token_id
    model.config.use_cache = False          # a single forward, no cache needed

    model.get_model().initialize_vision_modules(model_args=model_args, fsdp=None)
    vision_tower = model.get_vision_tower()
    vision_tower.to(dtype=torch.bfloat16 if training_args.bf16 else torch.float16,
                    device=training_args.device)
    for p in vision_tower.parameters():
        p.requires_grad = False
    for p in model.get_model().mm_projector.parameters():
        p.requires_grad = False

    from peft import LoraConfig, get_peft_model
    lora_config = LoraConfig(
        r=training_args.lora_r,
        lora_alpha=training_args.lora_alpha,
        target_modules=find_all_linear_names(model),
        lora_dropout=training_args.lora_dropout,
        bias=training_args.lora_bias,
        task_type="CAUSAL_LM",
    )
    if training_args.bf16:
        model.to(torch.bfloat16)
    model = get_peft_model(model, lora_config)
    model.resize_token_embeddings(len(tokenizer))
    model.config.image_aspect_ratio = "pad"
    model.config.tokenizer_model_max_length = tokenizer.model_max_length
    model.config.mm_use_im_start_end = False
    model = model.bfloat16()

    resume_path = win_compat.checkpoint_path()
    log("checkpoint: %s (last_dim=%d)" % (resume_path, win_compat.checkpoint_last_dim()))
    state_dict = win_compat.load_checkpoint(resume_path)
    win_compat.load_state_dict_flexible(model, state_dict)
    del state_dict
    win_compat.free_memory()
    model = win_compat.place_model(model)
    win_compat.report_devices(model)
    return model, tokenizer, seg_token_idx, vision_tower.image_processor


def build_prompt(description, version):
    """The user turn of round 2: <image> + question + geometry description."""
    conv = conversation_lib.conv_templates[version].copy()
    conv.messages = []
    prompt = DEFAULT_IMAGE_TOKEN + "\n" + QUESTION2
    if description:
        prompt = prompt + "\n" + description
    conv.append_message(conv.roles[0], prompt)
    conv.append_message(conv.roles[1], None)
    return conv.get_prompt()


def prompt_ids(prompt, answer_text, tokenizer, answer_mode):
    """Token ids of question (+ optional answer as the assistant reply)."""
    ids = tokenizer_image_token(prompt, tokenizer, return_tensors="pt")
    if answer_mode == "user":
        return ids.unsqueeze(0)
    answer_ids = tokenizer(answer_text, add_special_tokens=False,
                           return_tensors="pt").input_ids[0]
    return torch.cat([ids, answer_ids], dim=0).unsqueeze(0)


def seg_floats(model, tokenizer, seg_token_idx, image_pixels, input_ids, device):
    """One forward pass: tokens + image -> the float vector of every [SEG]."""
    input_ids = input_ids.to(device)
    image_clip = image_pixels.unsqueeze(0).to(device).bfloat16()

    t0 = time.time()
    with torch.no_grad():
        out = model.forward(
            input_ids=input_ids,
            images=image_clip,
            use_cache=False,
            output_hidden_states=True,
            inference=True,
            return_dict=True,
        )
    dt = time.time() - t0

    hidden = out.hidden_states[-1]
    mask = input_ids == seg_token_idx
    pad = hidden.shape[1] - mask.shape[1]
    if pad < 0:
        raise RuntimeError("hidden states shorter than the ids: %d < %d"
                           % (hidden.shape[1], mask.shape[1]))
    if pad > 0:
        # the single <image> token expands into 576 tokens; left-pad realigns it
        mask = torch.cat([torch.zeros((mask.shape[0], pad), dtype=torch.bool,
                                     device=mask.device), mask], dim=1)
    n_seg = int(mask.sum())
    if n_seg == 0:
        raise RuntimeError("the prompt contains no [SEG] token")
    floats = _float_layer(model)(hidden)[mask]
    floats = floats.detach().float().cpu().numpy().reshape(n_seg, -1)
    log("forward: %.1f s over %d tokens -> %d [SEG] slots x %d dim"
        % (dt, int(input_ids.shape[1]), n_seg, floats.shape[1]))
    return input_ids, floats, dt


def main():
    parser = transformers.HfArgumentParser(
        (ModelArguments, DataArguments, TrainingArguments, BypassArguments))
    model_args, data_args, training_args, args = parser.parse_args_into_dataclasses()
    model_args.version = model_args.version or "v1"
    conversation_lib.default_conversation = conversation_lib.conv_templates["v1"]

    os.makedirs(args.out_dir, exist_ok=True)
    with open(args.answer_json, "r", encoding="utf-8") as f:
        answer_text = f.read().strip()
    n_seg_text = answer_text.count("[SEG]")
    log("answer: %s (%d [SEG] slots)" % (args.answer_json, n_seg_text))

    # The JSON the parser will see: [SEG] becomes a throw-away 0.0 so that the
    # text is valid JSON; the real numbers come from the float head.
    json_output = repair_json(
        answer_text.replace("[SEG]", "0.0").replace("[STARTS]", "").replace("[ENDS]", ""),
        return_objects=True)
    key = ("wholebody_garment" if "wholebody_garment" in json_output
           else ("upperbody_garment" if "upperbody_garment" in json_output else None))
    if key is None:
        raise SystemExit("answer has neither wholebody_garment nor upperbody_garment")
    pred_cfg = json_output[key]
    try:
        paths = ordered_float_paths_from_pred(designs_config, pred_cfg)
        log("%s -> %d float design paths:" % (key, len(paths)))
        for p in paths:
            log("   " + p)
    except Exception as exc:  # noqa: BLE001
        paths = []
        log("could not pre-compute the float paths: %r" % (exc,))

    with open(os.path.join(args.out_dir, "prompt_answer.txt"), "w", encoding="utf-8") as f:
        f.write(answer_text)

    if args.dry_floats:
        vals = [float(x) for x in args.dry_floats.split(",") if x.strip()]
        floats = np.asarray(vals, dtype=np.float64).reshape(-1, 1)
        log("DRY RUN: using %d hand-given floats, the model is never loaded" % len(vals))
    else:
        model, tokenizer, seg_token_idx, processor = load_model(model_args, training_args)
        device = model.device
        image_pixels = load_image_pixels(args.image, processor)
        log("image: %s -> %s" % (args.image, tuple(image_pixels.shape)))
        description = args.description
        if args.description_file:
            with open(args.description_file, "r", encoding="utf-8") as fh:
                description = fh.read().strip()
        if args.answer_mode == "user":
            prompt = build_prompt(answer_text, model_args.version)
            ids = tokenizer_image_token(prompt, tokenizer, return_tensors="pt").unsqueeze(0)
        else:
            prompt = build_prompt(description, model_args.version)
            ids = prompt_ids(prompt, answer_text, tokenizer, "assistant")
        log("answer_mode=%s description=%d chars, %d tokens total"
            % (args.answer_mode, len(description), int(ids.shape[1])))
        with open(os.path.join(args.out_dir, "prompt.txt"), "w", encoding="utf-8") as f:
            f.write(prompt)
        _, floats, dt = seg_floats(model, tokenizer, seg_token_idx, image_pixels, ids, device)

    values = floats.reshape(-1).tolist()
    dump = {"paths": paths,
            "raw": values,
            "clipped_01": [min(max(v, 0.0), 1.0) for v in values],
            "answer_json": answer_text}
    with open(os.path.join(args.out_dir, "floats.json"), "w", encoding="utf-8") as f:
        json.dump(dump, f, indent=2)
    for i, v in enumerate(values):
        name = paths[i] if i < len(paths) else "?"
        log("  %2d  %-42s %.4f" % (i, name, v))

    if args.skip_garmentcode:
        log("skip_garmentcode=1: stopping after the floats")
        return

    all_specs = run_garmentcode_parser_float50([], copy.deepcopy(json_output), floats, args.out_dir)
    log("pattern files:")
    for s in all_specs:
        log("   " + s)
    with open(os.path.join(args.out_dir, "spec_files.json"), "w", encoding="utf-8") as f:
        json.dump(all_specs, f, indent=2)


if __name__ == "__main__":
    main()
