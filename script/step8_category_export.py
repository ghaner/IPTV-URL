# -*- coding: utf-8 -*-
"""Step8：读取step7分类运算结果，输出category目录 *.txt / *.m3u；处理EPG标签
修改点：
1. 仅 CCTV/卫视/地方台 分组输出 tvg‑id、tvg‑logo、#EPGURL
2. 其他分组：完全不输出 tvg‑id 属性，标签移除该字段
3. 新增EPG‑DEBUG调试日志，对齐iptv_process.py输出格式
参考 iptv_process.py generate_categories 成熟逻辑
"""
import os
import json
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
CATEGORY_DIR = os.path.join(BASE_DIR, "category")
os.makedirs(CATEGORY_DIR, exist_ok=True)

# 白名单：仅这些分类允许输出 tvg-id、tvg‑logo、#EPGURL
EPG_ALLOW_CATS = {"CCTV", "卫视", "地方台"}

ZERO_WIDTH_PAT = re.compile(r'[\u200b\u200c\u200d\u2060\ufeff]')
PAREN_CONTENT_PAT = re.compile(r'[(\[].*?[)\]]')
RESOLUTION_TAG_PAT = re.compile(r'(1080p|720p|4K|HD|超清|高清)', re.IGNORECASE)


def clean_text(s):
    return s.strip() if s else ""


def load_json(path):
    if not os.path.exists(path):
        return dict()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dict()


def clean_m3u_display_name(raw_name: str) -> str:
    """m3u输出界面展示名称清洗，对齐iptv_process.py"""
    n = clean_text(raw_name)
    # 删除 $ 开头线路标记
    n = re.sub(r"\$.*", "", n)
    # 删除括号和内部
    n = re.sub(r"\(.*?\)", "", n)
    n = re.sub(r"\[.*?\]", "", n)
    # 删除分辨率高清标记
    n = re.sub(r"(高清|超清|1080p|720p|4K|HD)", "", n, flags=re.IGNORECASE)
    # 零宽字符、多余空格
    n = ZERO_WIDTH_PAT.sub("", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def clean_channel_name(raw_name: str) -> str:
    """【EPG匹配专用清洗】对齐iptv_process.py，仅用于查询tvg_id_map"""
    name = clean_text(raw_name)
    # 移除线路后缀 $LR•IPV4•29『线路xx』线路标记
    name = re.sub(r"\$.*", "", name)
    # 移除圆括号、方括号内容
    name = re.sub(r"\(.*?\)", "", name)
    name = re.sub(r"\[.*?\]", "", name)
    # 将各种长破折号、特殊横杠统一替换为标准减号
    name = re.sub(r"[‑–—―−]", "-", name)
    # 剔除高清、超清、分辨率标记后缀
    name = re.sub(r"(高清|超清|1080p|720p|4K|HD)", "", name, flags=re.IGNORECASE)
    # 兼容 CCTV1 / CCTV01 → CCTV‑1
    name = re.sub(r"CCTV0?(\d+)", r"CCTV-\1", name)
    # 删除全部空白字符
    name = re.sub(r"\s+", "", name)
    name = name.strip()
    return name


def main():
    print("[STEP8‑PROGRESS] ======步骤8 分类结果输出txt/m3u开始======")
    step7_tmp = os.path.join(BASE_DIR, ".step7_cat_result.tmp.json")
    if not os.path.exists(step7_tmp):
        print("[ERROR‑STEP8]找不到step7分类运算临时文件，退出")
        return

    with open(step7_tmp, "r", encoding="utf-8") as f:
        category_result = json.load(f)

    # 清空旧分类目录文件
    for fn in os.listdir(CATEGORY_DIR):
        os.remove(os.path.join(CATEGORY_DIR, fn))

    epg_map = load_json(os.path.join(CONFIG_DIR, "tvg_id_map.json"))
    epg_cfg = load_json(os.path.join(CONFIG_DIR, "epg.json"))
    epg_url = epg_cfg.get("epg_url", "")
    tvg_logo_base = epg_cfg.get("tvg_logo_base", "").rstrip("/")

    # 新增DEBUG头部日志，对齐iptv_process.py打印格式
    print(f"[DEBUG] 加载 tvg_id_map.json，读取字典，keys数量:{len(epg_map)}")
    print(f"[DEBUG] generate_categories tvg_id_map加载key总数:{len(epg_map)}")
    print(f"[DEBUG] 加载 epg.json，读取字典，keys数量:{len(epg_cfg)}")

    gen_count = 0
    for cat_name, item_list in category_result.items():
        if not isinstance(item_list, list) or len(item_list) == 0:
            continue

        txt_path = os.path.join(CATEGORY_DIR, f"{cat_name}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(item_list))

        m3u_path = os.path.join(CATEGORY_DIR, f"{cat_name}.m3u")
        with open(m3u_path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            # 只有白名单内分类才写#EPGURL
            if cat_name in EPG_ALLOW_CATS and epg_url:
                f.write(f'#EPGURL={epg_url}\n')

            for line in item_list:
                n, u = line.split(",", 1)
                lookup_n = clean_channel_name(n)
                disp_n = clean_m3u_display_name(n)
                in_map_flag = lookup_n in epg_map
                # 新增单频道EPG调试日志，和截图日志格式完全一致
                print(f"[EPG‑DEBUG] 原始='{n}' | lookup='{lookup_n}' | in_map={in_map_flag}")

                extinf_parts = ["-1"]
                if cat_name in EPG_ALLOW_CATS:
                    tid = epg_map.get(lookup_n, "")
                    extinf_parts.append(f'tvg-id="{tid}"')
                    extinf_parts.append(f'tvg-name="{disp_n}"')
                    # 具备条件才追加logo
                    if tid and tvg_logo_base:
                        logo = f"{tvg_logo_base}/{tid}.png"
                        extinf_parts.append(f'tvg-logo="{logo}"')
                else:
                    # 非白名单分组：不加入 tvg‑id / tvg‑logo，仅保留 tvg‑name
                    extinf_parts.append(f'tvg-name="{disp_n}"')

                extinf_line = f'#EXTINF:{",".join(extinf_parts)},{disp_n}'
                f.write(f"{extinf_line}\n{u}\n")
        gen_count += 1

    print(f"[STEP8‑END]分类文件输出完成；共生成 {gen_count} 组txt+m3u文件到category目录")


if __name__ == "__main__":
    main()