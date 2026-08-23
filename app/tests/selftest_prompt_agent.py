"""AI 提示词 Agent 自测脚本。

用法：
  .venv\\Scripts\\python.exe app\\tests\\selftest_prompt_agent.py           # 离线自测
  .venv\\Scripts\\python.exe app\\tests\\selftest_prompt_agent.py --live    # 真实 LLM 冒烟（需 .env 配好 Key）
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.prompting import agent, loader  # noqa: E402


def _check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        raise SystemExit(1)


def test_loader() -> None:
    exp = loader.get_expand_agent()
    _check("expand_agent 存在且有提示词", bool(exp.get("name")) and bool(exp.get("prompt")), exp.get("name", ""))

    agent_v14 = loader.get_translate_agent("one obsession_v14.safetensors")
    _check("V14 翻译 Agent 命中特调", bool(agent_v14 and agent_v14.get("prompt")), (agent_v14 or {}).get("name", ""))

    supported = loader.get_supported_agents()
    _check("支持清单含 One Obsession V14", "one obsession_v14.safetensors" in supported, str(supported))
    for model_file, name in supported.items():
        agent = loader.get_translate_agent(model_file)
        _check(f"「{name}」配置完整", bool(agent and agent.get("prompt") and agent.get("validation")), model_file)
    _check("已适配模型数量 = model_configs 全部模型（10 个）", len(supported) >= 10, str(len(supported)))

    agent_unknown = loader.get_translate_agent("some_unknown_model.safetensors")
    _check("未知模型返回 None（无回退、不混用）", agent_unknown is None)


def test_parsing() -> None:
    r = agent._extract_positive_negative('POSITIVE: masterpiece, 1girl\nNEGATIVE: lowres, bad anatomy')
    _check("行解析", bool(r) and r["positive"].startswith("masterpiece") and "lowres" in r["negative"])

    r2 = agent._extract_positive_negative('{"positive": "masterpiece, 1girl", "negative": "lowres"}')
    _check("JSON 解析", bool(r2) and r2["positive"] == "masterpiece, 1girl")

    r3 = agent._extract_positive_negative("no structure here")
    _check("无结构输入返回 None", r3 is None)


def test_key_props() -> None:
    brief = "雨夜，女生撑着透明伞站在路灯下，扶着栏杆。"
    positive = "masterpiece, 1girl, holding umbrella, night"
    out = agent._ensure_key_props(brief, positive)
    _check("关键道具补插", "transparent umbrella" in out and "streetlight" in out and "wet railing" in out, out)


def test_key_props_natural_language() -> None:
    brief = "雨夜，女生撑着透明伞站在路灯下，扶着栏杆。"
    positive = "A medium shot of a girl. Her face is calm and wistful."
    out = agent._ensure_key_props(brief, positive, natural_language=True)
    _check(
        "自然语言关键道具插到第一句之后",
        out.startswith("A medium shot of a girl. The key props are")
        and "transparent umbrella" in out
        and "streetlight" in out
        and "wet railing" in out
        and "rain" in out,
        out,
    )


def test_validation() -> None:
    v14 = loader.get_translate_agent("one obsession_v14.safetensors")
    good = (
        "masterpiece, best quality, amazing quality, very awa, absurdres, newest, very aesthetic, "
        "depth of field, highres, 1girl, solo, upper body, close-up, blurred background, "
        "detailed face, long black hair, wet hair, amber eyes, school uniform, holding umbrella, "
        "transparent umbrella with metal ribs, night, rain, wet street, streetlight, "
        "streetlight glow, rim lighting, cinematic lighting, anime style, illustration"
    )
    _check("V14 合格提示词通过校验", agent._quality_ok(v14, good, "lowres, bad anatomy") is None)

    bad_cjk = agent._quality_ok(v14, "masterpiece, 1girl, 雨", "lowres")
    _check("含中文被拦截", "含中文" in (bad_cjk or ""), bad_cjk or "")

    bad_quality = agent._quality_ok(
        v14,
        "1girl, solo, upper body, close-up, blurred background, detailed face, "
        "long black hair, wet hair, amber eyes, school uniform, holding umbrella, "
        "transparent umbrella with metal ribs, night, rain, wet street, streetlight, "
        "streetlight glow, rim lighting, cinematic lighting, anime style, illustration, "
        "standing, looking at viewer, wet skin, water droplets, wet ground, reflection, "
        "moonlight, soft shadows, warm tones",
        "lowres",
    )
    _check("缺质量词被拦截", "质量词" in (bad_quality or ""), bad_quality or "")


def test_translate_no_key() -> None:
    import os

    old = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = ""
    try:
        result = agent.translate("雨夜女生撑透明伞", model="one obsession_v14.safetensors")
        _check("未配 Key 返回明确错误", (not result["ok"]) and "API Key" in result["error"], result["error"])
    finally:
        if old is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = old


def test_translate_unsupported_model() -> None:
    result = agent.translate("雨夜女生撑透明伞", model="some_unknown_model.safetensors")
    _check("未适配模型被拒绝（不混用）", (not result["ok"]) and "暂无适配" in result["error"], result["error"])


def test_live() -> None:
    result = agent.translate(
        "雨夜一个女生撑着透明伞站在路灯下，半身构图，要有氛围感",
        model="one obsession_v14.safetensors",
    )
    print("ok:", result["ok"])
    print("agent:", result["agent_name"], "| tuned:", result["tuned"])
    print("POSITIVE:", result["positive"])
    print("NEGATIVE:", result["negative"])
    print("BRIEF 字数:", len(result.get("brief") or ""))
    _check("真实 LLM 冒烟成功", result["ok"], result.get("error", ""))


if __name__ == "__main__":
    if "--live" in sys.argv:
        test_live()
    else:
        test_loader()
        test_parsing()
        test_key_props()
        test_key_props_natural_language()
        test_validation()
        test_translate_unsupported_model()
        test_translate_no_key()
    print("\n全部通过。")
