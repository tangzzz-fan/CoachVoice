#!/usr/bin/env python3
"""生成情绪档位语料台账：phrase-bank.json + 规格表（stdout）。

数据集内联在本文件里（唯一来源）。跑一次就产出渲染脚本的输入，
同时把三条硬约束验一遍：字数预算、文本唯一、三档齐全。

用法：
    python3 scripts/build_phrase_bank.py                # 写 phrase-bank.json，表打到 stdout
    python3 scripts/build_phrase_bank.py --check        # 只校验，不写文件（改文案后跑这个）
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

# 中文播报语速 4.0–4.3 字/秒，取中值算预留。
RATE = 4.15
# 4 秒预算是硬约束：4.0 字/秒（慢端）× 4s = 16 字。
# README 里写的「20 字」是错的——20 字按 4.3 字/秒要 4.65s，超预算 16%。
MAX_CHARS = 16
MIN_CHARS = 4

# 三档各自的演法。渲染脚本把这几条直接拼进 TTS 的指令前缀，
# 盲听时也只有这三条是可以被评判的变量。
TIER_SPEC = {
    "calm": {
        "label": "组间报数",
        "prosody": "语速平，句尾落下，不评判，像在旁边记录",
        "rate": 0.95,
        "pitch": 0.0,
    },
    "encourage": {
        "label": "肯定已完成",
        "prosody": "略快，句尾微扬，重音在「做完了」「稳」这类完成态的词上",
        "rate": 1.0,
        "pitch": 0.06,
    },
    "push": {
        "label": "逼一下",
        "prosody": "短促，重音在动词，句尾干脆截断，不拖",
        "rate": 1.08,
        "pitch": 0.1,
    },
}

# 20 个子场景 × 3 档 × 2 变体 = 120 条。
# 选 2 变体而不是 3：2 变体就把「每节课同一句」的概率砍半，
# 从 120 到 180 的边际收益主要在体积和录制时间上，不在体感上。
SCENES = [
    {
        "id": "open.start",
        "event": "sessionStart",
        "intent": "开始这节课",
        "tiers": {
            "calm": ["开始训练，按计划走。", "今天按计划来，不急。"],
            "encourage": ["开始吧，今天这节不轻松。", "准备好了，我们开始。"],
            "push": ["开练，今天别留手。", "第一组，把劲拿出来。"],
        },
    },
    {
        "id": "open.warmup",
        "event": "sessionStart",
        "intent": "进入热身",
        "tiers": {
            "calm": ["先热身，把关节活动开。", "热身两组，慢慢来。"],
            "encourage": ["热身做足，后面才好发力。", "别省热身，这是给后面省力。"],
            "push": ["热身也要认真，别敷衍。", "热身到位，今天能多举一点。"],
        },
    },
    {
        "id": "open.resume",
        "event": "sessionStart",
        "intent": "中断后继续",
        "tiers": {
            "calm": ["继续，接着刚才那组。", "回来了，我们接着走。"],
            "encourage": ["断一下没关系，继续。", "接上就行，别重头来。"],
            "push": ["别歇太久，马上接上。", "回来就练，别磨。"],
        },
    },
    {
        "id": "rest.begin",
        "event": "rest",
        "intent": "开始休息",
        "tiers": {
            "calm": ["休息一分钟，呼吸放平。", "歇一会儿，等心率下来。"],
            "encourage": ["这组做完了，歇着。", "休息，你刚才那组很稳。"],
            "push": ["只歇一分钟，别坐下。", "休息短一点，别凉了。"],
        },
    },
    {
        "id": "rest.mid",
        "event": "rest",
        "intent": "休息中段",
        "tiers": {
            "calm": ["还有一半时间，慢慢呼吸。", "不着急，把气匀过来。"],
            "encourage": ["缓过来了就准备。", "状态在回来，别急。"],
            "push": ["时间不多了，站起来。", "别躺着，走两步。"],
        },
    },
    {
        "id": "rest.final",
        "event": "rest",
        "intent": "休息最后十秒",
        "tiers": {
            "calm": ["还有十秒。", "十秒，准备下一组。"],
            "encourage": ["十秒，站到位置上。", "快好了，准备。"],
            "push": ["十秒，手放杠上。", "十秒，别浪费。"],
        },
    },
    {
        "id": "rest.end",
        "event": "rest",
        "intent": "休息结束",
        "tiers": {
            "calm": ["休息结束，开始下一组。", "时间到，继续。"],
            "encourage": ["休息够了，上。", "恢复得不错，继续。"],
            "push": ["时间到，直接上。", "别等了，开始。"],
        },
    },
    {
        "id": "set.begin",
        "event": "set",
        "intent": "开始一组",
        "tiers": {
            "calm": ["这一组，按次数做。", "按计划做，不用抢。"],
            "encourage": ["这组做完就过半了。", "稳住节奏，你能做完。"],
            "push": ["这组，快一点。", "上，别犹豫。"],
        },
    },
    {
        "id": "set.half",
        "event": "set",
        "intent": "组中过半",
        "tiers": {
            "calm": ["一半了，保持呼吸。", "过半，节奏别乱。"],
            "encourage": ["一半了，后面更轻松。", "挺过半程，就快了。"],
            "push": ["一半了，加速。", "别停，还有一半。"],
        },
    },
    {
        "id": "set.final",
        "event": "set",
        "intent": "还剩最后两次",
        "tiers": {
            "calm": ["还剩两次，做完。", "最后两次，控制住。"],
            "encourage": ["就差两次，顶住。", "两次，你可以的。"],
            "push": ["两次，别放。", "最后两下，用力。"],
        },
    },
    {
        "id": "last.begin",
        "event": "set",
        "intent": "进入最后一组",
        "tiers": {
            "calm": ["最后一组，按计划做。", "这是最后一组了。"],
            "encourage": ["最后一组，收好它。", "撑完这组就结束了。"],
            "push": ["最后一组，全部拿出来。", "最后一组，别留力。"],
        },
    },
    {
        "id": "last.mid",
        "event": "set",
        "intent": "最后一组中段",
        "tiers": {
            "calm": ["最后一组过半，稳住。", "还剩一半，别急。"],
            "encourage": ["就剩这几下了。", "快了，别在这掉。"],
            "push": ["别松，就剩几下。", "顶住，不许放。"],
        },
    },
    {
        "id": "done.set",
        "event": "milestone",
        "intent": "这组完成",
        "tiers": {
            "calm": ["这组完成。", "完成一组，记一下。"],
            "encourage": ["做完了，很稳。", "这组漂亮，继续。"],
            "push": ["完成，马上下一组。", "做完就走，别停。"],
        },
    },
    {
        "id": "done.target",
        "event": "milestone",
        "intent": "当日目标达标",
        "tiers": {
            "calm": ["今天的目标完成了。", "按计划达标。"],
            "encourage": ["达标了，今天没白练。", "目标拿到，状态不错。"],
            "push": ["达标，还能再加。", "这点量不够，继续。"],
        },
    },
    {
        "id": "done.record",
        "event": "milestone",
        "intent": "破纪录",
        "tiers": {
            "calm": ["这是你目前最好的一次。", "新记录，记下来了。"],
            "encourage": ["破了！今天没白来。", "比上次重，进步了。"],
            "push": ["记录破了，再来一次。", "还能再破，接着上。"],
        },
    },
    {
        "id": "done.streak",
        "event": "milestone",
        "intent": "连续达标",
        "tiers": {
            "calm": ["连续三节都达标。", "这几节都稳。"],
            "encourage": ["连着几节都做到，很难得。", "稳定比爆发更值钱。"],
            "push": ["稳了，那就加量。", "别停在舒适区。"],
        },
    },
    {
        "id": "switch.next",
        "event": "transition",
        "intent": "换下一个动作",
        "tiers": {
            "calm": ["这个动作结束，换下一个。", "换动作，先调器械。"],
            "encourage": ["这个练完了，下一个。", "换项，状态带着走。"],
            "push": ["别磨，换下一个。", "换动作，快点。"],
        },
    },
    {
        "id": "switch.back",
        "event": "transition",
        "intent": "回到主项",
        "tiers": {
            "calm": ["回到主项，重量照旧。", "主项第二轮，稳住。"],
            "encourage": ["主项最后一遍，做好。", "回到主项，还有力气。"],
            "push": ["主项最后一轮，拼。", "主项收尾，别省。"],
        },
    },
    {
        "id": "close.plan",
        "event": "sessionEnd",
        "intent": "按计划收尾",
        "tiers": {
            "calm": ["今天的计划完成了。", "按计划结束，可以走了。"],
            "encourage": ["全部做完，今天很完整。", "一节没落，做得不错。"],
            "push": ["计划完成，还能加一组。", "收尾了，别拖。"],
        },
    },
    {
        "id": "close.cut",
        "event": "sessionEnd",
        "intent": "提前收尾",
        "tiers": {
            "calm": ["今天就到这里。", "提前结束，也算练了。"],
            "encourage": ["练到这就够了，休息。", "今天状态一般，收着点。"],
            "push": ["收工，下次补上。", "走，明天再来。"],
        },
    },
]

PUNCT = set("，。！？、；：「」『』（）…—·,.!?;:")


def spoken_len(text: str) -> int:
    """按发音数计字数：标点不读，数字一律用汉字（下面会校验）。"""
    return sum(1 for ch in text if ch not in PUNCT and not ch.isspace())


def build() -> tuple[list[dict], list[str]]:
    entries: list[dict] = []
    errors: list[str] = []
    seen: dict[str, str] = {}

    for scene in SCENES:
        for tier in TIER_SPEC:
            variants = scene["tiers"].get(tier, [])
            if len(variants) != 2:
                errors.append(f"{scene['id']}/{tier}: 变体数 {len(variants)}，应为 2")
            for i, text in enumerate(variants, start=1):
                n = spoken_len(text)
                where = f"{scene['id']}/{tier}/v{i}"
                if n > MAX_CHARS:
                    errors.append(f"{where}: {n} 字超预算（>{MAX_CHARS}）：{text}")
                if n < MIN_CHARS:
                    errors.append(f"{where}: {n} 字过短（<{MIN_CHARS}）：{text}")
                if any(ch.isdigit() for ch in text):
                    errors.append(f"{where}: 含阿拉伯数字，TTS 读音不可控：{text}")
                if any(unicodedata.east_asian_width(ch) == "Na" and ch.isalpha() for ch in text):
                    errors.append(f"{where}: 含拉丁字母：{text}")
                if text in seen:
                    errors.append(f"{where}: 与 {seen[text]} 文本重复：{text}")
                seen[text] = where
                entries.append(
                    {
                        "id": f"{scene['id']}.{tier}.v{i}",
                        "scene": scene["id"],
                        "event": scene["event"],
                        "intent": scene["intent"],
                        "tier": tier,
                        "variant": i,
                        "text": text,
                        "chars": n,
                        "est_seconds": round(n / RATE, 2),
                    }
                )
    return entries, errors


def markdown_table() -> str:
    lines = ["| 场景 | 说什么 | calm | encourage | push |", "|---|---|---|---|---|"]
    for scene in SCENES:
        cells = ["<br>".join(scene["tiers"][t]) for t in TIER_SPEC]
        lines.append(f"| `{scene['id']}` | {scene['intent']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = ap.parse_args()

    entries, errors = build()
    total_seconds = sum(e["est_seconds"] for e in entries)
    aac_bytes = total_seconds * 32000 / 8

    if errors:
        print("校验失败：", file=sys.stderr)
        for e in errors:
            print("  -", e, file=sys.stderr)
        return 1

    summary = (
        f"条数 {len(entries)} ｜ 场景 {len(SCENES)} ｜ "
        f"总时长 {total_seconds:.0f}s ｜ 预估体积 {aac_bytes/1024/1024:.2f}MB (AAC 32kbps 单声道)"
    )
    print(f"# {summary}", file=sys.stderr)

    if not args.check:
        out = Path(__file__).resolve().parent.parent / "phrase-bank.json"
        payload = {
            "version": 1,
            "generated_by": "scripts/build_phrase_bank.py",
            "rate_chars_per_sec": RATE,
            "max_chars": MAX_CHARS,
            "tier_spec": TIER_SPEC,
            "summary": {
                "clips": len(entries),
                "scenes": len(SCENES),
                "total_seconds": round(total_seconds, 1),
                "est_bytes_aac32": int(aac_bytes),
            },
            "entries": entries,
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"# 已写入 {out}", file=sys.stderr)

    print(markdown_table())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
