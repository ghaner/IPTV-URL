# -*- coding: utf‑8 -*-
"""Step4：读取初处理.txt执行测速【增强修改版】
修改内容：
1.降低并发；增大HTTP超时；
2.输出底层真实异常，不再笼统http_client_error；
3.ffprobe失败原因输出到err字段；
4.每条任务携带自身错误，日志打印本条url对应的错误，消除乱序日志误导
"""
import asyncio
import aiohttp
import time
import json
import os
from typing import Tuple, Optional
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_DIR = os.path.join(BASE_DIR, "sources")
VLC_UA = "VLC/3.0.20 LibVLC/3.0.20"

# ========== 参数调优：降低并发，增大超时 ==========
CONCURRENCY_HTTP = 8
CONCURRENCY_FFPROBE = 4
TIMEOUT = 6  # HTTP请求总超时提升到6秒
SUCCESS_CODES = {200, 201, 202, 206}
MAX_SPEED_TEST_RUN_TIME = 5 * 3600 + 30 * 60
HTTP_READ_BYTES = 2048
SKIP_AUDIO_ONLY_STREAM = False


def clean_text(s):
    return s.strip() if s else ""


def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc or "unknown"
    except Exception:
        return "unknown"


async def ffprobe_check(url: str, sem: asyncio.Semaphore) -> Tuple[bool, str, str, str, str, str]:
    """
    返回: (ok, width, height, codec, bitrate, fail_reason)
    fail_reason: ffprobe失败原因，空字符串代表正常
    """
    try:
        async with sem:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-timeout", "3000000", "-stimeout", "3000000",
                "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,codec_name,bit_rate",
                "-of", "default=noprint_wrappers=1:nokey=1",
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.2)
                data = stdout.decode().splitlines()
                w = data[0] if len(data) > 0 else ""
                h = data[1] if len(data) > 1 else ""
                codec = data[2] if len(data) > 2 else ""
                br = data[3] if len(data) > 3 else "0"
                bitrate = str(int(br) // 1000) if br.isdigit() else "0"
                has_video = bool(w and h and w != "N/A" and h != "N/A")

                if SKIP_AUDIO_ONLY_STREAM and not has_video:
                    return False, "", "", "", "", "ffprobe:skip_audio_only_stream"

                if not has_video:
                    return False, w, h, codec, bitrate, "ffprobe:no_video_stream"

                return True, w, h, codec, bitrate, ""

            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return False, "", "", "", "", "ffprobe:subprocess_timeout"
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
    except Exception as e:
        return False, "", "", "", "", f"ffprobe:exception:{str(e)}"


async def test_single(session: aiohttp.ClientSession, http_sem: asyncio.Semaphore, domain_sem_map: dict,
                      ff_sem: asyncio.Semaphore, line: str):
    """
    返回 (res, orig_line, err)
    err:本条任务真实错误信息，空字符串=无错误
    """
    try:
        line = clean_text(line)
        if not line or "," not in line:
            return None, line, "bad_line_format:missing_comma"

        name, url_part = line.split(",", 1)
        url = url_part.split("#")[0].strip()
        source_src = url_part.split("#")[1] if "#" in url_part else ""
        dom = get_domain(url)

        if dom not in domain_sem_map:
            domain_sem_map[dom] = asyncio.Semaphore(3)

        async with http_sem, domain_sem_map[dom]:
            st = time.time()
            http_ok = False
            try:
                async with session.get(url, headers={"User‑Agent": VLC_UA},
                                       timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as resp:
                    await resp.content.read(HTTP_READ_BYTES)
                    http_ok = resp.status in SUCCESS_CODES
                    if not http_ok:
                        return None, line, f"http:status_code_{resp.status}"

            except aiohttp.ClientError as ce:
                # 输出底层真实异常，不再笼统http_client_error
                return None, line, f"aiohttp_client_error:{type(ce).__name__}|{str(ce)}"
            except asyncio.TimeoutError:
                return None, line, "http_timeout"
            except Exception as e:
                return None, line, f"http_unknown_exception:{type(e).__name__}|{str(e)}"

            delay = round((time.time() - st) * 1000)
            ff_ok, w, h, codec, br, ff_err = await ffprobe_check(url, ff_sem)

            valid = http_ok and ff_ok
            # 如果ffprobe有失败原因，覆盖到err
            err = ff_err
            res = {
                "name": name,
                "url": url,
                "delay": delay,
                "width": w,
                "height": h,
                "codec": codec,
                "bitrate": br,
                "valid": valid,
                "source": source_src,
                "err": err
            }
            return res, line, err

    except asyncio.CancelledError:
        raise
    except Exception as e:
        return None, line, f"task_outer_exception:{type(e).__name__}|{str(e)}"


async def main():
    print("[STEP4‑PROGRESS] ======步骤4直播源测速开始======")
    input_path = os.path.join(SOURCES_DIR, "初处理.txt")
    if not os.path.exists(input_path):
        print("[WARN‑STEP4]初处理.txt不存在，退出测速")
        return

    with open(input_path, "r", encoding="utf‑8") as f:
        lines = [l for l in f if clean_text(l)]
    print(f"[STEP4‑DEBUG]待测速 {len(lines)} 条")

    speed_start = time.time()
    http_sem = asyncio.Semaphore(CONCURRENCY_HTTP)
    ff_sem = asyncio.Semaphore(CONCURRENCY_FFPROBE)
    domain_sem = dict()
    connector = aiohttp.TCPConnector(limit=CONCURRENCY_HTTP, ttl_dns_cache=300, force_close=False)

    valid_tmp = os.path.join(SOURCES_DIR, ".valid.tmp")
    fail_tmp = os.path.join(SOURCES_DIR, ".fail.tmp")
    results = []

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [test_single(session, http_sem, domain_sem, ff_sem, ln) for ln in lines]
        completed = 0
        fv = open(valid_tmp, "w", encoding="utf‑8")
        ff = open(fail_tmp, "w", encoding="utf‑8")
        try:
            for task in asyncio.as_completed(tasks):
                if time.time() - speed_start > MAX_SPEED_TEST_RUN_TIME:
                    print("[STEP4‑WARN]测速达到最大时长，强制终止测速任务")
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    break

                res, orig_line, err = await task
                completed += 1

                if res is not None:
                    results.append(res)
                    if res["valid"]:
                        fv.write(orig_line + "\n")
                    else:
                        ff.write(orig_line + "\n")

                # 重点：打印**本条任务自身的err**，不是全局缓存错误
                if completed % 50 == 0:
                    v_cnt = sum(1 for r in results if r["valid"])
                    print(f"[STEP4‑PROGRESS]已测速 {completed}/{len(lines)}，有效{v_cnt}，失败{len(results)-v_cnt} sample_err={err}")
                # 可选：每一条都打印（信息量很大，建议默认注释，调试打开）
                # print(f"[STEP4‑DETAIL] line={orig_line[:60]} err={err}")

        finally:
            fv.close()
            ff.close()

    out_res_tmp = os.path.join(BASE_DIR, ".step4_results.tmp.json")
    with open(out_res_tmp, "w", encoding="utf‑8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"[STEP4‑END]测速结束；本轮结果集{len(results)}")


if __name__ == "__main__":
    asyncio.run(main())