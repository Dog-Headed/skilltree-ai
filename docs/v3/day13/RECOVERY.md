# V3 三库备份与隔离恢复

恢复工具：`day13_recovery.py`。它不运行模型、不自动迁移、不重新规划，也不修改序列化 Checkpoint。恢复包包含学习答案和私有评价资料，默认保存到已忽略的本机 `work/`；不要上传 GitHub。

## 先停止所有写入

先停止网页服务、后台 worker、导入脚本和其他写入进程；不要只关闭浏览器。尤其要停止“新建项目”入口：仅锁定现有项目无法锁住尚未存在的项目。工具要求 `--writers-stopped` 明确声明，并补充 Windows 进程检查、各项目 OS 锁、业务库 `BEGIN IMMEDIATE` 写闸及全程 main/WAL 字节稳定性检查。进程扫描不能证明没有自定义写入器，操作者停写仍是必要前提。工具不会擅自结束其他进程。

```powershell
.\.venv\Scripts\python.exe day13_recovery.py capture --writers-stopped --package work/day13-private-backup
.\.venv\Scripts\python.exe day13_recovery.py verify --package work/day13-private-backup
.\.venv\Scripts\python.exe day13_recovery.py restore --package work/day13-private-backup --directory work/day13-isolated-restore
```

所有目标必须是新目录；重复捕获和重复恢复都拒绝覆盖。捕获失败时不会发布有效 `manifest.json`，失败目录留作排查，选择新的目录重做。`--data-root` 只用于显式指定另一套 V3；原 V2 `data/` 不可作为 V3 源。完整 Day 11 存储的三个文件必须齐全。

## 包里有什么

* `data/v3/learning.sqlite`：项目、冻结版本、资料原文/哈希/版本/片段、测验、评价、诊断、完成事实、预算和执行日志。
* `data/v3/checkpoints.sqlite`：准备流程 Checkpoint。
* `data/v3/learning-checkpoints.sqlite`：学习流程 Checkpoint。
* `code/`：当前受控源码、测试、资料、配置与文档的允许后缀文件，记录实际工作树内容摘要；有 Git 时另记 HEAD 与 dirty，没有 Git 也按文件内容定位版本。
* `environment/`：Python/平台信息及已安装包的名称与版本。项目 `requirements.txt` 随源码保存；不保存可能带凭证的 pip direct URL。
* `manifest.json`：全部文件哈希、长度、三库版本/表数/结构、项目/thread/等待输入/测验身份与已保存事实摘要、原数据未变证据。

排除真实 `.env`、凭证文件、私钥、执行文件、`.git`、虚拟环境、运行数据目录和日志；仅允许无真实配置的 `.env.example`。模型密钥应通过独立受保护的配置重新提供，Fake 工程恢复无需密钥。恢复包没有把外部依赖 wheel 一并离线缓存，创建新环境仍需可用的软件源；包内版本信息不等于任意操作系统的兼容承诺。

SQLite `backup()` 包含已提交 WAL 页面，保证单库一致性；三库之间没有跨数据库原子事务。因此必须停写、持有项目锁并比较三库备份前后 main/WAL 完全一致，不能把三次独立在线拷贝当作一个原子快照。业务写入后、Checkpoint 更新前的断点会按原样保留，由现有 journal/retry 和结果复用机制恢复，工具不会“修正”历史。

## 验证和恢复边界

`verify` 使用只读、immutable SQLite 连接；只解析 JSON 和 SQL 行，不 import 包内代码、不反序列化 Checkpoint。拒绝缺清单、额外文件、危险/秘密文件名、路径穿越、symlink/junction、文件哈希不符、数据库完整性/外键问题、版本错误及业务身份冲突。包的普通 SHA-256 清单用于发现损坏，**不是对抗恶意整体替换的数字签名**；应保护原包并从可信来源恢复。

恢复目录为 `<target>/code` 与 `<target>/code/data/v3`，所以从恢复的源码启动会自然使用该副本。原始三库和 V2 两库均不覆盖。先在新虚拟环境安装 `requirements.txt`，再进行 Fake 或明确的真实恢复演示；正式启动前单独配置密钥。`restore` 返回原 project/thread/pending_input/assessment 身份和零模型调用记录；实际继续学习仍须调用正常服务恢复入口。

## V2 独立方案

V2 保持 `day9_v2_recovery.py` 的匹配旧源码 + `learning.sqlite`/`checkpoints.sqlite` 双库方案及其旧依赖环境，不能将 V2 Checkpoint 导入 V3。Day 13 工具只记录原 V2 文件的前后哈希，不打开 V2 写连接、不升级旧库。V2 的既有 capture 同样要求停写；是否实际运行过隔离恢复，应以本轮真实命令与报告为准，不能用本文说明替代执行证据。

## 工程测试与正式验收

`tests/test_day13_recovery.py` 使用真实 SQLite/Checkpoint 和明确标注的 Fake 模型，验证等待身份、已保存评价/诊断/完成事实、重新打开旧卷的复用、只读验证、V2 隔离、秘密排除、重复恢复拒绝、损坏拒绝、创建写闸和捕获期间变化拒绝。这些是工程证据，不是内容质量证据；最终三科保留集、第四主题和干净环境演示须按 Day 13 顺序独立完成。


## 本轮最终实际验证与审阅注意

候选04同义密度资料包的356文件等待点包已在全新依赖环境实际恢复、继续同卷并完成两个依赖节点；身份/旧任务保持、预算7→16、事实唯一、原数据不变。详见CLEAN_RECOVERY_RESULTS.md最终段，旧候选03和失败分支分别保留。

即使SQLite mode=ro也可能为WAL库创建空wal/shm。本轮独审因漏immutable产生4个额外文件，被严格restore正确拒绝。任何手工审阅私有备份必须mode=ro&immutable=1、显式close；勿用普通数据库浏览器直接打开不可变包。若已出现额外文件，先核清单内字节，保存取证，再重新严格验证；不能直接忽略额外文件或改清单让它通过。
