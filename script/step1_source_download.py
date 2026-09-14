# -*- coding: utf-8 -*-
"""Step1：从config/DOWNLOAD_SOURCE_URLS.json下载各个直播源文件，解析输出sources/下载源.txt"""
import asyncio
import aiohttp
import os
import json
import re
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
SOURCES_DIR = os.path.join(BASE_DIR, "sources")
CATEGORY_DIR = os.path.join(BASE_DIR, "category")
LOG_DIR = os.path.join(BASE_DIR, "log")
for d in [SOURCES_DIR, CATEGORY_DIR, LOG_DIR]:
    os.makedirs(d, exist_ok=True)

VLC_UA = "VLC/3.0.20 LibVLC/3.0.20"
SUCCESS_CODES = {200, 201, 202, 206}

def clean_text(s):
    return s.strip() if s else ""

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

def parse_m3u(content: str, source_url: str):
    sources = []
    name_pat = re.compile(r'tvg‑name="([^"]+)"')
    lines = content.splitlines()
    current_name = ""
    for line in lines:
        line = clean_text(line)
        if line.startswith("#EXTINF"):
            m = name_pat.search(line)
            if m:
                current_name = m.group(1)
            else:
                current_name = line.split(",")[-1] if "," in line else "未知频道"
        elif line.startswith("http"):
            if current_name and line:
                sources.append(f"{clean_text(current_name)},{line} #{source_url}")
            current_name = ""
    return sources

def parse_txt(content: str, source_url: str):
    sources = []
    lines = content.splitlines()
    for line in lines:
        line = clean_text(line)
        if not line or line.startswith("#"):
            continue
        if "," in line:
            name, url = line.split(",",1)
            url = clean_text(url)
            if url.startswith("http"):
                sources.append(f"{clean_text(name)},{url} #{source_url}")
        elif line.startswith("http"):
            sources.append(f"未知频道,{line} #{source_url}")
    return sources

async def main():
    print("[STEP1‑PROGRESS] ======步骤1 下载直播源文件开始======")
    url_cfg = os.path.join(CONFIG_DIR, "DOWNLOAD_SOURCE_URLS.json")
    source_urls = load_json(url_cfg)
    if not isinstance(source_urls, list) or len(source_urls) == 0:
        print("[FATAL‑STEP1] DOWNLOAD_SOURCE_URLS.json地址列表为空，退出！")
        return

    source_map = defaultdict(list)
    all_items = []
    async with aiohttp.ClientSession() as session:
        for idx, src_url in enumerate(source_urls):
            try:
                print(f"[STEP1‑DEBUG] ({idx+1}/{len(source_urls)})下载 {src_url}")
                async with session.get(src_url, headers={"User‑Agent":VLC_UA}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status not in SUCCESS_CODES:
                        print(f"[WARN‑STEP1] 下载状态异常 status={resp.status} {src_url}")
                        continue
                    text = await resp.text(errors="ignore")
                    if src_url.endswith((".m3u",".m3u8")):
                        items = parse_m3u(text, src_url)
                    else:
                        items = parse_txt(text, src_url)
                    source_map[src_url] = items
                    all_items.extend(items)
                    print(f"[STEP1‑DEBUG] {src_url} 解析 {len(items)} 条")
            except Exception as e:
                print(f"[ERROR‑STEP1]下载失败 {src_url} : {str(e)}")

    out_file = os.path.join(SOURCES_DIR, "下载源.txt")
    with open(out_file, "w", encoding="utf‑8") as f:
        f.write("\n".join(all_items))
    print(f"[STEP1‑END]下载源.txt写入完成，总条数 {len(all_items)}")

    import tempfile, shutil
    tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf‑8", delete=False, suffix=".json")
    json.dump(source_map, tmp, ensure_ascii=False)
    tmp.close()
    env_out = os.path.join(BASE_DIR, ".step1_sourcemap.tmp.json")
    shutil.move(tmp.name, env_out)

if __name__ == "__main__":
    asyncio.run(main())