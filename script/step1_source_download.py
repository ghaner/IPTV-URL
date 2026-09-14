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

# 浏览器UA，防止github raw拦截
HEADERS = {
    "User‑Agent": "Mozilla/5.0 (X86_64; Linux) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept‑Language": "zh‑CN,zh;q=0.9,*;q=0.8"
}
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
    """健壮M3U解析：允许#EXTINF和http行之间穿插空行、注释行，跳过空白行"""
    sources = []
    name_pat = re.compile(r'tvg‑name="([^"]+)"')
    lines = content.splitlines()
    pending_name = None
    for raw_line in lines:
        line = clean_text(raw_line)
        if not line:
            continue
        if line.startswith("#EXTINF"):
            pending_name = None
            m = name_pat.search(line)
            if m:
                pending_name = m.group(1).strip()
            else:
                # 取逗号后面作为频道名 #EXTINF:-1 ,CCTV‑1
                parts = line.rsplit(",", 1)
                if len(parts) >=2:
                    pending_name = clean_text(parts[-1])
            if not pending_name:
                pending_name = "未知频道"
            continue
        # 遇到流地址，并且有待处理频道名
        if pending_name is not None and line.startswith("http"):
            sources.append(f"{pending_name},{line} #{source_url}")
            pending_name = None
    return sources

def parse_txt(content: str, source_url: str):
    """解析TVBox txt格式：name,url"""
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
    return sources

async def fetch_raw_text(session, url):
    """优先读取bytes，多编码尝试解码，修复github raw无charset导致乱码/空文本问题"""
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=12)) as resp:
            if resp.status not in SUCCESS_CODES:
                return None, f"status={resp.status}"
            raw_bytes = await resp.read()
            print(f"[DEBUG] {url} 下载字节数：{len(raw_bytes)}")
            # 尝试utf‑8，失败回退latin‑1
            try:
                text = raw_bytes.decode("utf‑8")
            except UnicodeDecodeError:
                text = raw_bytes.decode("latin‑1")
            return text, None
    except Exception as e:
        return None, str(e)

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
            print(f"[STEP1‑DEBUG] ({idx+1}/{len(source_urls)})下载 {src_url}")
            text, err = await fetch_raw_text(session, src_url)
            if err is not None or text is None:
                print(f"[WARN‑STEP1] 下载失败 {src_url} , err={err}")
                continue
            # 判断解析器
            lower_url = src_url.lower()
            if lower_url.endswith((".m3u",".m3u8")):
                items = parse_m3u(text, src_url)
            else:
                items = parse_txt(text, src_url)
            source_map[src_url] = items
            all_items.extend(items)
            print(f"[STEP1‑DEBUG] {src_url} → 解析得到 {len(items)} 条")

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