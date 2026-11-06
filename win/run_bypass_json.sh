#!/usr/bin/env bash
# CG-WIN: "VLM bypass" run - the JSON answer is written by us, the model only
# guesses the floats.  Same model setup / environment as win/run_eval_imggen.sh.
#
# Usage:
#   bash win/run_bypass_json.sh --image R-C.jpg --answer_json cases/rc_dress/answer.json --tag rc_dress
#   bash win/run_bypass_json.sh --image R-C.jpg --answer_json cases/rc_dress/answer.json \
#        --tag rc_dry --dry_floats 0.35,0.1,0.1,0.15,0.9,0.4,0   # CPU-only smoke test
#
# Extra flags understood by the python side (scripts/bypass_vlm_from_json_1float.py):
#   --dry_floats  comma separated floats, skips the checkpoint entirely
#   --skip_garmentcode 1   stop after the float prediction
#   --out_dir     where design.yaml / pattern / floats.json are written
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

export PYTHONUNBUFFERED=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
export TMPDIR="$REPO_ROOT/.tmp" TEMP="$REPO_ROOT/.tmp" TMP="$REPO_ROOT/.tmp"
mkdir -p "$TMPDIR"

DATA_ROOT="${CG_DATA_ROOT:-D:/ChatGarment_data}"
BASE_CONFIG="${CG_BASE_CONFIG:-$DATA_ROOT/models/llava-v1.5-7b-config}"
VISION_TOWER="${CG_VISION_TOWER:-$DATA_ROOT/models/clip-vit-large-patch14-336}"

exec ./.venv/Scripts/python.exe scripts/bypass_vlm_from_json_1float.py \
    --lora_enable True --lora_r 128 --lora_alpha 256 --mm_projector_lr 2e-5 \
    --model_name_or_path "$BASE_CONFIG" \
    --version v1 \
    --data_path ./ \
    --data_path_eval ./ \
    --image_folder ./ \
    --vision_tower "$VISION_TOWER" \
    --mm_projector_type mlp2x_gelu \
    --mm_vision_select_layer -2 \
    --mm_use_im_start_end False \
    --mm_use_im_patch_token False \
    --image_aspect_ratio pad \
    --group_by_modality_length True \
    --bf16 True \
    --output_dir ./checkpoints/llava-v1.5-7b-task-lora \
    --num_train_epochs 1 \
    --per_device_train_batch_size 1 \
    --per_device_eval_batch_size 1 \
    --gradient_accumulation_steps 1 \
    --evaluation_strategy no \
    --save_strategy steps \
    --save_steps 50000 \
    --save_total_limit 1 \
    --learning_rate 2e-4 \
    --weight_decay 0. \
    --warmup_ratio 0.03 \
    --lr_scheduler_type cosine \
    --logging_steps 1 \
    --tf32 True \
    --model_max_length 3072 \
    --gradient_checkpointing True \
    --dataloader_num_workers 0 \
    --lazy_preprocess True \
    --report_to none \
    "$@"
