# SkillTree AI Agent 学习版

基于 [V2.0 架构](./SkillTree_Agent学习版架构_V2.0.md)逐步实现的 Python 学习项目。当前已有可运行的命令行学习流程：规划、教学、测验、评分、补弱与复测；Diagnosis 使用确定性规则实现，后续将加入模型工具调用。

## 快速开始

当前使用 Python 3.11 验证。在项目目录中创建虚拟环境并安装依赖：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

在本地 `.env` 中填写 `LLM_MODEL`、`LLM_API_KEY` 和 `LLM_BASE_URL`，然后启动交互演示：

```powershell
.\.venv\Scripts\python.exe day4_demo.py
```

命令行中可以提问、开始测验、查看反馈并复测。简答题支持多行输入，以单独一行 `END` 结束。运行真实演示会调用配置的模型服务。

## 自动测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

自动测试使用固定模型结果，并阻止真实模型调用，无需配置模型密钥。测试覆盖规划校验、条件分支、中断恢复、测评与交互演示。

## 当前实现状态

- Planner：模型生成结构化规划，Pydantic 和 DAG 校验通过后写入 State。
- Tutor：首次教学、追问与针对性补弱。
- Assessment：固定试卷与评分标准，客观题程序判分，简答题模型评价，程序计算总分。
- LangGraph：等待用户输入、恢复执行、补弱复测及通过条件检查。
- 执行现场使用 `InMemorySaver`，仅在当前进程内保留。
- SQLite 持久化、工具诊断、API 与 HTML 页面按后续阶段实现；相关文件保留占位。

## 项目范围

- 本地单用户，首版学习 Python 基础的 8–12 个技能节点。
- 使用 Planner、Tutor、Assessment、Diagnosis 四类 Agent，形成规划、教学、测评、诊断、补弱或推进的闭环。
- 后端计划使用 FastAPI、LangGraph、Pydantic；业务记录与执行现场分别保存到 SQLite 业务库和 Checkpoint。
- 前端计划使用一个简单 HTML 页面。

## 目录说明

| 路径 | 预留用途 |
| --- | --- |
| `app/main.py` | API 入口、启动资源、输入校验和公开响应 |
| `app/state.py` | 共享 State 与消息合并规则 |
| `app/graph.py` | 图结构、条件路由、等待和推进节点 |
| `app/agents/` | 四类 Agent 的职责实现 |
| `app/tools/` | 历史、前置状态与节点材料的只读工具 |
| `app/models/schemas.py` | 规划、试卷、评价和诊断的数据契约 |
| `app/db/repository.py` | 四张业务表及具体数据库操作 |
| `app/services/llm.py` | 模型配置、结构化调用与有限重试 |
| `app/static/index.html` | 单页演示界面 |
| `tests/` | 规则、交互和治理测试 |
| `data/` | 课程骨架、短材料及本地数据库文件 |

## 建议实施顺序

1. State、最小图和四个固定输出节点。
2. 等待用户输入、中断与恢复。
3. 结构化规划和 DAG 校验。
4. 教学、出题、评分与复测闭环。
5. Diagnosis 的只读工具调用。
6. SQLite 业务记录与 Checkpoint 持久化。
7. 超时、重试、轮数限制和评价案例。
8. API、单页界面与演示。

依赖版本记录在 `requirements.txt`，模型变量模板见 `.env.example`。真实密钥只保存在本地 `.env`；本地环境、数据库与缓存由 `.gitignore` 排除。
