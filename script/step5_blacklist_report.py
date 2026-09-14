# -*- coding: utf‑8 -*-
"""Step5：测速临时文件原子重命名、更新黑名单、生成源质量报告"""
import json
import os
from collections import defaultdict
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_DIR = os.path.join(BASE_DIR, "sources")
LOG_DIR = os.path.join(BASE_DIR, "log")
os.makedirs(LOG_DIR, exist_ok=True)

MAX_CONSECUTIVE_FAIL = 3
MAX_TEMP_BLACKLIST_ENTRY = 4
PERM_BLACKLIST_PATH = os.path.join(SOURCES_DIR, "永久黑名单.txt")
TEMP_BLACKLIST_PATH = os.path.join(SOURCES_DIR, "临时黑名单.txt")

def clean_text(s):
    return s.strip() if s else ""

def get_run_trigger_type() -> str:
    return os.environ.get("GITHUB_EVENT_NAME", "")

def load_json(path):
    if not os.path.exists(path):
        return [] if "DOWNLOAD_SOURCE_URLS" in path else dict()
    try:
        with open(path, "r", encoding="utf‑8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return data
        return [] if "DOWNLOAD_SOURCE_URLS" in path else dict()
    except Exception:
        return [] if "DOWNLOAD_SOURCE_URLS" in path else dict()

def load_perm_blacklist() -> set:
    data = set()
    if os.path.exists(PERM_BLACKLIST_PATH):
        with open(PERM_BLACKLIST_PATH, "r", encoding="utf‑8") as f:
            for line in f:
                u = clean_text(line)
                if u:
                    data.add(u)
    return data

def save_perm_blacklist(black_set: set):
    with open(PERM_BLACKLIST_PATH, "w", encoding="utf‑8") as f:
        for u in sorted(black_set):
            f.write(u + "\n")

def load_temp_blacklist():
    result = {}
    if not os.path.exists(TEMP_BLACKLIST_PATH):
        return result
    with open(TEMP_BLACKLIST_PATH, "r", encoding="utf‑8") as f:
        for line in f:
            line = clean_text(line)
            if not line:
                continue
            parts = line.split("|")
            if len(parts) !=3:
                continue
            url, iso_str, cnt_str = parts
            try:
                enter_dt = datetime.fromisoformat(iso_str)
                cnt = int(cnt_str)
                result[url] = {"enter_time": enter_dt, "count": cnt}
            except Exception:
                continue
    return result

def save_temp_blacklist(bl_dict):
    lines = []
    for url, info in bl_dict.items():
        iso = info["enter_time"].isoformat()
        count = info["count"]
        lines.append(f"{url}|{iso}|{count}")
    with open(TEMP_BLACKLIST_PATH, "w", encoding="utf‑8") as f:
        for l in lines:
            f.write(l + "\n")

def main():
    print("[STEP5‑PROGRESS] ======步骤5测速结果&黑名单&质量报告开始======")
    smap_path = os.path.join(BASE_DIR, ".step1_sourcemap.tmp.json")
    source_map = load_json(smap_path) if os.path.exists(smap_path) else dict()
    rel_path = os.path.join(BASE_DIR, ".step3_released.tmp.json")
    released_urls = set(json.load(open(rel_path, "r", encoding="utf‑8"))) if os.path.exists(rel_path) else set()
    res_path = os.path.join(BASE_DIR, ".step4_results.tmp.json")
    results = load_json(res_path) if os.path.exists(res_path) else []

    valid_tmp = os.path.join(SOURCES_DIR, ".valid.tmp")
    fail_tmp = os.path.join(SOURCES_DIR, ".fail.tmp")
    valid_out = os.path.join(SOURCES_DIR, "有效直播源.txt")
    fail_out = os.path.join(SOURCES_DIR, "测速失败.txt")
    if os.path.exists(valid_tmp):
        os.replace(valid_tmp, valid_out)
    if os.path.exists(fail_tmp):
        os.replace(fail_tmp, fail_out)
    print(f"[STEP5‑DEBUG]测速文件落地；有效直播源.txt、测速失败.txt已更新")

    if len(results) == 0:
        print("[WARN‑STEP5]测速结果为空，跳过黑名单与报告")
        return

    trigger = get_run_trigger_type()
    perm_bl = load_perm_blacklist()
    temp_bl = load_temp_blacklist()
    url_consec_fail = {u:0 for u in released_urls}
    for item in results:
        url = item["url"]
        if url not in url_consec_fail:
            url_consec_fail[url] =0
        if item["valid"]:
            url_consec_fail[url] = 0
        else:
            if trigger == "schedule":
                url_consec_fail[url] += 1

    if trigger == "schedule":
        new_temp_add = set()
        for url, fail_cnt in url_consec_fail.items():
            if fail_cnt >= MAX_CONSECUTIVE_FAIL and url not in temp_bl:
                new_temp_add.add(url)
        for u in new_temp_add:
            old_count = temp_bl[u]["count"] if u in temp_bl else 0
            temp_bl[u] = {"enter_time": datetime.now(), "count": old_count+1}
        move_perm = set()
        for u in list(temp_bl.keys()):
            if temp_bl[u]["count"] >= MAX_TEMP_BLACKLIST_ENTRY:
                move_perm.add(u)
                del temp_bl[u]
        if move_perm:
            perm_bl.update(move_perm)
            save_perm_blacklist(perm_bl)
        save_temp_blacklist(temp_bl)
        print(f"[BLACKLIST‑INFO]新增临时黑名单:{len(new_temp_add)}；升级永久黑名单:{len(move_perm)}")
    else:
        print("[BLACKLIST‑INFO]手动触发，不更新黑名单")

    total_stat = defaultdict(int)
    valid_stat = defaultdict(int)
    for r in results:
        src = r["source"]
        total_stat[src] += 1
        if r["valid"]:
            valid_stat[src] += 1
    report = []
    for src_url, items in source_map.items():
        t = total_stat.get(src_url,0)
        v = valid_stat.get(src_url,0)
        f = t - v
        frate = f/t if t>0 else 0
        report.append({
            "source_url": src_url,
            "total": t,
            "valid": v,
            "failed": f,
            "failure_rate": round(frate,4),
            "available_rate": round(1‑frate,4)
        })
    report_file = os.path.join(LOG_DIR, "source_quality_report.json")
    with open(report_file, "w", encoding="utf‑8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    bad_top3 = sorted(report, key=lambda x:x["failure_rate"], reverse=True)[:3]
    bad_url_list = [x["source_url"] for x in bad_top3]
    bad_out = os.path.join(SOURCES_DIR, "失效源地址.txt")
    with open(bad_out, "w", encoding="utf‑8") as f:
        f.write("\n".join(bad_url_list))
    print(f"[STEP5‑END]源质量报告输出log/source_quality_report.json；失效率TOP3:{bad_url_list}")

if __name__ == "__main__":
    main()