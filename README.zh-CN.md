# refspec-lens 中文说明

离线解释 Git fetch refspec：哪些远端引用被映射、被负向规则排除、映射到哪里，
哪些本地引用处于 prune 覆盖范围。输出包含规则编号、目标冲突证据及 JSON，
不会联网、调用 Git、修改配置或删除引用。

需要 Python 3.11+，无运行时第三方依赖。克隆后建立并激活虚拟环境，运行
`python -m pip install .` 与 `python examples/demo.py`。示例的对象 ID 明确为
合成数据；测试套件另用真实 Git 仓库对照 fetch/prune 行为。

输入为 UTF-8 的完整 `对象ID 引用名` 快照。远端使用 `git ls-remote --refs origin`；
本地应排除符号引用，英文 README 提供完整命令。PowerShell 5 请用
`Set-Content -Encoding utf8`，避免默认 UTF-16。每条 refspec 用独立 `--refspec` 指定。

返回码 0 表示通过，1 表示映射冲突、精确源缺失，或启用 `--prune` 后发现裁剪暴露；
2 表示无效输入或超限。裁剪候选仅为输入快照下的风险范围，不是执行计划，不能推断
快进、安全更新或实时服务器状态。自动跟随标签、符号引用、短名称及空目标不支持。

默认每快照 16 MiB、100000 引用，总规则 128，展开匹配总数 200000。
只在 GitHub 发布源码及 wheel，未发布 PyPI。卸载使用
`python -m pip uninstall refspec-lens`，按需删除专用环境和快照。
