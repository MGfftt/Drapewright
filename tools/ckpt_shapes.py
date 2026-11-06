"""Print shapes of a few keys from a torch zip checkpoint without materialising it."""
import sys, torch
path = sys.argv[1]
keys = sys.argv[2:] or None
sd = torch.load(path, map_location="cpu", mmap=True, weights_only=True)
if keys:
    for k in keys:
        print(k, tuple(sd[k].shape), sd[k].dtype, flush=True)
else:
    want = [k for k in sd if k.endswith("embed_tokens.weight") or k.endswith("lm_head.weight") or "vision_tower" in k or k.endswith("mm_projector.0.weight")]
    for k in want:
        print(k, tuple(sd[k].shape), sd[k].dtype, flush=True)
    print("n_keys", len(sd))
