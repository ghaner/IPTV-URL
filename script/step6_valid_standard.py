# -*- coding: utf‑8 -*-
"""Step6：有效源标准化处理；输出sources/有效标准化直播源.txt、sources/有效直播源.m3u"""
import sys
import os
import re
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
SOURCES_DIR = os.path.join(BASE_DIR, "sources")

ZERO_WIDTH_PAT = re.compile(r'[\u200b\u200c\u200d\u2060\ufeff]')

def clean_text(s):
    return s.strip() if s else ""

def load_json(path):
    if not os.path.exists(path):
        return dict()
    try:
        with open(path, "r", encoding="utf‑8") as f:
            return json.load(f)
    except Exception:
        return dict()

def clean_m3u_display_name(raw_name: str) -> str:
    n = clean_text(raw_name)
    n = re.sub(r"\$.*", "", n)
    n = re.sub(r"\(.*?\)", "", n)
    n = re.sub(r"\[.*?\]", "", n)
    n = re.sub(r"(高清|超清|1080p|720p|4K|HD)", "", n, flags=re.IGNORECASE)
    n = ZERO_WIDTH_PAT.sub("", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n

def clean_channel_name(raw_name: str) -> str:
    name = clean_text(raw_name)
    name = re.sub(r"\$.*", "", name)
    name = re.sub(r"\(.*?\)", "", name)
    name = re.sub(r"\[.*?\]", "", name)
    name = re.sub(r"[‑–—―−]", "-", name)
    name = re.sub(r"(高清|超清|1080p|720p|4K|HD)", "", name, flags=re.IGNORECASE)
    name = re.sub(r"CCTV0?(\d+)", r"CCTV‑\1", name)
    name = re.sub(r"\s+", "", name)
    return name

def main():
    print("[STEP6‑PROGRESS] ======步骤6 有效源标准化处理开始======")
    valid_path = os.path.join(SOURCES_DIR, "有效直播源.txt")
    if not os.path.exists(valid_path):
        print("[WARN‑STEP6]有效直播源.txt不存在，退出")
        return

    raw_list = []
    with open(valid_path, "r", encoding="utf‑8") as f:
        raw_list = f.readlines()
    out_lines = []
    for l in raw_list:
        l = clean_text(l)
        if "," in l:
            name, url_part = l.split(",",1)
            url = url_part.split("#")[0].strip()
            out_lines.append(f"{clean_text(name)},{url}")
    out_lines = sorted(list(set(out_lines)), key=lambda x: x.split(",")[0])
    std_out = os.path.join(SOURCES_DIR, "有效标准化直播源.txt")
    with open(std_out, "w", encoding="utf‑8") as f:
        f.write("\n".join(out_lines))
    print(f"[STEP6‑DEBUG]有效标准化直播源.txt输出，{len(out_lines)}条")

    epg_map = load_json(os.path.join(CONFIG_DIR, "tvg_id_map.json"))
    m3u_all = os.path.join(SOURCES_DIR, "有效直播源.m3u")
    with open(m3u_all, "w", encoding="utf‑8") as fm:
        fm.write("#EXTM3U\n")
        for line in out_lines:
            n,u = line.split(",",1)
            lookup_n = clean_channel_name(n)
            disp_n = clean_m3u_display_name(n)
            tvg_id = epg_map.get(lookup_n, "")
            fm.write(f'#EXTINF:-1 tvg‑id="{tvg_id}" tvg‑name="{disp_n}",{disp_n}\n{u}\n')

    step6_tmp = os.path.join(BASE_DIR, ".step6_std_sources.tmp.json")
    with open(step6_tmp, "w", encoding="utf‑8") as f:
        json.dump(out_lines, f, ensure_ascii=False)
    print(f"[STEP6‑END]步骤6完成")

if __name__ == "__main__":
    main()