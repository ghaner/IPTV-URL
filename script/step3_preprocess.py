# -*- coding: utf‑8 -*-
"""Step3：汇总.txt → URL标准化、去重、双黑名单过滤 → sources/初处理.txt
方案A：永久黑名单内存标准化，磁盘文件不修改，兼容【脚本自动生成】+【用户手动添加】
注意：磁盘永久黑名单保持用户原始录入文本；仅内存中做标准化用于匹配过滤
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

# 调试开关：True打印每条标准化URL，排查黑名单匹配；正常使用改为False
DEBUG_PRINT = False

ZERO_WIDTH_PAT = re.compile(r'[\u200b\u200c\u200d\u2060\ufeff]')
LR_SUFFIX_PAT = re.compile(r'(\.m3u8.*?)\$LR•.*$', re.IGNORECASE)
PAREN_CONTENT_PAT = re.compile(r'[(\[].*?[)\]]')
RESOLUTION_TAG_PAT = re.compile(r'(1080p|720p|4K|HD|超清|高清)', re.IGNORECASE)
TRASH_QUERY_KEYS = {"line", "lr", "route", "r", "sp", "channelno", "uid", "userid", "type", "t", "live_type", "srcidx"}


def clean_text(s):
    return s.strip() if s else ""


def load_perm_blacklist() -> set:
    """
    方案A逻辑：
    读取磁盘永久黑名单文件，磁盘文件原样保留用户手动输入内容，不修改；
    内存中将每一条URL执行sanitize_iptv_url标准化，用于运行时比对过滤。
    """
    data = set()
    if os.path.exists(PERM_BLACKLIST_PATH):
        with open(PERM_BLACKLIST_PATH, "r", encoding="utf‑8") as f:
            for line in f:
                u = clean_text(line)
                if u:
                    norm_u = sanitize_iptv_url(u)
                    if norm_u:
                        data.add(norm_u)
    return data


def save_perm_blacklist(black_set: set):
    """
    脚本自动新增黑名单时调用，写入的是标准化URL；
    不会回写/覆盖已存在的用户手动录入旧条目（只有新增才调用）。
    """
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
                norm_url = sanitize_iptv_url(url)
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


def sanitize_iptv_url(raw_url: str) -> str:
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
    url_seen = set()
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

        url = sanitize_iptv_url(raw_url)
        if not url or not name:
            count_bad += 1
            continue

        if DEBUG_PRINT:
            print(f"[DEBUG] norm_url={repr(url)} perm_hit={url in perm_black} temp_hit={url in temp_black}")

        if url in perm_black:
            count_perm_filter += 1
            continue
        if url in temp_black:
            count_temp_filter += 1
            continue
        if url in url_seen:
            count_dup += 1
            continue

        url_seen.add(url)
        output_lines.append(f"{clean_text(name)},{url}{comment}")

    out_file = os.path.join(SOURCES_DIR, "初处理.txt")
    with open(out_file, "w", encoding="utf‑8") as f:
        f.write("\n".join(output_lines))

    print(f"[STEP3‑FILTER]永久黑名单过滤:{count_perm_filter}；临时黑名单过滤:{count_temp_filter}；重复url:{count_dup}；坏行丢弃:{count_bad}；输出初处理.txt {len(output_lines)}条")

    tmp_release = os.path.join(BASE_DIR, ".step3_released.tmp.json")
    with open(tmp_release, "w", encoding="utf‑8") as f:
        json.dump(list(released_url_set), f, ensure_ascii=False)


if __name__ == "__main__":
    main()