# Day13 干净安装与V3隔离恢复（技术与内容分开）

执行于2026-10-23。根工作树工程全量893通过；全新venv内另跑恢复、评价器、学习恢复、Diagnosis相关85项通过（64.23秒），不是与893相加的独立总数。

## 实际干净启动

在原仓库之外D:/SkillTree_AI/day13-isolated-20261023/clean-install/code新建Python3.11.15 venv，system-site-packages=false、用户site关闭；按requirements安装57个分发包，pip check无冲突。未复制.env或数据，清除了模型环境变量。显式UTF-8运行（安装使用PYTHONUTF8=1，与README的-X utf8等效），避免Windows GBK读取中文注释的问题。V2首轮实际遇到并保留编码失败；README现已明确UTF-8。

显式初始化三库并运行真实app.py入口，GET /、/projects、/capabilities、/legacy/projects均200；项目、测验、model_operations、model_tasks计数均0。只停止了本次自己启动的server子进程。证据：work/day13-20261023/clean-install-evidence.json、clean-install-packages.json、clean-engineering-regression.log。该步骤仅证明新安装与启动，不假称已从空白环境重新创建整门课程。

## 停写捕获和等待点恢复

源是合成SQL隔离项目，并未备份或迁移真实生产项目。等待包work/day13-20261023/sql-waiting-backup包含三库、320个受控文件、资料和环境，实际停写、进程检查、写闸、项目锁和源main/WAL稳定性均通过。包排除密钥，manifest SHA256=21d65b4c1f691a4fa3371529d6d6f7ab3e6fc5b1cc8589a6944d1697e079e751。

实际restore到D:/SkillTree_AI/day13-isolated-20261023/v3-restored/code，使用上述新venv解释器加载恢复代码。原SELECT等待卷、project/thread/pending_input/assessment、完整题面、旧评分/任务和累计预占8全部一致，未改Checkpoint内部数据，恢复与纯读0模型调用。随后正常Graph用保护的外部进程环境配置真实模型（未复制.env），完成SELECT和WHERE，两节点完成各唯一，累计预算8+9=17，原库与包未变。

## 不能混为内容通过

恢复分支新WHERE卷再次将3个普通分项设critical。实际全对6/6与状态推进成立，技术恢复通过；独立内容审查仍阻断该新卷，未把它算全课程内容通过。旧失败原输出、完成事实与审查全部保留。对应work/day13-20261023/unbound-restored-result.json及独立审查记录。

当前进一步验证的是现有Repository显式私有资料绑定配置，不改通用核心或旧冻结卷。结果和是否关闭本次新课程内容阻断须另记，不能由本次技术通过推定。真实生产V2/V3文件前后指纹未变；V2匹配旧环境单独见V2_RECOVERY_RESULTS.md。

## 候选03显式绑定恢复分支（已完成）

随后从合成显式绑定项目制作`work/day13-20261023/sql-bound-waiting-backup`，324个受控文件，实际还原到`D:/SkillTree_AI/day13-isolated-20261023/bound-restored/code`，使用上述新venv加载匹配代码。原project/thread、pending_input、SELECT测验身份、完整题面/私有评价快照、任务与预占8均保持，恢复与只读0模型。

实际继续SELECT12/12，生成新WHERE12分量规（12普通项均非critical），正确回答12/12，两节点各唯一完成、三条唯一迁移；新增9次真实请求，累计17，最大单操作5≤12，没有重试或修复。独立审查逐条核44个实际来源块、22个作答锚点、历史与守卫，内容通过。证据：`work/day13-20261023/bound-restored-result.json`、独立审查JSON/Markdown。原V2/V3库、原管理课程与包哈希保持不变。

旧未绑定恢复分支的内容失败不被此结果抹除。两条恢复都证明三库/资料/代码匹配的重要性，不能据此声称普通上传已经自动绑定评价标准。

## 当前工作树与上述证据的区别

普通产品绑定缺口随后开始修复，通用准备流程、上下文预检、前端及Diagnosis身份提示已变化。因此上述干净安装/实际恢复属于候选03匹配快照的证据；新的工作树仍须按顺序完成开发复验、冻结后验证、新主题及匹配新代码的最终恢复。旧V2旧环境恢复的独立结论保留，不把它升级为V3 Checkpoint可直接兼容旧版。


## 候选04最终匹配环境及密度恢复（2026-10-24）

三科冻结复验和新主题固定评价通过后，首密度普通课程因复合项critical错误被独审阻断；第一份clean-install仅是中间工程证据。随后仅补资料同义澄清，新课程实审通过，再从其旧等待点包执行clean-install-v2。

全新Python3.11.15 venv按requirements安装，禁system/user site，不借原Conda的site-packages，pip check通过，57分发包；app.py实际启动，四HTTP入口200、空三库、0模型、无.env或秘密复制，64.82秒。环境证据D:/SkillTree_AI/day13-isolated-20261024/clean-install-v2/evidence.json。该环境又运行104项必要工程测试通过（78.73秒，1警告），与稳定913有重叠。

356文件包density-v2-waiting-backup实际恢复到day13-isolated-20261024/density-restored-v2/code。同c3fc待答卷、project/thread/pending_input、完整view/counts/tasks全等，7预算保持，读取0模型。使用全新venv加载恢复源码，原卷10/10，后节点新两题4+6=10/10，两完成/三迁移唯一；7+9=16、maxop4/logical3、0修复网络。6个旧任务及旧quiz/非null结果原样复用。root/clean/restored/package四处116个核心指纹均匹配freeze04，原V2/V3五库、源已完成课程不变。

首次restore拒绝未列出的4个空WAL/SHM：审阅SQLite使用mode=ro而非immutable=1导致。先核全部列出字节相等，再保留额外文件至density-v2-read-sidecars，无删除/改DB，strict verify后restore成功。审阅已改immutable=1并显式close；当前包无额外文件，但不能写成从捕获到现在绝无侧文件。incident及首次日志保留。

最终独立内容通过见DENSITY_WORKFLOW_INDEPENDENT_REVIEW.md阶段7，原机械density-restored-result.json审查时pending字段保持历史原字节，派生记录/总报告承接批准。最终演示1440/390纯GET/刷新通过，不额外扣模型预算。V2旧环境证据维持其限定范围，不混为V3能解释旧存档。
