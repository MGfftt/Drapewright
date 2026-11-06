import zipfile, pickletools, sys, io, collections
path = r"D:\ChatGarment_data\chatgarment_weights\pytorch_model.bin"
z = zipfile.ZipFile(path)
names = z.namelist()
print("entries:", len(names))
pk = [n for n in names if n.endswith("data.pkl")]
print("pickle:", pk)
data = z.read(pk[0])
strs = []
for op, arg, pos in pickletools.genops(io.BytesIO(data)):
    if op.name in ("SHORT_BINUNICODE", "BINUNICODE", "BINUNICODE8") and isinstance(arg, str):
        strs.append(arg)
print("strings:", len(strs))
keys = [s for s in strs if ("." in s) and not s.startswith("collections")]
print("dotted:", len(keys))
pref = collections.Counter()
for k in keys:
    parts = k.split(".")
    pref[".".join(parts[:2]) if len(parts) > 1 else parts[0]] += 1
print("--- top-2-level prefixes (count):")
for k, v in pref.most_common(40):
    print(f"{v:6d}  {k}")
lora = [k for k in keys if "lora" in k]
print("lora keys:", len(lora), lora[:5])
print("float_layer keys:", [k for k in keys if "float_layer" in k][:8])
print("vision_tower keys:", len([k for k in keys if k.startswith("vision_tower")]))
print("mm_projector keys:", [k for k in keys if "mm_projector" in k][:6])
print("sample keys:", keys[:6])
