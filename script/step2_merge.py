# -*- coding: utf‑8 -*-
"""Step2：合并 sources/下载源.txt + sources/有效直播源.txt → sources/汇总.txt"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_DIR = os.path.join(BASE_DIR, "sources")

def clean_text(s):
    return s.strip() if s else ""

def main():
    print("[STEP2‑PROGRESS] ======步骤2 汇总新旧直播源开始======")
    download_path = os.path.join(SOURCES_DIR, "下载源.txt")
    valid_old_path = os.path.join(SOURCES_DIR, "有效直播源.txt")
    merged_list = []
    cnt_dl = 0
    cnt_old_valid = 0

    if os.path.exists(download_path):
        with open(download_path, "r", encoding="utf‑8") as f:
            dl_lines = [clean_text(l) for l in f if clean_text(l)]
            merged_list.extend(dl_lines)
            cnt_dl = len(dl_lines)

    if os.path.exists(valid_old_path):
        with open(valid_old_path, "r", encoding="utf‑8") as f:
            old_lines = [clean_text(l) for l in f if clean_text(l)]
            merged_list.extend(old_lines)
            cnt_old_valid = len(old_lines)

    out = os.path.join(SOURCES_DIR, "汇总.txt")
    with open(out, "w", encoding="utf‑8") as f:
        f.write("\n".join(merged_list))
    print(f"[STEP2‑END]汇总.txt输出；下载源:{cnt_dl}；旧有效源:{cnt_old_valid}；合计{len(merged_list)}条")

if __name__ == "__main__":
    main()