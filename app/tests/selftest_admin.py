"""管理员后台离线自测：隐私数据/密码哈希、会话、Agent 提示词在线编辑（临时目录，不改真实文件）。"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        raise SystemExit(1)


def test_secrets() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mpwe_secrets_"))
    os.environ["MPWE_PRIVATE_DIR"] = str(tmp)
    try:
        from app.admin import secrets_store as ss

        p1 = ss.ensure_salt()
        p2 = ss.ensure_salt()
        _check("固定盐幂等生成", p1 == p2 and p1.exists())
        data = ss.load_secrets()
        salt = (data.get("admin") or {}).get("salt")
        _check("盐为 16 字节 hex（32 位）", bool(salt) and len(salt) == 32, salt or "")
        _check("初始未设置密码", not ss.password_set())
        _check("未设密码时校验为 False", not ss.verify_password("anything"))

        ss.set_password("Admin@12345")
        _check("设置密码后 password_set", ss.password_set())
        _check("正确密码通过", ss.verify_password("Admin@12345"))
        _check("错误密码拒绝", not ss.verify_password("wrong-pass"))
        _check("空/超长密码拒绝", not ss.verify_password("") and not ss.verify_password("x" * 200))
        try:
            ss.set_password("short")
            _check("短密码被拒绝", False)
        except ValueError:
            _check("短密码被拒绝", True)

        # 改密复用同一固定盐
        ss.set_password("NewPass@6789")
        _check("旧密码失效", not ss.verify_password("Admin@12345"))
        _check("新密码生效", ss.verify_password("NewPass@6789"))
        data2 = ss.load_secrets()
        _check("改密后盐保持不变（固定盐）", (data2["admin"]["salt"] == salt))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        os.environ.pop("MPWE_PRIVATE_DIR", None)


def test_sessions() -> None:
    from app.admin import sessions

    token = sessions.create_session()
    _check("会话创建且有效", sessions.session_valid(token))
    _check("空/未知会话无效", not sessions.session_valid(None) and not sessions.session_valid("bad"))
    sessions.invalidate(token)
    _check("注销后会话失效", not sessions.session_valid(token))


def test_prompts_roundtrip() -> None:
    src = PROJECT_ROOT / "app" / "prompting" / "agent_prompts.yaml"
    tmp = Path(tempfile.mkdtemp(prefix="mpwe_prompts_"))
    copy = tmp / "agent_prompts.yaml"
    shutil.copy2(src, copy)
    try:
        from app.admin import prompts_api
        from ruamel.yaml import YAML
        import yaml as pyyaml

        agents = prompts_api.list_agents(copy)
        _check("列出全部 Agent（共用扩写 + 各模型翻译）", len(agents) >= 2, str([a["id"] for a in agents]))
        v14 = next((a for a in agents if a["id"] == "translate_agent:one obsession_v14.safetensors"), None)
        _check("V14 翻译 Agent 在列", v14 is not None)
        exp = next((a for a in agents if a["id"] == "expand_agent"), None)
        _check("共用扩写 Agent 在列", exp is not None)
        model_agents = [a for a in agents if a["id"].startswith("translate_agent:")]
        _check("全部模型翻译 Agent 在列（10 个）", len(model_agents) == 10, str(len(model_agents)))

        updated = prompts_api.update_agent(
            v14["id"],
            name="One Obsession V14 Prompt Engineer (Edited)",
            description="test edit",
            prompt=v14["prompt"] + "\n# TEST EDIT MARKER\n",
            path=copy,
        )
        _check(
            "更新成功且回读一致",
            "(Edited)" in updated["name"] and "# TEST EDIT MARKER" in updated["prompt"],
        )

        # 注释保留 + PyYAML 可解析（运行时 loader 兼容）
        raw = copy.read_text(encoding="utf-8")
        _check("文件头注释保留", raw.startswith("# ==="))
        doc = pyyaml.safe_load(raw)
        _check(
            "PyYAML 可解析",
            doc and "# TEST EDIT MARKER" in doc["models"]["one obsession_v14.safetensors"]["translate_agent"]["prompt"],
        )
        # ruamel 再次读取一致
        agents2 = prompts_api.list_agents(copy)
        v14b = next(a for a in agents2 if a["id"] == v14["id"])
        _check("ruamel 二次读取一致", "# TEST EDIT MARKER" in v14b["prompt"])

        try:
            prompts_api.update_agent("translate_agent:not_exist.safetensors", prompt="x", path=copy)
            _check("不存在的 Agent 报 KeyError", False)
        except KeyError:
            _check("不存在的 Agent 报 KeyError", True)
        try:
            prompts_api.update_agent(v14["id"], prompt="   ", path=copy)
            _check("空提示词被拒绝", False)
        except ValueError:
            _check("空提示词被拒绝", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_secrets()
    test_sessions()
    test_prompts_roundtrip()
    print("\n全部通过。")
