# -*- coding: utf‑8 -*-
"""Step8：读取step7分类运算结果，输出category目录 *.txt / *.m3u；处理EPG标签"""
import os
import json
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
CATEGORY_DIR = os.path.join(BASE_DIR, "category")
os.makedirs(CATEGORY_DIR, exist_ok=True)

EPG_ALLOW_CATS = {"CCTV","卫视","地方台"}
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
    print("[STEP8‑PROGRESS] ======步骤8 分类结果输出txt/m3u开始======")
    step7_tmp = os.path.join(BASE_DIR, ".step7_cat_result.tmp.json")
    if not os.path.exists(step7_tmp):
        print("[ERROR‑STEP8]找不到step7分类运算临时文件，退出")
        return
    with open(step7_tmp, "r", encoding="utf‑8") as f:
        category_result = json.load(f)

    for fn in os.listdir(CATEGORY_DIR):
        os.remove(os.path.join(CATEGORY_DIR, fn))

    epg_map = load_json(os.path.join(CONFIG_DIR, "tvg_id_map.json"))
    epg_cfg = load_json(os.path.join(CONFIG_DIR, "epg.json"))
    epg_url = epg_cfg.get("epg_url","")
    tvg_logo_base = epg_cfg.get("tvg_logo_base","").rstrip("/")

    gen_count = 0
    for cat_name, item_list in category_result.items():
        if not isinstance(item_list,list) or len(item_list) == 0:
            continue
        txt_path = os.path.join(CATEGORY_DIR, f"{cat_name}.txt")
        with open(txt_path, "w", encoding="utf‑8") as f:
            f.write("\n".join(item_list))
        m3u_path = os.path.join(CATEGORY_DIR, f"{cat_name}.m3u")
        with open(m3u_path, "w", encoding="utf‑8") as f:
            f.write("#EXTM3U\n")
            if cat_name in EPG_ALLOW_CATS and epg_url:
                f.write(f'#EPGURL={epg_url}\n')
            for line in item_list:
                n,u = line.split(",",1)
                lookup_n = clean_channel_name(n)
                disp_n = clean_m3u_display_name(n)
                tid = epg_map.get(lookup_n, "")
                if cat_name in EPG_ALLOW_CATS and tid and tvg_logo_base:
                    logo = f"{tvg_logo_base}/{tid}.png"
                    f.write(f'#EXTINF:-1 tvg‑id="{tid}" tvg‑name="{disp_n}" tvg‑logo="{logo}",{disp_n}\n{u}\n')
                else:
                    f.write(f'#EXTINF:-1 tvg‑id="{tid}" tvg‑name="{disp_n}",{disp_n}\n{u}\n')
        gen_count += 1
    print(f"[STEP8‑END]分类文件输出完成；共生成 {gen_count} 组txt+m3u文件到category目录")

if __name__ == "__main__":
    main()