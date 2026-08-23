"""MPWE - AI 提示词 Agent（两阶段流水线，配置驱动）。

阶段一：共用「画面需求书扩写 Agent」→ 600-700 字中文画面需求书；
阶段二：模型专属「翻译 Agent」（来自 agent_prompts.yaml）→ 英文正/负向提示词。

系统提示词全部来自 YAML 配置，程序本体与模型无关；
硬性验收：最终 POSITIVE/NEGATIVE 必须全部为英文，任何阶段失败都只报错，
绝不把中文原文当最终提示词返回。
"""

from __future__ import annotations

import json
import re
from typing import Callable, Optional

from app.prompting import loader
from app.prompting.llm import LLMAPIError, LLMConfigError, LLMTimeoutError, chat

CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# 关键道具兜底词表：需求书点名 → 提示词里必须出现
_PROP_RULES = [
    (("透明伞", "透明"), "transparent umbrella"),
    (("伞", "umbrella"), "umbrella"),
    (("路灯", "streetlight", "lamp"), "streetlight"),
    (("栏杆", "railing", "fence"), "wet railing"),
    (("雨", "rain"), "rain"),
    (("夜", "night"), "night"),
    (("霓虹", "neon"), "neon lights"),
    (("桥", "bridge"), "bridge"),
    (("樱花", "cherry blossom"), "cherry blossoms"),
    (("月亮", "moon"), "moon"),
    (("烟花", "fireworks"), "fireworks"),
    (("雪", "snow"), "snow"),
]

_ACTION_ANCHORS = ("holding", "hand", "fingers", "standing", "sitting", "gripping", "leaning", "pose")


def _emit(on_progress: Optional[Callable], **kw) -> None:
    if on_progress:
        try:
            on_progress(kw)
        except Exception:
            pass


# ========== 阶段一：大白话 → 详细中文画面需求书 ==========


def _expand_brief(text: str, retry: Optional[str] = None, on_usage=None) -> Optional[str]:
    """生成中文画面需求书；长度越界时带原因重试一次（600-700 字目标）。"""
    agent = loader.get_expand_agent()
    system = agent["prompt"]
    if retry == "short":
        system += (
            "\n\nYour previous output was rejected: too short, or it did not contain all seven "
            "required sections, or the first/second/third priorities were not clearly stated. "
            "This time write a complete 600-700 character requirement document with all seven "
            "sections and explicit visual priorities."
        )
    elif retry == "long":
        system += (
            "\n\nYour previous output was rejected: TOO LONG. The requirement document must be "
            "strictly 600-700 Simplified Chinese characters (section headings excluded). "
            "Tighten every sentence, keep all seven sections, and do not exceed 700 characters. "
            "IMPORTANT: stay BETWEEN 600 and 700 characters; do not drop below 600."
        )
    content = chat(
        system,
        f"用户描述（User description）:\n{text}",
        temperature=0.6,
        max_tokens=4000,
        on_usage=on_usage,
    )
    n = len(content)
    if n < 200:
        # 太短：重试一次，仍短则交回调用方兜底
        return None if retry else _expand_brief(text, retry="short", on_usage=on_usage)
    if n > 850:
        # 超长：重试一次；第二次若矫枉过正（<500）则再按“太短”回正一次，否则接受
        if retry:
            return content if n >= 500 else _expand_brief(text, retry="short", on_usage=on_usage)
        return _expand_brief(text, retry="long", on_usage=on_usage)
    return content


# ========== 阶段二：需求书 → 专业英文提示词 ==========


def _extract_positive_negative(content: str) -> Optional[dict]:
    """优先解析 JSON，失败降级解析 POSITIVE:/NEGATIVE: 两行。"""
    if not content:
        return None
    jm = re.search(r"\{.*\}", content, re.DOTALL)
    if jm:
        try:
            data = json.loads(jm.group(0))
            positive = str(data.get("positive", "") or "").strip()
            if positive:
                return {
                    "positive": positive,
                    "negative": str(data.get("negative", "") or "").strip(),
                }
        except json.JSONDecodeError:
            pass
    m = re.search(
        r"POSITIVE\s*[:：]\s*(.+?)(?=\n\s*NEGATIVE\s*[:：]|$)",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    n = re.search(r"NEGATIVE\s*[:：]\s*(.+?)$", content, re.DOTALL | re.IGNORECASE)
    if m:
        return {
            "positive": m.group(1).strip(),
            "negative": n.group(1).strip() if n else "",
        }
    return None


def _trim_tags(positive: str, max_tags: int = 55, max_words: int = 90) -> str:
    """按预算裁剪：提示词顺序即优先级，从头保留，尾部（背景）可裁。"""
    tags = [t.strip() for t in (positive or "").split(",") if t.strip()]
    kept = []
    words = 0
    for t in tags:
        w = len(t.split())
        if len(kept) >= max_tags or words + w > max_words:
            break
        kept.append(t)
        words += w
    return ", ".join(kept)


def _ensure_key_props(brief: str, positive: str, natural_language: bool = False) -> str:
    """需求书里点名的关键道具，提示词里必须出现；缺失时自动插入。

    natural_language=True 时（Z-Image / Z-Anime 等自然语言模型）：
    关键道具以自然语句形式插到第一句之后，避免破坏"主体在前"的句子结构。
    """
    brief = brief or ""
    low_pos = (positive or "").lower()
    missing = []
    for keys, tag in _PROP_RULES:
        if not any(k.lower() in brief for k in keys):
            continue
        if tag not in low_pos:
            missing.append(tag)
    if not missing:
        return positive
    # 同一概念只插一次（如 transparent umbrella 与 umbrella 按名词去重）
    seen_nouns = set()
    uniq = []
    for tag in missing:
        noun = tag.split()[-1]
        if noun in seen_nouns:
            continue
        seen_nouns.add(noun)
        uniq.append(tag)
    if not uniq:
        return positive
    if natural_language:
        text = positive.rstrip()
        marker = ". "
        idx = text.find(marker)
        if idx != -1:
            insert_at = idx + len(marker)
            return text[:insert_at] + "The key props are " + ", ".join(uniq) + ". " + text[insert_at:]
        return (text + " The key props are " + ", ".join(uniq) + ".").strip()
    tags = [t.strip() for t in (positive or "").split(",") if t.strip()]
    idx = next(
        (i for i, t in enumerate(tags) if any(a in t.lower() for a in _ACTION_ANCHORS)),
        None,
    )
    if idx is None:
        idx = min(8, len(tags))
    for tag in reversed(uniq):
        tags.insert(idx, tag)
    return ", ".join(tags)


def _quality_ok(agent: dict, positive: str, negative: str) -> Optional[str]:
    """返回不合格原因；None 表示合格。"""
    positive = (positive or "").strip()
    negative = (negative or "").strip()
    if not positive:
        return "positive 为空"
    if CJK_RE.search(positive):
        return "positive 含中文"
    if CJK_RE.search(negative):
        return "negative 含中文"

    v = agent.get("validation") or loader.get_default_validation()
    tags = [t for t in positive.split(",") if t.strip()]
    words = len(positive.split())

    min_tags = int(v.get("min_tags") or 0)
    max_tags = int(v.get("max_tags") or 999)
    if len(tags) < min_tags:
        return f"标签太少（{len(tags)} 个，要求 ≥{min_tags}）"
    if len(tags) > max_tags:
        return f"标签太多（{len(tags)} 个，要求 ≤{max_tags}）"
    if words < int(v.get("min_words") or 0):
        return f"词数过少（{words} 词，要求 ≥{v.get('min_words')}）"
    if words > int(v.get("max_words") or 999):
        return f"词数过多（{words} 词，要求 ≤{v.get('max_words')}）"
    for tag in v.get("required_tags") or []:
        if tag not in positive.lower():
            return f"缺少必需质量词: {tag}"
    if v.get("negative_required", True) and not negative:
        return "SD 类模型缺少负面提示词"
    return None


def _to_prompt(
    agent: dict,
    brief: str,
    strict: bool = False,
    final: bool = False,
    on_usage=None,
) -> tuple:
    """返回 (result, reason)；成功时 reason 为空。"""
    system = agent["prompt"]
    v = agent.get("validation") or loader.get_default_validation()
    if bool(v.get("negative_required", True)):
        format_note = " Exactly two lines: POSITIVE: ... and NEGATIVE: ..."
        neg_line = " and a complete NEGATIVE line"
    else:
        format_note = " Output only the POSITIVE line (this model does not use a NEGATIVE line)."
        neg_line = ""
    if strict:
        system += (
            "\n\nYour previous output was rejected: too short, contained Chinese, "
            "or the background was too dominant. This time obey the requirement's priority order: "
            "subject first and large, key props second, background last and blurred. "
            f"Write within the configured word budget, in pure English,{neg_line}."
        )
    if final:
        system += (
            "\n\nLAST CHANCE: You failed twice. Do not fail again. Ignore the user's brevity, "
            "write the richest, pure-English prompt you can, put the subject first, "
            f"keep the background weak and blurred,{neg_line}.{format_note}"
        )
    content = chat(
        system,
        f"模型（Model）: {agent.get('name', '')}\n中文画面需求书（Scene Requirement Document）:\n{brief}",
        temperature=0.35,
        max_tokens=4000,
        on_usage=on_usage,
    )
    result = _extract_positive_negative(content)
    if result is None:
        return None, "输出格式解析失败（缺少 POSITIVE/NEGATIVE）"
    positive = result["positive"].strip()
    negative = result["negative"].strip()

    natural_language = bool(v.get("natural_language", False))
    positive = _ensure_key_props(brief, positive, natural_language=natural_language)
    v = agent.get("validation") or loader.get_default_validation()
    positive = _trim_tags(
        positive,
        max_tags=int(v.get("max_tags") or 55),
        max_words=int(v.get("max_words") or 90),
    )
    positive = _ensure_key_props(brief, positive, natural_language=natural_language)
    positive = _trim_tags(
        positive,
        max_tags=int(v.get("max_tags") or 55),
        max_words=int(v.get("max_words") or 90),
    )
    reason = _quality_ok(agent, positive, negative)
    if reason:
        return None, reason
    return {"positive": positive, "negative": negative}, ""


def translate(
    text: str,
    model: str = "",
    on_progress: Optional[Callable] = None,
    on_usage=None,
) -> dict:
    """两阶段翻译：大白话 → 详细需求书 → 模型特调英文提示词。

    返回 {"ok", "positive", "negative", "brief", "tuned", "agent_name", "error"}。
    """
    text = (text or "").strip()
    if not text:
        return {
            "ok": False,
            "positive": "",
            "negative": "",
            "brief": "",
            "tuned": False,
            "agent_name": "",
            "error": "描述不能为空。",
        }
    agent = loader.get_translate_agent(model)
    if agent is None:
        return {
            "ok": False,
            "positive": "",
            "negative": "",
            "brief": "",
            "tuned": False,
            "agent_name": "",
            "error": "该模型暂无适配的提示词 Agent：可在 agent_prompts.yaml 的 models 下为该模型新增 translate_agent 配置（一个模型对应一个 Agent）。",
        }
    tuned = True
    agent_name = agent.get("name", "")
    try:
        _emit(on_progress, stage="brief", value=8, max=100, note="正在理解描述并细化画面要求…")
        brief = _expand_brief(text, on_usage=on_usage)
        if brief is None:
            brief = (
                f"用户描述：{text}\n"
                "（自动细化失败，请严格按系统规则补全所有细节，禁止照抄这段短描述。）"
            )
        _emit(
            on_progress,
            stage="prompt",
            value=55,
            max=100,
            note=f"{agent_name} 正在转换为专业提示词…",
        )
        result, reason = _to_prompt(agent, brief, on_usage=on_usage)
        if result is None:
            result, reason = _to_prompt(agent, brief, strict=True, on_usage=on_usage)
        if result is None:
            result, reason = _to_prompt(agent, brief, strict=True, final=True, on_usage=on_usage)
        if result is None:
            return {
                "ok": False,
                "positive": "",
                "negative": "",
                "brief": brief,
                "tuned": tuned,
                "agent_name": agent_name,
                "error": f"提示词生成失败：AI 未返回合格的英文提示词（{reason}），请重试。",
            }
        _emit(on_progress, stage="done", value=100, max=100, note="提示词已生成")
        return {
            "ok": True,
            "positive": result["positive"],
            "negative": result["negative"],
            "brief": brief,
            "tuned": tuned,
            "agent_name": agent_name,
            "error": "",
        }
    except LLMConfigError as exc:
        return {
            "ok": False,
            "positive": "",
            "negative": "",
            "brief": "",
            "tuned": tuned,
            "agent_name": agent_name,
            "error": f"提示词生成失败：{exc}",
        }
    except (LLMTimeoutError, LLMAPIError) as exc:
        return {
            "ok": False,
            "positive": "",
            "negative": "",
            "brief": "",
            "tuned": tuned,
            "agent_name": agent_name,
            "error": f"提示词生成失败：{exc}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "positive": "",
            "negative": "",
            "brief": "",
            "tuned": tuned,
            "agent_name": agent_name,
            "error": f"提示词生成失败：{exc}",
        }


__all__ = ["translate"]
