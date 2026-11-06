#!/usr/bin/env bash
# CG-WIN: image -> JSON geometry -> sewing-pattern eval on a single Windows GPU.
#
# Usage:  bash win/run_eval_imggen.sh <image-folder> [extra args...]
#   <image-folder>  folder with .png/.jpg inputs (processed as one dataset)
#
# Environment (all optional):
#   CG_DATA_ROOT      where the big files live (default D:/ChatGarment_data)
#   CG_CHECKPOINT     ChatGarment checkpoint  (default $CG_DATA_ROOT/chatgarment_weights/pytorch_model.bin)
#   CG_BASE_CONFIG    llava-v1.5-7b config+tokenizer dir (default $CG_DATA_ROOT/models/llava-v1.5-7b-config)
#   CG_VISION_TOWER   clip-vit-large-patch14-336 dir     (default $CG_DATA_ROOT/models/clip-vit-large-patch14-336)
#   CG_DEVICE_MODE    4bit (default) | auto | cuda | cpu
#   CG_GPU_BUDGET_GB  VRAM given to the weights in auto mode (default: free - 1.2 GiB)
#   CG_MAX_NEW_TOKENS upper bound for generated tokens (default 2048)
#   CG_DIAG           1 = run four model self-checks instead of the eval
#   CG_USE_CACHE      1 (default) keeps the KV cache during generation
#   CG_QUANT_SKIP     module names kept in bf16 in 4bit mode
#                     (default lm_head,float_layer,mm_projector,lora_A,lora_B --
#                      quantising the LoRA adapter destroys the fine-tune)
#   CG_QUANT_VISION   1 = also quantize the CLIP tower (saves ~0.45 GiB)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [ $# -lt 1 ]; then
  echo "usage: bash win/run_eval_imggen.sh <image-folder> [extra args...]" >&2
  exit 2
fi
IMG_DIR="$1"; shift || true

export PYTHONUNBUFFERED=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
# the prompt templates contain non-ASCII characters and the Windows console
# defaults to GBK -> force UTF-8 for stdout/stderr and for file IO.
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
# (expandable_segments is not supported on Windows)
# the venv python may only write inside the repo, so keep every temp/cache here
export TMPDIR="$REPO_ROOT/.tmp" TEMP="$REPO_ROOT/.tmp" TMP="$REPO_ROOT/.tmp"
mkdir -p "$TMPDIR"

DATA_ROOT="${CG_DATA_ROOT:-D:/ChatGarment_data}"
BASE_CONFIG="${CG_BASE_CONFIG:-$DATA_ROOT/models/llava-v1.5-7b-config}"
VISION_TOWER="${CG_VISION_TOWER:-$DATA_ROOT/models/clip-vit-large-patch14-336}"

exec ./.venv/Scripts/python.exe scripts/evaluate_garment_v2_imggen_1float.py \
    --lora_enable True --lora_r 128 --lora_alpha 256 --mm_projector_lr 2e-5 \
    --model_name_or_path "$BASE_CONFIG" \
    --version v1 \
    --data_path ./ \
    --data_path_eval "$IMG_DIR" \
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