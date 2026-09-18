# -*- coding: utf‑8 -*-
"""Step3：汇总.txt → URL标准化、去重、双黑名单过滤 → sources/初处理.txt
方案A：磁盘黑名单原样保留用户手动录入；内存黑名单使用激进标准化用于匹配；
【方案1 函数拆分】
sanitize_for_save() → 输出保存到初处理.txt，温和清洗，保证链接可访问
sanitize_for_blacklist() → 仅内存黑名单比对，激进标准化，不写磁盘
"""
import os
import re
import json
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, quote
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_DIR = os.path.join(BASE_DIR, "sources")
TEMP_BLACKLIST_PATH = os.path.join(SOURCES_DIR, "临时黑名单.txt")
PERM_BLACKLIST_PATH = os.path.join(SOURCES_DIR, "永久黑名单.txt")
TEMP_BLACKLIST_EXPIRE_DAY = 30

DEBUG_PRINT = False

ZERO_WIDTH_PAT = re.compile(r'[\u200b\u200c\u200d\u2060\ufeff]')
LR_SUFFIX_PAT = re.compile(r'(\.m3u8.*?)\$LR•.*$', re.IGNORECASE)
PAREN_CONTENT_PAT = re.compile(r'[(\[].*?[)\]]')
RESOLUTION_TAG_PAT = re.compile(r'(1080p|720p|4K|HD|超清|高清)', re.IGNORECASE)
TRASH_QUERY_KEYS = {"line", "lr", "route", "r", "sp", "channelno", "uid", "userid", "type", "t", "live_type", "srcidx"}


def clean_text(s):
    return s.strip() if s else ""


def sanitize_for_save(raw_url: str) -> str:
    """
    温和清洗：用于写入初处理.txt给step4测速，输出真实可访问URL
    仅清理零宽字符、$LR后缀、空白控制字符；
    ✅不删除query参数、✅不quote路径、✅不移除括号分辨率标签
    """
    u = raw_url
    u = LR_SUFFIX_PAT.sub(r"\1", u)
    u = ZERO_WIDTH_PAT.sub("", u)
    u = re.sub(r'[\r\n\t]', '', u)
    u = re.sub(r'\s+', '', u.strip())
    if not u:
        return ""

    full_protos = ("http://", "https://", "rtsp://", "rtmp://")
    if u.startswith(full_protos):
        pass
    elif u.startswith("rtsp:"):
        u = "rtsp://" + u[5:]
    elif u.startswith("rtmp:"):
        u = "rtmp://" + u[5:]
    else:
        u = "https://" + u
    return u


def sanitize_for_blacklist(raw_url: str) -> str:
    """
    激进标准化：【仅用于内存黑名单匹配，禁止写入磁盘】
    删除垃圾query参数、清理括号分辨率标签、路径quote编码，用于比对命中黑名单
    """
    u = raw_url
    u = LR_SUFFIX_PAT.sub(r"\1", u)
    u = ZERO_WIDTH_PAT.sub("", u)
    u = re.sub(r'[\r\n\t]', '', u)
    u = PAREN_CONTENT_PAT.sub("", u)
    u = RESOLUTION_TAG_PAT.sub("", u)
    u = re.sub(r'\s+', '', u.strip())
    if not u:
        return ""

    full_protos = ("http://", "https://", "rtsp://", "rtmp://")
    if u.startswith(full_protos):
        pass
    elif u.startswith("rtsp:"):
        u = "rtsp://" + u[5:]
    elif u.startswith("rtmp:"):
        u = "rtmp://" + u[5:]
    else:
        u = "https://" + u

    try:
        p = urlparse(u)
        qs_dict = parse_qs(p.query, keep_blank_values=True)
        new_qs = {k: v for k, v in qs_dict.items() if k.lower() not in TRASH_QUERY_KEYS}
        new_query = urlencode(new_qs, doseq=True)
        safe_chars = "/:-,._~"
        new_path = quote(p.path, safe=safe_chars)
        return urlunparse((p.scheme, p.netloc, new_path, p.params, new_query, p.fragment))
    except Exception:
        return u


def load_perm_blacklist() -> set:
    """
    方案A：磁盘文件原样保留用户手动录入；内存使用sanitize_for_blacklist做比对
    """
    data = set()
    if os.path.exists(PERM_BLACKLIST_PATH):
        with open(PERM_BLACKLIST_PATH, "r", encoding="utf‑8") as f:
            for line in f:
                u = clean_text(line)
                if u:
                    norm_u = sanitize_for_blacklist(u)
                    if norm_u:
                        data.add(norm_u)
    return data


def save_perm_blacklist(black_set: set):
    """脚本自动新增黑名单调用，写入的是黑名单激进标准化后的url"""
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
            if len(parts) != 3:
                continue
            url, iso_str, cnt_str = parts
            try:
                enter_dt = datetime.fromisoformat(iso_str)
                cnt = int(cnt_str)
                norm_url = sanitize_for_blacklist(url)
                if norm_url:
                    result[norm_url] = {"enter_time": enter_dt, "count": cnt}
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


def clean_expired_temp_blacklist(temp_bl):
    now = datetime.now()
    keep = {}
    released = set()
    for url, info in temp_bl.items():
        expire = info["enter_time"] + timedelta(days=TEMP_BLACKLIST_EXPIRE_DAY)
        if now >= expire:
            released.add(url)
        else:
            keep[url] = info
    return keep, released


def main():
    print("[STEP3‑PROGRESS] ======步骤3 汇总直播源初步处理开始======")
    merged_file = os.path.join(SOURCES_DIR, "汇总.txt")
    if not os.path.exists(merged_file):
        print("[WARN‑STEP3]汇总.txt不存在，直接退出")
        return

    perm_black = load_perm_blacklist()
    temp_black = load_temp_blacklist()
    temp_black, released_url_set = clean_expired_temp_blacklist(temp_black)
    save_temp_blacklist(temp_black)

    count_perm_filter = 0
    count_temp_filter = 0
    count_dup = 0
    count_bad = 0
    url_seen_save = set()   # 去重使用【保存版url】（真实访问url）
    output_lines = []

    with open(merged_file, "r", encoding="utf‑8") as f:
        raw_lines = [clean_text(l) for l in f if clean_text(l)]

    print(f"[STEP3‑DEBUG]输入原始行数 {len(raw_lines)}")

    for line in raw_lines:
        if "," not in line:
            count_bad += 1
            continue
        name, url_part = line.split(",", 1)
        raw_url = url_part.split("#")[0].strip()
        comment = "#" + url_part.split("#")[1] if "#" in url_part else ""

        # 两个版本
        save_url = sanitize_for_save(raw_url)          # 输出保存给step4
        black_check_url = sanitize_for_blacklist(raw_url) # 用于黑名单匹配

        if not save_url or not name:
            count_bad += 1
            continue

        if DEBUG_PRINT:
            print(f"[DEBUG] save_url={repr(save_url)} black_key={repr(black_check_url)} perm_hit={black_check_url in perm_black} temp_hit={black_check_url in temp_black}")

        # 使用黑名单专用key做过滤判断
        if black_check_url in perm_black:
            count_perm_filter += 1
            continue
        if black_check_url in temp_black:
            count_temp_filter += 1
            continue
        # 去重依据：真实可访问的save_url，避免不同黑名单key，但实际访问链接一样重复输出
        if save_url in url_seen_save:
            count_dup += 1
            continue

        url_seen_save.add(save_url)
        output_lines.append(f"{clean_text(name)},{save_url}{comment}")

    out_file = os.path.join(SOURCES_DIR, "初处理.txt")
    with open(out_file, "w", encoding="utf‑8") as f:
        f.write("\n".join(output_lines))

    print(f"[STEP3‑FILTER]永久黑名单过滤:{count_perm_filter}；临时黑名单过滤:{count_temp_filter}；重复url:{count_dup}；坏行丢弃:{count_bad}；输出初处理.txt {len(output_lines)}条")

    tmp_release = os.path.join(BASE_DIR, ".step3_released.tmp.json")
    with open(tmp_release, "w", encoding="utf‑8") as f:
        json.dump(list(released_url_set), f, ensure_ascii=False)


if __name__ == "__main__":
    main()