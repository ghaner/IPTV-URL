import json
import asyncio
from collections import defaultdict
import aiohttp

VLC_UA = "VLC/3.0.20 LibVLC/3.0.20"
SUCCESS_CODES = {200}


def parse_m3u(content: str):
    """m3u/m3u8解析"""
    result = []
    lines = content.splitlines()
    name = ""
    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF:"):
            if "," in line:
                name = line.split(",", 1)[1]
        elif line and not line.startswith("#"):
            result.append({"name": name, "url": line})
            name = ""
    return result


def parse_txt(content: str):
    """txt格式解析"""
    result = []
    lines = content.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "," in line:
            name, url = line.split(",", 1)
            result.append({"name": name.strip(), "url": url.strip()})
    return result


async def step1_download():
    # ==========修复这里：正确json路径==========
    with open("config/DOWNLOAD_SOURCE_URLS.json", "r", encoding="utf-8") as f:
        source_urls = json.load(f)

    if not isinstance(source_urls, list) or len(source_urls) == 0:
        print("[FATAL-STEP1] DOWNLOAD_SOURCE_URLS.json 下载地址为空，终止下载！")
        return {}

    all_sources = []
    source_map = defaultdict(list)
    print(f"[STEP1-DEBUG] 待下载源数量：{len(source_urls)}")
    print(f"DEBUG-UA-RAW: {repr(VLC_UA)}")

    async with aiohttp.ClientSession() as session:
        for idx, source_url in enumerate(source_urls):
            try:
                print(f"[STEP1-DEBUG] ({idx+1}/{len(source_urls)}) 下载: {source_url}")
                async with session.get(
                    source_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                    },
                    timeout=aiohttp.ClientTimeout(total=12)
                ) as resp:
                    if resp.status not in SUCCESS_CODES:
                        err_body = await resp.text(errors="ignore")
                        print(f"[WARN‑STEP1] {source_url} status={resp.status}, reply_body={err_body[:400]}")
                        continue

                    text_content = await resp.text(errors="ignore")
                    result_list = []
                    if source_url.endswith(".m3u") or source_url.endswith(".m3u8"):
                        result_list = parse_m3u(text_content)
                    else:
                        result_list = parse_txt(text_content)

                    print(f"[STEP1‑DEBUG] {source_url} 解析得到 {len(result_list)} 条源")
                    all_sources.extend(result_list)

            except Exception as e:
                print(f"[WARN‑STEP1] 请求异常 {source_url} , error: {str(e)}")
                continue

    # 输出文件路径，脚本在script目录，输出到script下
    out_data = {
        "total": len(all_sources),
        "list": all_sources
    }
    with open("script/step1_output.json", "w", encoding="utf-8") as fw:
        json.dump(out_data, fw, ensure_ascii=False, indent=2)

    print(f"[STEP1-INFO] step1完成，共获取 {len(all_sources)} 条直播源，写入 script/step1_output.json")
    return out_data


if __name__ == "__main__":
    asyncio.run(step1_download())