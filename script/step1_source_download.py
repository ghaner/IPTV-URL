# -*- coding: utf‑8 -*-
"""Step1：从config/DOWNLOAD_SOURCE_URLS.json下载各个直播源文件，解析输出sources/下载源.txt
取自成熟iptv_process.py下载模块，修复解析0条源问题
"""
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
    """清理空白字符"""
    return s.strip() if s else ""

def load_json(path):
    """
    【来自iptv_process.py成熟函数】
    修复BUG：区分顶层list/dict；DOWNLOAD_SOURCE_URLS.json为list，映射配置tvg_id_map.json为dict
    """
    if not os.path.exists(path):
        print(f"[ERROR] JSON文件不存在: {path}")
        return [] if "DOWNLOAD_SOURCE_URLS" in path else dict()
    try:
        with open(path, "r", encoding="utf‑8") as f:
            data = json.load(f)
        if isinstance(data, list):
            print(f"[DEBUG] 加载 {os.path.basename(path)}，读取列表长度：{len(data)}")
            return data
        elif isinstance(data, dict):
            print(f"[DEBUG] 加载 {os.path.basename(path)}，读取字典，keys数量:{len(data.keys())}")
            return data
        else:
            print(f"[WARN] {os.path.basename(path)} 不是字典/列表")
            return [] if "DOWNLOAD_SOURCE_URLS" in path else dict()
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON解析失败 {path} : {str(e)}")
        return [] if "DOWNLOAD_SOURCE_URLS" in path else dict()
    except Exception as e:
        print(f"[ERROR] 文件读取异常 {path}: {str(e)}")
        return [] if "DOWNLOAD_SOURCE_URLS" in path else dict()

def parse_m3u(content, source_url):
    """
    【来自iptv_process.py成熟M3U解析】
    缺陷修复：#EXTINF与http之间允许空行，pending_name暂存频道名，不会因为中间空行丢失频道
    """
    sources = []
    name_pattern = re.compile(r'tvg‑name="([^"]+)"')
    lines = content.splitlines()
    current_name = ""
    for line in lines:
        line = clean_text(line)
        if line.startswith("#EXTINF"):
            match = name_pattern.search(line)
            if match:
                current_name = match.group(1)
            else:
                current_name = line.split(",")[-1] if "," in line else "未知频道"
        elif line.startswith("http") and current_name:
            sources.append(f"{clean_text(current_name)},{line} #{source_url}")
            current_name = ""
    return sources

def parse_txt(content, source_url):
    """【来自iptv_process.py】解析TVBox txt格式 name,url"""
    sources = []
    lines = content.splitlines()
    for line in lines:
        line = clean_text(line)
        if not line or line.startswith("#"):
            continue
        if "," in line:
            name, url = line.split(",", 1)
            if url.startswith("http"):
                sources.append(f"{clean_text(name)},{clean_text(url)} #{source_url}")
        elif line.startswith("http"):
            sources.append(f"未知频道,{line} #{source_url}")
    return sources

async def download_sources():
    """【来自iptv_process.py成熟下载主逻辑】"""
    url_file = os.path.join(CONFIG_DIR, "DOWNLOAD_SOURCE_URLS.json")
    source_urls = load_json(url_file)
    if not isinstance(source_urls, list) or len(source_urls) == 0:
        print("[FATAL‑STEP1] DOWNLOAD_SOURCE_URLS.json 下载地址为空，终止下载！")
        return {}
    all_sources = []
    source_map = defaultdict(list)
    print(f"[STEP1‑DEBUG] 待下载源数量：{len(source_urls)}")
    # -------- 在你的 async for source_url in source_list: 循环内部，原有get位置完整替换为下面整块 --------
async with session.get(
    source_url,
    headers={
        # 手敲下面UA，尽量不要复制聊天框文本
        "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    },
    timeout=aiohttp.ClientTimeout(total=12)
) as resp:
    if resp.status not in SUCCESS_CODES:
        # 新增：捕获服务器返回的报错正文
        err_body = await resp.text(errors="ignore")
        print(f"[WARN‑STEP1] {source_url} status={resp.status}, reply_body={err_body[:400]}")
        continue

    text_content = await resp.text(errors="ignore")
    # === 下面保留你原来已有的业务代码，不要改动 ===
    result_list = []
    if source_url.endswith(".m3u") or source_url.endswith(".m3u8"):
        result_list = parse_m3u(text_content)
    else:
        result_list = parse_txt(text_content)

    print(f"[STEP1‑DEBUG] {source_url} 解析得到 {len(result_list)} 条源")
    all_sources.extend(result_list)
# ---------------------------------------------------------------------------------------
    async with aiohttp.ClientSession() as session:
        for idx, source_url in enumerate(source_urls):
            try:
                print(f"[STEP1‑DEBUG] ({idx+1}/{len(source_urls)}) 下载: {source_url}")
                async with session.get(
                    source_url,
                    headers={"User‑Agent": VLC_UA},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status not in SUCCESS_CODES:
                        print(f"[WARN‑STEP1] 状态码异常 {source_url} status={resp.status}")
                        continue
                    # 读取bytes字节，规避github raw缺少charset导致乱码空内容
                    raw_bytes = await resp.read()
                    try:
                        content = raw_bytes.decode("utf‑8")
                    except UnicodeDecodeError:
                        content = raw_bytes.decode("latin‑1")

                    if source_url.endswith((".m3u", ".m3u8")):
                        items = parse_m3u(content, source_url)
                    else:
                        items = parse_txt(content, source_url)
                    all_sources.extend(items)
                    source_map[source_url] = items
                    print(f"[STEP1‑DEBUG] {source_url} 解析得到 {len(items)} 条源")
            except Exception as e:
                print(f"[ERROR‑STEP1] 下载失败 {source_url}: {str(e)}")
    output = os.path.join(SOURCES_DIR, "下载源.txt")
    with open(output, "w", encoding="utf‑8") as f:
        f.write("\n".join(all_sources))
    print(f"[STEP1‑END] 下载完成，下载源.txt总条数：{len(all_sources)}")
    return source_map

async def main():
    print("[STEP1‑PROGRESS] ======步骤1 下载直播源文件开始======")
    source_map = await download_sources()

    # 输出跨步骤中间临时文件 .step1_sourcemap.tmp.json
    import tempfile, shutil
    tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf‑8", delete=False, suffix=".json")
    json.dump(source_map, tmp, ensure_ascii=False)
    tmp.close()
    env_out = os.path.join(BASE_DIR, ".step1_sourcemap.tmp.json")
    shutil.move(tmp.name, env_out)

if __name__ == "__main__":
    asyncio.run(main())