
import re, json, io
p = r"C:\Users\41239\Desktop\科研\ChatGarment-main\runs\chatgarment_weights\win_1img_img_recon\vis_new\valid_garment_win_1img\80141ce740f489f1d2f57a03f32c7577a28b62a6ac790a0d9ed8a18d961c2918\output.txt"
t = io.open(p, encoding="utf-8").read()
print("chars", len(t))
# blank slots: ":<spaces>," or ":<spaces>}" or ":<spaces>]"
blanks = re.findall(r":(\s{1,6})(?=[,}\]])", t)
print("blank slots:", len(blanks), "widths:", sorted(set(len(b) for b in blanks)))
print("[SEG] occurrences:", t.count("[SEG]"), "STARTS:", t.count("[STARTS]"), "ENDS:", t.count("[ENDS]"))
# how many keys mention float-ish fields
print("total ':' count:", t.count(":"))
