# -*- coding: utf-8 -*-
"""Step4：读取初处理.txt执行测速【修复bug+GitHub Action提速调参版】
修复清单：
1. HTTP头User‑Agent中文全角横杠 → 英文User‑Agent
2. ffprobe 使用正确 -http_user_agent
3. 删除废弃 -stimeout，使用 -rw_timeout
调参：提高并发、放宽单域名限流、缩短IO超时，平衡速度与防盗链风险
新增强化：测速善终提前结束
  整个action运行5小时30分钟时，如果测速任务还未完成
  终止测速任务；将已完成测速的直播源分有效源和失败源进行输出保存，供给后续步骤处理
"""
import asyncio
import aiohttp
import time
import json
import os
from typing import Tuple
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_DIR = os.path.join(BASE_DIR, "sources")

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

# ========== 【提速调参区】 ==========
CONCURRENCY_HTTP = 8
CONCURRENCY_FFPROBE = 6
DOMAIN_MAX_CONCURRENCY = 6   # 单个域名最大并发请求
TIMEOUT = 10                 # http总超时 秒
FF_RW_TIMEOUT = 2000000      # ffprobe读写IO超时(微秒) 2秒
SUCCESS_CODES = {200, 201, 202, 206}
MAX_SPEED_TEST_RUN_TIME = 5 * 3600 + 30 * 60   # 5小时30秒 测速最大时长，超时善终退出
SKIP_AUDIO_ONLY_STREAM = False


def clean_text(s):
    return s.strip() if s else ""


def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc or "unknown"
    except Exception:
        return "unknown"


async def ffprobe_check(url: str, sem: asyncio.Semaphore) -> Tuple[bool, str, str, str, str, str]:
    proc = None
    try:
        async with sem:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-http_user_agent", BROWSER_UA,
                "-rw_timeout", str(FF_RW_TIMEOUT),
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,codec_name,bit_rate",
                "-of", "default=noprint_wrappers=1:nokey=1",
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                err_text = stderr.decode("utf-8", errors="ignore")[:250]
                return False, "", "", "", "", f"ffprobe:fail:{err_text}"
            data = stdout.decode("utf-8").splitlines()
            if len(data) >= 4:
                w = data[0].strip()
                h = data[1].strip()
                codec = data[2].strip()
                br = data[3].strip()
                return True, w, h, codec, br, ""
            else:
                return False, "", "", "", "", "ffprobe:no_video_stream"
    except Exception as e:
        return False, "", "", "", "", f"ffprobe:exception:{str(e)}"
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass


async def test_single(session: aiohttp.ClientSession, http_sem: asyncio.Semaphore, domain_sem_map: dict,
                      ff_sem: asyncio.Semaphore, line: str):
    try:
        line = clean_text(line)
        if not line or "," not in line:
            return None, line, "bad_line_format:missing_comma"
        name, url_part = line.split(",", maxsplit=1)
        url = url_part.split("#")[0].strip()
        source_src = url_part.split("#")[1].strip() if "#" in url_part else ""
        dom = get_domain(url)
        if dom not in domain_sem_map:
            domain_sem_map[dom] = asyncio.Semaphore(DOMAIN_MAX_CONCURRENCY)
        dom_sem = domain_sem_map[dom]
        async with http_sem, dom_sem:
            st = time.time()
            headers = {
                "User-Agent": BROWSER_UA,
                "Referer": "https://localhost/"
            }
            try:
                async with session.get(url, headers=headers,
                                       timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as resp:
                    http_ok = resp.status in SUCCESS_CODES
                    if not http_ok:
                        return None, line, f"http:status_code_{resp.status}"
            except aiohttp.ClientError as ce:
                return None, line, f"aiohttp_client_error:{type(ce).__name__}|{str(ce)}"
            except asyncio.TimeoutError:
                return None, line, "http_timeout"
            except Exception as e:
                return None, line, f"http_unknown_exception:{type(e).__name__}|{str(e)}"
            delay_ms = round((time.time() - st) * 1000)
            ff_ok, w, h, codec, br, ff_err = await ffprobe_check(url, ff_sem)
            valid = http_ok and ff_ok
            res = {
                "name": name,
                "url": url,
                "delay": delay_ms,
                "width": w,
                "height": h,
                "codec": codec,
                "bitrate": br,
                "valid": valid,
                "source": source_src,
                "err": ff_err
            }
            return res, line, ff_err
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return None, line, f"task_outer_exception:{type(e).__name__}|{str(e)}"


async def main():
    print("[STEP4‑PROGRESS] ======步骤4直播源测速开始【提速+善终超时退出】======")
    input_path = os.path.join(SOURCES_DIR, "初处理.txt")
    if not os.path.exists(input_path):
        print("[WARN‑STEP4]初处理.txt不存在，退出测速")
        return
    with open(input_path, "r", encoding="utf-8") as f:
        lines = [l for l in f if clean_text(l)]
    print(f"[STEP4‑DEBUG]待测速 {len(lines)} 条")
    speed_start = time.time()
    time_need_stop = speed_start + MAX_SPEED_TEST_RUN_TIME

    http_sem = asyncio.Semaphore(CONCURRENCY_HTTP)
    ff_sem = asyncio.Semaphore(CONCURRENCY_FFPROBE)
    domain_sem = dict()

    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY_HTTP,
        ttl_dns_cache=300,
        force_close=False,
        family=4   # 强制IPv4，屏蔽IPv6报错刷屏
    )
    valid_tmp = os.path.join(SOURCES_DIR, ".valid.tmp")
    fail_tmp = os.path.join(SOURCES_DIR, ".fail.tmp")
    results = []
    is_timeout_grace_exit = False

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [test_single(session, http_sem, domain_sem, ff_sem, ln) for ln in lines]
        completed = 0
        fv = open(valid_tmp, "w", encoding="utf-8")
        ff = open(fail_tmp, "w", encoding="utf-8")
        try:
            for task in asyncio.as_completed(tasks):
                # 判断是否到达最大测速时长，触发善终提前结束
                if time.time() >= time_need_stop:
                    print("[STEP4‑WARN] === 测速到达最大5h30m，触发善终提前结束 ===")
                    is_timeout_grace_exit = True
                    # 取消所有尚未完成的任务
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

                if completed % 50 == 0:
                    v_cnt = sum(1 for r in results if r["valid"])
                    print(f"[STEP4‑PROGRESS]已发起 {completed}/{len(lines)}，已完成有效{v_cnt}，已完成失败{len(results)-v_cnt} sample_err={err}")

        finally:
            fv.close()
            ff.close()
            # 无论正常跑完还是超时善终，都写入已完成结果json，下游步骤可以读取
            out_res_tmp = os.path.join(BASE_DIR, ".step4_results.tmp.json")
            with open(out_res_tmp, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

            if is_timeout_grace_exit:
                print(f"[STEP4‑END]【超时善终提前结束】已保存已完成{len(results)}条；未完成任务已丢弃；后续步骤可读取临时文件继续处理")
            else:
                print(f"[STEP4‑END]测速正常全部结束；本轮结果集{len(results)}")


if __name__ == "__main__":
    asyncio.run(main())