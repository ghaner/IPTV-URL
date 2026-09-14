# -*- coding: utf‑8 -*-
"""Step7：有效源分类运算，内置全部分类逻辑；仅做计算，不写磁盘文件"""
import os
import json
import functools
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(BASE_DIR, "config")

def _load_json_keys(filename: str):
    fp = os.path.join(CONFIG, filename)
    if not os.path.exists(fp):
        return []
    try:
        with open(fp, "r", encoding="utf‑8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return list(data.keys())
        return []
    except Exception:
        return []

@functools.lru_cache(maxsize=1)
def load_all_json_data():
    raw = {
        "base_categories": _load_json_keys("base_categories.json"),
        "province": _load_json_keys("province.json"),
        "city": _load_json_keys("city.json"),
        "singer": _load_json_keys("singer.json"),
        "actor": _load_json_keys("actor.json"),
        "teleplay": _load_json_keys("teleplay.json"),
        "sceniczone": _load_json_keys("sceniczone.json"),
        "documentary": _load_json_keys("documentary.json"),
        "taiwan": _load_json_keys("taiwan.json"),
        "show": _load_json_keys("show.json"),
        "mtcommentary": _load_json_keys("MTcommentary.json"),
    }
    lower = {k: [i.lower() for i in v] for k, v in raw.items()}
    return {"raw": raw, "lower": lower}

def get_channel_categories(name: str, link: str):
    name_raw = name.strip()
    link_raw = link.strip()
    name_lower = name_raw.lower()
    link_lower = link_raw.lower()
    result_cats = set()
    cache_data = load_all_json_data()
    raw_data = cache_data["raw"]
    lower_data = cache_data["lower"]

    base_categories = raw_data["base_categories"]
    PROVINCE_LIST = raw_data["province"]
    PROVINCE_LOWER = lower_data["province"]
    CITY_LIST = raw_data["city"]
    CITY_LOWER = lower_data["city"]
    SINGER_NAMES = raw_data["singer"]
    SINGER_LOWER = lower_data["singer"]
    ACTOR_NAMES = raw_data["actor"]
    ACTOR_LOWER = lower_data["actor"]
    TV_DRAMA_NAMES = raw_data["teleplay"]
    TV_DRAMA_LOWER = lower_data["teleplay"]
    SCENIC_ZONE_NAMES = raw_data["sceniczone"]
    SCENIC_ZONE_LOWER = lower_data["sceniczone"]
    DOCUMENTARY_NAMES = raw_data["documentary"]
    DOCUMENTARY_LOWER = lower_data["documentary"]
    TAIWAN_NAMES = raw_data["taiwan"]
    TAIWAN_LOWER = lower_data["taiwan"]
    SHOW_LINKS = raw_data["show"]
    SHOW_LOWER = lower_data["show"]
    MTCOMMENTARY_LINKS = raw_data["mtcommentary"]
    MTCOMMENTARY_LOWER = lower_data["mtcommentary"]

    if "/huya" in link_lower:
        result_cats.add("huya")
    if "/douyu" in link_lower:
        result_cats.add("douyu")
    if "/bilibili" in link_lower:
        result_cats.add("bilibili")
    if "/yy/" in link_lower:
        result_cats.add("yy")

    for show_raw, show_low in zip(SHOW_LINKS, SHOW_LOWER):
        if show_low in link_lower:
            result_cats.add("综艺")
    for mt_raw, mt_low in zip(MTCOMMENTARY_LINKS, MTCOMMENTARY_LOWER):
        if mt_low in link_lower:
            result_cats.add("影视解说")
    for doc_raw, doc_low in zip(DOCUMENTARY_NAMES, DOCUMENTARY_LOWER):
        if doc_low in link_lower:
            result_cats.add("纪录片")
    for dr_raw, dr_low in zip(TV_DRAMA_NAMES, TV_DRAMA_LOWER):
        if dr_low in link_lower:
            result_cats.add("电视剧")

    for cat in base_categories:
        if cat.lower() in name_lower:
            result_cats.add(cat)

    movie_comment_keywords = ["说电影", "看电影", "侃电影", "讲电影", "撩电影"]
    for kw in movie_comment_keywords:
        if kw in name_lower:
            result_cats.add("电影")
            result_cats.add("影视解说")

    if "dj" in name_lower:
        result_cats.add("音乐")
    if "风云" in name_lower:
        result_cats.add("CCTV")
    for sport_kw in ["足球", "高尔夫", "网球"]:
        if sport_kw in name_lower:
            result_cats.add("体育")
    if "凤凰" in name_lower:
        result_cats.add("凤凰卫视")
    for scenic_kw in ["风景", "景区", "泰山"]:
        if scenic_kw in name_lower:
            result_cats.add("景区")
    for sz_raw, sz_low in zip(SCENIC_ZONE_NAMES, SCENIC_ZONE_LOWER):
        if sz_low in name_lower:
            result_cats.add("景区")
    if "相声" in name_lower or "小品" in name_lower:
        result_cats.add("相声小品")
    if "chc" in name_lower:
        result_cats.add("CHC")
    if "tvb" in name_lower or "翡翠台" in name_lower:
        result_cats.add("TVB")
    if "财经" in name_lower:
        result_cats.add("财经")

    for dr_raw, dr_low in zip(TV_DRAMA_NAMES, TV_DRAMA_LOWER):
        if dr_low in name_lower:
            result_cats.add("电视剧")
    for doc_raw, doc_low in zip(DOCUMENTARY_NAMES, DOCUMENTARY_LOWER):
        if doc_low in name_lower:
            result_cats.add("纪录片")
    for tw_raw, tw_low in zip(TAIWAN_NAMES, TAIWAN_LOWER):
        if tw_low in name_lower:
            result_cats.add("台湾")
    for s_raw, s_low in zip(SINGER_NAMES, SINGER_LOWER):
        if s_low in name_lower:
            result_cats.add("歌手")
    for a_raw, a_low in zip(ACTOR_NAMES, ACTOR_LOWER):
        if a_low in name_lower:
            result_cats.add("演员")
    for p_raw, p_low in zip(PROVINCE_LIST, PROVINCE_LOWER):
        if p_low in name_lower:
            result_cats.add(p_raw)
    for c_raw, c_low in zip(CITY_LIST, CITY_LOWER):
        if c_low in name_lower:
            result_cats.add(c_raw)

    if not result_cats:
        result_cats.add("未分类")
    return list(result_cats)

def main():
    print("[STEP7‑PROGRESS] ======步骤7 有效源分类运算开始======")
    step6_tmp = os.path.join(BASE_DIR, ".step6_std_sources.tmp.json")
    if not os.path.exists(step6_tmp):
        print("[ERROR‑STEP7]找不到step6输出的标准化源临时文件，退出")
        return
    with open(step6_tmp, "r", encoding="utf‑8") as f:
        std_source_list = json.load(f)

    cat_map = defaultdict(list)
    match_cnt = 0
    unclass_cnt = 0
    for line in std_source_list:
        name, url = line.split(",",1)
        cats = get_channel_categories(name, url)
        if cats:
            match_cnt +=1
            for c in cats:
                cat_map[c].append(line)
        else:
            cat_map["未分类"].append(line)
            unclass_cnt +=1

    step7_out_tmp = os.path.join(BASE_DIR, ".step7_cat_result.tmp.json")
    with open(step7_out_tmp, "w", encoding="utf‑8") as f:
        json.dump(dict(cat_map), f, ensure_ascii=False, indent=2)
    print(f"[STEP7‑DEBUG]分类运算完成；命中规则:{match_cnt}；归入未分类:{unclass_cnt}")
    print("[STEP7‑END]步骤7完成")

if __name__ == "__main__":
    main()