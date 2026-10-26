# Day 13 评价参考绑定：独立浏览器复核

日期：2026-10-23。范围：普通网页导入 `assessment_private` 资料后，经显式选择用途确认计划的最小修复。此报告独立检查页面交互、公开响应和数据库事实，不代替真实模型内容质量评价。

## 环境与隔离

- 实际交付的 `app/static/v3.html`、`v3.js`、`v3.css`，Microsoft Edge / Chromium 无头浏览器。
- 桌面 1440×960；手机宽度 390×844。
- 真实 FastAPI、Preparation / Learning Graph、SQLite 与持久化上下文，模型使用明确的 Fake。
- 每次执行由 pytest 建立独立临时业务库与 Checkpoint；未打开部署中的业务库或用户浏览器配置，不访问付费模型或保留评价案例。
- 本复核只新增测试及报告；生产界面、API、Graph 的修复由主 Agent 统一修改。

## 检查范围

| 场景 | 页面操作与断言 | 数据库检查 |
|---|---|---|
| `desktop-bind` | 创建数学档案 → 公开教学资料 → 规划 → 私有参考导入 → 重新规划 → 绑定第一个节点 → 冻结 → 开始学习 | 参考进入冻结清单；只形成 `assessment` / `grading` 链接，不进入教学上下文 |
| `mobile-refresh-bind` | 390px；清除本机参考标题后刷新，以“评价参考 1”泛化标签重新选择节点 | 与桌面绑定相同；无页面水平溢出，选择与确认可操作 |
| `explicit-exclude` | 明确选择“本计划不使用”，仍可冻结并进入学习 | 私有参考不进入冻结清单，不产生任何用途链接 |
| `missing-choice` | 未选择用途、选择绑定但未选节点，两次均阻止发送确认 POST；再明确排除 | 只保存最后一次有效确认 |
| `stale-and-duplicate` | 双击确认只发一次；相同请求重放；第二标签页旧确认返回 409 后刷新到冻结状态 | 参考链接与准备命令未重复；请求计数与普通绑定场景一致 |
| `safe-text` | 私有标题中的 HTML 是本机文字；公开来源中的 `<script>` / `<img onerror>` 作为原文展示 | 私有正文、私有标题不进入公开响应；脚本不执行 |

所有场景还检查：页面无未捕获异常、公开响应无测试私有正文、学习页面无私有正文；成功导入后的隐藏输入框也必须清除私有正文。

## 复核发现与过程证据

1. 首次针对可见页面、API 与实际绑定的六场景运行：**6 passed，30.12 秒**。目录：`work/day13-20261023/private-reference-browser/`。
2. 增加隐藏输入框检查后，发现导入成功关闭弹窗时，用户刚粘贴的私有正文仍残留在隐藏 `textarea.value` 中。此时公开响应与可见页面均无正文，但不满足成功后清理 DOM 的严格检查。单独复现：**1 failed，7.74 秒**。失败证据保留在 `work/day13-20261023/private-reference-browser-hidden-dom-review/desktop-bind/failure.json` 与 `failed.png`。
3. 主 Agent 已修复：只在导入确认成功后清空正文/文件，失败时保留用户草稿。最终复验结果见下节；初始失败文件未删除、未覆盖。

## 最终复验

主 Agent 完成隐藏输入清理和冻结前上下文预检后，已在独立证据目录重新运行全部加强版场景：**6 passed，32.14 秒**，无跳过。日志为 `work/day13-20261023/private-reference-browser-final-pytest.log`。仅有依赖弃用警告，无页面异常。执行命令：

```powershell
$env:DAY13_PRIVATE_REFERENCE_EVIDENCE_DIR='D:\SkillTree_AI\skilltree\work\day13-20261023\private-reference-browser-final'
& 'D:\conda_envs\edu_agent\python.exe' -m pytest tests/test_day13_private_reference_frontend.py -q
```

每例保留 `result.json`（实际请求、响应状态、视口及断言）、`database-facts.json`（冻结清单、链接数、有效命令与请求数）以及桌面或手机截图。私有测试内容是人工指定的合成哨兵字符串；证据不是用户真实资料。

最终结果：

| 场景 | 结果 | 私有用途链接数 | 准备有效命令数 | 模型请求预占数 |
|---|---|---:|---:|---:|
| 桌面绑定 | 通过 | 4，仅第一个节点的出题/评分 | 3 | 3 |
| 手机刷新后绑定 | 通过 | 4，仅第一个节点的出题/评分 | 3 | 3 |
| 明确排除 | 通过 | 0 | 3 | 3 |
| 未选用途 / 未选节点 | 通过；两次均为 0 次确认 POST，最后明确排除 | 0 | 3 | 3 |
| 连点 / 重放 / 两标签页 | 通过；双击 1 次 POST，原请求重放 200，旧页面确认 409 | 4 | 3 | 3 |
| HTML / 脚本文本 | 通过；另加公开脚本文本后多一次重规划 | 4 | 4 | 4 |

成功绑定的四条链接来自第一个节点两个目标 × 两种私有用途。绑定、排除、陈旧确认场景均未增加额外模型请求。六例最终都处于 `learning`，隐藏输入框、可见页面和公开响应均无测试私有正文；由用户在本机填写的私有标题仅作为本机文字标签，不作为服务器返回字段。

截图抽查：`private-reference-browser-final/mobile-refresh-bind/mobile-generic-reference-selected.png`（390px，刷新重建泛化标签后仍可选择）；同目录 `mobile-learning.png`；`private-reference-browser-final/desktop-bind/desktop-frozen-plan.png`、`desktop-learning.png`。手机截图无水平溢出，资料、节点选择和确认按钮均可读可操作。

## 结论边界

这些测试证明显式绑定/排除、过期确认、连点与数据隔离的产品路径。Fake 不证明参考答案正确性、真实出题质量或真实文字评价质量，也不改变三科/第四主题正式评价的结论。
