## Installation

#### 1. Clone this repository
```bash
git clone git@github.com:biansy000/ChatGarment.git
cd ChatGarment
```

#### 2. Install Dependencies
If you are not using Linux, see instructions for [macOS](https://github.com/haotian-liu/LLaVA/blob/main/docs/macOS.md) and [Windows](https://github.com/haotian-liu/LLaVA/blob/main/docs/Windows.md).

```Shell
conda create -n chatgarment python=3.10 -y
conda activate chatgarment
pip install --upgrade pip  # enable PEP 660 support
pip install -e ".[train]"
pip install flash-attn --no-build-isolation
```

#### 3. Install [GarmentCodeRC](https://github.com/biansy000/GarmentCodeRC)
Follow installation instructions in its repository.


#### 4. Download Pretrained Weights
Put the [Pretrained weights](https://sjtueducn-my.sharepoint.com/:u:/g/personal/biansiyuan_sjtu_edu_cn/EQayoB8ie7ZIsFrjLWdBASQBFexZHXcGjrS6ghgGCjIMzw?e=o60Y65) to ``checkpoints/try_7b_lr1e_4_v3_garmentcontrol_4h100_v4_final/pytorch_model.bin``.

#### 5. Update Paths in Code
Modify the following lines in relevant Python files:
```Python
sys.path.insert(1, '/is/cluster/fast/sbian/github/chatgarment_private') # path of the current ChatGarment repo
sys.path.insert(1, '/is/cluster/fast/sbian/github/GarmentCodeV2/') # path of GarmentCodeRC repo
```
Replace with their actual local paths.

#### 6. Add Soft Link 
Add the softlink of ``assets`` folder in ``GarmentCodeRC`` repo:
```Shell
ln -s path_to_garmentcode_assets assets
```
---

## Windows / single-GPU notes (this checkout)

This copy runs on a plain Windows machine with an 8 GB laptop GPU (RTX 5060, sm_120): no
conda, no DeepSpeed, no flash-attn, no CUDA toolkit, no OpenAI key. The steps above are
replaced by the ones in **[../win/README.md](../win/README.md)** (sections 3.1-3.5), in short:

* Python 3.11.9 venv + `torch 2.7.1+cu128` from a mirror (2.1.2 has no sm_120 kernel);
* the 15 GB checkpoint is quantised to NF4 at load time (LoRA adapters kept in bf16!);
* GarmentCodeRC goes to `repos/GarmentCodeRC-main`, `assets` is a **junction**
  (`New-Item -ItemType Junction`), and no code path is rewritten by hand - all paths are
  resolved relative to the repo root by `llava/win_compat.py`;
* the pretrained weights are fetched from `sy000/chatgarment_extrafiles` on hf-mirror.com
  (the SharePoint link above is dead);
* run: `bash win/run_eval_imggen.sh <image-folder>`; remove everything:
  `powershell -File win/cleanup.ps1 -Execute`.

Two upstream issues had to be fixed for the released weights, both documented in
`win/README.md` section 6: the LoRA adapter must not be quantised, and the checkpoint emits a
variable number of bare `[SEG]` tokens (upstream assumes 76/152 index-suffixed ones).
