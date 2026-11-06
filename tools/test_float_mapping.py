import os, sys, json, pprint
REPO = r"C:/Users/41239/Desktop/科研/ChatGarment-main"
os.chdir(REPO)
sys.path.insert(0, REPO)
from llava.json_fixer import repair_json
from llava.garment_utils_v2 import ordered_float_paths_from_pred, designs_config, all_float_paths

raw = None
for line in open(os.path.join(REPO, 'runs/chatgarment_weights/win_1img_img_recon/raw_q1.txt'), encoding='utf-8'):
    if line.startswith('RAW='):
        raw = line[4:].strip()
print('raw chars', len(raw), 'n_seg', raw.count('[SEG]'))

# 1) upstream route: strip the markers, then repair
stripped = raw.replace('[STARTS]','').replace('[SEG]','').replace('[ENDS]','')
try:
    up = repair_json(stripped, return_objects=True)
    print('UPSTREAM_PARSE keys:', list(up.keys()))
except Exception as e:
    print('UPSTREAM_PARSE failed:', type(e).__name__, e)
    up = None

# 2) CG-WIN route: neutralise the markers with a numeric placeholder first
filled = raw.replace('[SEG]', '0.0')
try:
    cg = repair_json(filled, return_objects=True)
    print('CGWIN_PARSE keys:', list(cg.keys()))
except Exception as e:
    print('CGWIN_PARSE failed:', type(e).__name__, e)
    cg = None

for tag, obj in (('UPSTREAM', up), ('CGWIN', cg)):
    if not isinstance(obj, dict) or 'wholebody_garment' not in obj:
        continue
    paths = ordered_float_paths_from_pred(designs_config, obj['wholebody_garment'])
    print(tag, 'n_mapped_paths =', len(paths), '(segs', raw.count('[SEG]'), ')')
    if tag == 'CGWIN':
        for p in paths:
            print('   ', p)
