#!/usr/bin/env python
"""构建面板并拷入包内:python scripts/build_panel.py(发布 wheel 前必须执行)。

npm run build(web/)→ 产物拷贝到 agent_inspect/panel/,作为包数据随 wheel 分发,
使 pip 安装的用户也能拿到真实面板(而非占位页)。产物不入 git(.gitignore)。
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "dist"
DST = ROOT / "agent_inspect" / "panel"


def main() -> int:
    subprocess.run("npm run build", cwd=ROOT / "web", shell=True, check=True)
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST)
    assert (DST / "index.html").is_file(), "panel build incomplete"
    print(f"[build_panel] panel -> {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
