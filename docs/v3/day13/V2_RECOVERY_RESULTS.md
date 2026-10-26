# Day 13：V2 独立旧依赖环境恢复结果

执行时间：2026-10-23 10:06—10:12（Asia/Shanghai）。本项结论：**通过限定范围的实际恢复验收**。恢复使用旧 V2 代码与旧库；没有用 V3 Graph 解释旧 Checkpoint，也没有改写原始学习库或备份包。

## 1. 环境与安装

- 归档包：`D:/SkillTree_AI/skilltree/work/day9/v2-baseline-verified-20261014`。
- 新环境：`D:/SkillTree_AI/day13-isolated-20261023/v2-clean-env`。
- 恢复副本：`D:/SkillTree_AI/day13-isolated-20261023/v2-restored`。
- Python **3.11.15**；`sys.prefix != sys.base_prefix`，`include-system-site-packages=false`，用户 site-packages 关闭。实际安装分发包全部位于新 venv，不借用原 conda 的 site-packages。
- 按包内原 `code/requirements.txt` 安装，并直接使用包内原 `environment/pip-freeze.txt` 作为 constraints，两个文件均未修改。
- 安装的 **52 个需求依赖闭包包**与旧 freeze 的版本全部一致；`pip check` 为 `No broken requirements found`。这包括 LangGraph 1.0.9、Checkpoint 2.1.2、SQLite Saver 2.0.11、langchain-core 1.2.16、langchain-openai 1.1.10、Pydantic 2.11.4、OpenAI SDK 2.54.0。
- 新 venv 的引导工具为 pip 24.0、setuptools 79.0.1。旧 freeze 的 pip 是不可移植的构建目录 URI，setuptools 为 80.9.0；未将这两个引导工具宣称为与旧 conda 完全一致。未安装旧 conda 中与 V2 需求无关的训练、向量库及文档处理包。

首次安装确实失败：Windows 默认 GBK 无法解析旧 requirements 的 UTF-8 中文注释，退出码 2。完整日志保留在 `work/day13-20261023/v2-install.log`。随后只增加 Python 的 `-X utf8` 开关，使用同一份 requirements 和 constraints 安装成功，退出码 0。没有通过改依赖、借用全局包或改写旧包绕过失败。

环境证明与逐包比对：

- [新环境路径、版本、包位置](../../../work/day13-20261023/v2-environment.json)
- [52 个依赖匹配及引导工具差异](../../../work/day13-20261023/v2-dependency-match.json)
- [安装成功日志](../../../work/day13-20261023/v2-install-utf8.log)
- [pip check](../../../work/day13-20261023/v2-pip-check.log)

## 2. 真实旧等待点：两个进程一致

旧包包含 4 个业务项目、3 个 Checkpoint 线程。恢复程序确实调用包内旧版 `build_graph`、`LearningSession.restore()` 和公开状态投影。

选中的真实旧项目保持以下身份：

| 字段 | 恢复结果 |
|---|---|
| project_id / thread_id | `project_db4878f84b0241fcad8d2245882c9a2d`，二者相同 |
| pending_input_id | `learning_33bc9c2840a943709535c0ca38aa8b59` |
| 当前节点 | `variables_and_types` |
| 等待点 / 页面 | `wait_learning` / `learning` |
| assessment_id / 当前试卷 | 均为空，与原等待教学状态一致 |
| 课程 SHA-256 | `40f7a9efcca9e8562ccf6ff52fab1f81b65694f1331f7a4795795bdb7da34efa` |

主恢复演示分别在 PID **108084、109100** 的两个新进程读取，同一项目的上述身份、等待点、内容和哈希完全一致。

另以 PID **108448、107268** 的两个独立探针进程再次核对：`sys.executable` 均为新 venv 的解释器；Graph、State、Repository、LearningSession 均从旧包 `code/app/` 导入；项目完整读取结果一致，恢复副本业务库和 Checkpoint 主文件未变。

旧 Checkpoint 记录的业务库是原绝对路径。演示沿用既有只读 Saver 适配器，仅在内存返回值中将该路径指向恢复副本，并校验原路径归属；**没有直接编辑 Checkpoint 内部表或序列化数据**。

## 3. 待作答补充与限制

旧包**没有可恢复的真实 `wait_answer` Checkpoint**。`day6_demo_project` 只有 `awaiting_answer` 业务记录、没有对应 Checkpoint；本次如实保留其孤立状态，没有补造用户历史或将其算作恢复成功。

为单独验证等待作答的持久化，在恢复副本内用匹配的旧 V2 Graph 创建了明确标记的 Fake 项目，再在另一新进程读取：

| 字段 | 隔离 Fake 结果 |
|---|---|
| project_id / thread_id | `day9_isolated_fake_wait_answer` |
| pending_input_id | `answer_cef0b0d9fe094f04b35141c206ed41b2` |
| assessment_id | `assessment_2bc71082ad60` |
| 等待点 / 页面 / 业务状态 | `wait_answer` / `quiz` / `awaiting_answer` |
| 题目 | 同一份 2 题试卷，题干、选项、题号及测验身份均一致 |
| 私有完整试卷 SHA-256 | `57af50ffb13865c4dfb12e6d61247cbcab8ae1a1eb3a1e573d9d2496e6ed3948` |
| 写入 / 重启读取 PID | **99960 / 109776** |

业务库试卷与 Checkpoint 试卷一致。这个结果仅证明隔离 Fake 待答状态可跨进程恢复，**不替代真实旧用户待答存档证据，也不评价真实模型的教学或评分质量**。

真实旧等待点的只读阶段，恢复副本主文件和有效 WAL 哈希保持不变。后续创建 Fake 项目会有意写入恢复副本；不能把只读阶段的“副本未变”扩大为整个 Fake 演示都没有写入。

## 4. 原始数据、密钥与网络

原始 V2 两库在本次前后 SHA-256 完全一致：

| 原始文件 | 前后相同 SHA-256 |
|---|---|
| `data/learning.sqlite` | `af7d1a3c8680b9d47f92cc6f9a36ea08ad3811f08f20a23a6e072bd7fd936f33` |
| `data/checkpoints.sqlite` | `463c7570f6a7e035c03c143b3f8caf08dcf4040ec8e1739c285e92dbd971333d` |

以上是 **2026-10-23 当次原库**哈希；没有拿 Day 9 的旧哈希冒充今天的原库。备份包 96 个声明载荷文件和 manifest 校验均通过；开始前已有的空 WAL/SHM 辅助文件也原样保留，所有 99 个包内实际文件的前后哈希一致。未删除、覆盖、升级旧包。

恢复运行没有复制 `.env`，运行环境使用不含模型凭据的变量白名单；在导入旧 V2 前禁用 dotenv 读取，模型入口和真实模型函数全部设置为失败守卫，TCP 连接也禁止。恢复过程真实模型调用 **0**；两个补充探针启用网络审计，`socket.connect`、`socket.sendto`、`socket.getaddrinfo` 事件合计 **0**。依赖安装的包下载不属于该“离线恢复运行”范围。

## 5. 实际命令与证据

执行命令的完整参数、工作目录、开始结束时间和退出码保存在 [v2-commands.json](../../../work/day13-20261023/v2-commands.json)。成功的核心命令为：

```powershell
& D:/conda_envs/edu_agent/python.exe -B -m venv D:/SkillTree_AI/day13-isolated-20261023/v2-clean-env
& D:/SkillTree_AI/day13-isolated-20261023/v2-clean-env/Scripts/python.exe -B -X utf8 -m pip install --disable-pip-version-check -r D:/SkillTree_AI/skilltree/work/day9/v2-baseline-verified-20261014/code/requirements.txt -c D:/SkillTree_AI/skilltree/work/day9/v2-baseline-verified-20261014/environment/pip-freeze.txt
& D:/SkillTree_AI/day13-isolated-20261023/v2-clean-env/Scripts/python.exe -B -X utf8 D:/SkillTree_AI/skilltree/day9_v2_recovery.py verify --package D:/SkillTree_AI/skilltree/work/day9/v2-baseline-verified-20261014
& D:/SkillTree_AI/day13-isolated-20261023/v2-clean-env/Scripts/python.exe -B -X utf8 D:/SkillTree_AI/skilltree/day9_v2_recovery.py demo --package D:/SkillTree_AI/skilltree/work/day9/v2-baseline-verified-20261014 --directory D:/SkillTree_AI/day13-isolated-20261023/v2-restored --fake-wait-answer
```

重复演练必须另选全新恢复目录，不覆盖本次证据或现有数据。

- [综合机器结论](../../../work/day13-20261023/v2-result.json)
- [完整恢复身份及 Fake 试卷证据](../../../work/day13-20261023/v2-recovery-evidence.json)
- [额外进程探针 1](../../../work/day13-20261023/v2-runtime-probe-1.json)、[探针 2](../../../work/day13-20261023/v2-runtime-probe-2.json)
- [原库与包全部文件：执行前哈希](../../../work/day13-20261023/v2-before-hashes.json)、[执行后哈希](../../../work/day13-20261023/v2-after-hashes.json)
- [演练编排脚本](../../../work/day13-20261023/v2_clean_recovery.py)、[只读进程探针](../../../work/day13-20261023/v2_worker_probe.py)

本次没有重新运行旧 V2 全量 pytest；包内 `250 passed` 是 Day 9 捕捉时的历史基线，不是今天新增的测试成绩。本次交付证据是实际新环境安装、包校验、旧 Graph 真实等待点跨进程恢复、隔离 Fake 待答恢复、网络及文件不变检查。
