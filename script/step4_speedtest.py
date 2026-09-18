# -*- coding: utf-8 -*-
"""Step4：读取初处理.txt执行测速【修复计数丢失+失败原因统计模块】
已确认改动清单：
1. HTTP头 User‑Agent 使用英文横杠
2. ffprobe 使用正确参数 -http_user_agent
3. 删除废弃 -stimeout，改用 -rw_timeout
4. 提速调参：并发、单域名限流、IO超时
5. 5小时30分钟测速善终提前结束，部分结果落盘供下游继续处理
6. 修复CancelledError导致任务丢失，保证待测总数 ≈ 有效+失败
7.【新增独立模块】测速失败原因统计模块，带配置开关，关闭不影响主逻辑
无额外私自增加逻辑，移除 family=4
"""
import asyncio
import aiohttp
import time
import json
import os
from collections import Counter
from typing import Tuple
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_DIR = os.path.join(BASE_DIR, "sources")
LOG_DIR = os.path.join(BASE_DIR, "log")
os.makedirs(LOG_DIR, exist_ok=True)

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

# ========== 【提速调参区】 ==========
CONCURRENCY_HTTP = 8
CONCURRENCY_FFPROBE = 6
DOMAIN_MAX_CONCURRENCY = 6   # 单个域名最大并发请求
TIMEOUT = 10                 # http总超时 秒
FF_RW_TIMEOUT = 2000000      # ffprobe读写IO超时(微秒) 2秒
SUCCESS_CODES = {200, 201, 202, 206}
MAX_SPEED_TEST_RUN_TIME = 5 * 3600 + 30 * 60   # 5小时30分，测速最大时长，超时善终退出
SKIP_AUDIO_ONLY_STREAM = False

# ==========【独立模块开关：测速失败原因统计】 ==========
ENABLE_FAIL_REASON_STAT = True   # True开启；False关闭该模块，完全不影响其他业务

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


# 【新增】外层包装，兜底捕获取消、逃逸异常
async def wrap_task(coro, orig_line_text):
    try:
        return await coro
    except asyncio.CancelledError:
        return None, orig_line_text, "task_cancelled:grace_timeout"
    except Exception as e:
        return None, orig_line_text, f"task_uncaught_exception:{type(e).__name__}:{str(e)}"


async def main():
    print("[STEP4‑PROGRESS] ======步骤4直播源测速开始【修复计数丢失】======")
    input_path = os.path.join(SOURCES_DIR, "初处理.txt")
    if not os.path.exists(input_path):
        print("[WARN‑STEP4]初处理.txt不存在，退出测速")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        lines = [l for l in f if clean_text(l)]

    total_input = len(lines)
    print(f"[STEP4‑DEBUG]待测速 {total_input} 条")
    speed_start = time.time()
    time_need_stop = speed_start + MAX_SPEED_TEST_RUN_TIME

    http_sem = asyncio.Semaphore(CONCURRENCY_HTTP)
    ff_sem = asyncio.Semaphore(CONCURRENCY_FFPROBE)
    domain_sem = dict()

    # 已移除 family=4，不再强制限定IP协议族
    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY_HTTP,
        ttl_dns_cache=300,
        force_close=False
    )

    valid_tmp = os.path.join(SOURCES_DIR, ".valid.tmp")
    fail_tmp = os.path.join(SOURCES_DIR, ".fail.tmp")
    results = []
    grace_stop = False

    async with aiohttp.ClientSession(connector=connector) as session:
        # 使用wrap_task包装每一个任务，传入原始行
        tasks = [
            wrap_task(
                test_single(session, http_sem, domain_sem, ff_sem, ln),
                ln
            )
            for ln in lines
        ]
        completed = 0
        fv = open(valid_tmp, "w", encoding="utf-8")
        ff = open(fail_tmp, "w", encoding="utf-8")
        try:
            for task in asyncio.as_completed(tasks):
                # 判断是否到达最大测速时长
                if (not grace_stop) and (time.time() >= time_need_stop):
                    print("[STEP4‑WARN] === 测速到达最大5h30m，触发善终提前结束 ===")
                    grace_stop = True
                    # 取消尚未完成的任务；不break，继续消费as_completed剩余任务
                    for t in tasks:
                        if not t.done():
                            t.cancel()

                res, orig_line, err = await task
                completed += 1

                if res is not None:
                    results.append(res)
                    if res["valid"]:
                        fv.write(orig_line + "\n")
                    else:
                        ff.write(orig_line + "\n")
                else:
                    # res为None（格式错误 / 被取消 / 顶层异常）全部归入失败
                    results.append({
                        "name": orig_line.split(",")[0] if "," in orig_line else "",
                        "url": orig_line.split(",")[1].split("#")[0].strip() if "," in orig_line else "",
                        "delay": 0,
                        "width": "",
                        "height": "",
                        "codec": "",
                        "bitrate": "",
                        "valid": False,
                        "source": orig_line.split("#")[1].strip() if ("#" in orig_line and "," in orig_line) else "",
                        "err": err
                    })
                    ff.write(orig_line + "\n")

                if completed % 50 == 0:
                    v_cnt = sum(1 for r in results if r["valid"])
                    f_cnt = len(results) - v_cnt
                    print(f"[STEP4‑PROGRESS]已处理 {completed}/{total_input}，已完成有效{v_cnt}，已完成失败{f_cnt} sample_err={err}")

        finally:
            fv.close()
            ff.close()
            # 无论正常跑完还是超时善终，都写入已完成结果json，下游步骤可以读取
            out_res_tmp = os.path.join(BASE_DIR, ".step4_results.tmp.json")
            with open(out_res_tmp, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

            valid_final = sum(1 for r in results if r["valid"])
            fail_final = len(results) - valid_final
            diff = total_input - len(results)
            print(f"[STEP4‑STAT]统计：输入总数={total_input}；结果集={len(results)}；有效={valid_final}；失败={fail_final}；差值={diff}")
            if diff > 0:
                print(f"[STEP4‑WARN] ⚠️存在未捕获任务差值 {diff}")

            # === MODULE_FAIL_REASON_STAT BEGIN ===
            # 功能：测速失败原因统计模块
            # 开关：ENABLE_FAIL_REASON_STAT
            # 逻辑：遍历results，过滤valid=False条目，提取err字段，计数；控制台打印TopN；输出log/fail_reason_stat.json
            # 关闭条件：ENABLE_FAIL_REASON_STAT=False，整块跳过，不影响主流程、不读写文件
            if ENABLE_FAIL_REASON_STAT:
                err_counter = Counter()
                for item in results:
                    if not item.get("valid", False):
                        err_msg = item.get("err", "unknown").strip()
                        err_counter[err_msg] += 1
                # 打印top15失败原因
                print("\n[STEP4‑FAIL‑STAT] ---------- 失败原因统计 TOP15 ----------")
                for reason, cnt in err_counter.most_common(15):
                    print(f"cnt={cnt:6d} | {reason}")
                print("[STEP4‑FAIL‑STAT] --------------------------------------------\n")
                # 输出统计json文件
                stat_out_path = os.path.join(LOG_DIR, "fail_reason_stat.json")
                with open(stat_out_path, "w", encoding="utf‑8") as fp:
                    json.dump(dict(err_counter), fp, ensure_ascii=False, indent=2)
                print(f"[STEP4‑FAIL‑STAT]失败原因统计文件输出：log/fail_reason_stat.json")
            # === MODULE_FAIL_REASON_STAT END ===

            if grace_stop:
                print(f"[STEP4‑END]【超时善终提前结束】；后续步骤可读取临时文件继续处理")
            else:
                print(f"[STEP4‑END]测速正常全部结束；本轮结果集{len(results)}")


if __name__ == "__main__":
    asyncio.run(main())