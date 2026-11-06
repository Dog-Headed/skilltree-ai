# Training Demo Progress (Grok Bot)

Updated: 2026-11-06 (Asia/Shanghai). Owner: Grok Bot continuous implementation.

适用提交：GitHub `main` `d9482127ef3e2de07a15886aa45e4a7f6ef339e7`。该提交是 PR #19 的 squash，父提交为 PR #18 `bbdb3bce0d2d172f0c49c5378f67f0736c82f4fd`。

## GitHub `main`

| Item | Result |
|---|---|
| Day2 | PR #2 |
| 4A | PR #3 |
| Day3 publish/assign | PR #4 → `a40004d` |
| Day3 employee start | PR #5 → `f2998f3` |
| Day4 dashboard | PR #6 → `7baff8f` |
| Day5 rehearsal + docs | PR #7 → `3a98441` |
| Garden skin | PR #17 → `d38857b` |
| R01–R05 确认草稿发布并按同一标准领取 | PR #18 → `bbdb3bc` |
| R06–R07 制度断言与 PDF 按可靠标题拆章 | PR #19 squash → `d948212` |
| Production | 部署目标为上述 `main`。2026-11-05 写过的「still on `80d53f4`; **not deployed**」只适用于当日 Day 5 文档，不描述 2026-11-06 |

## 代码、运行标记与同步范围

2026-11-06：GitHub 与服务器已同步。Windows 本机仓未强制覆盖、待用户自行同步。不要为对齐而覆盖用户未提交文件。

生产健康检查的 `version` 不是目录里的 `git rev-parse HEAD`。`deploy/asgi.py` 的 `GET /healthz` 返回环境变量 `SKILLTREE_COMMIT`；`deploy/update.sh` 在快进部署时把该变量写入 `/etc/skilltree/runtime.env`。此前目录 HEAD（审查时为 `d38857b`）与回环 `/healthz`（`89f51f4`）不一致，根因是这份标记滞后，不是两套源码。运维侧已按实际部署提交写回 `SKILLTREE_COMMIT`。

本工作区于 2026-11-06 探测公网：`https://skilltree.goutouren.work/` 返回 303 到 `/learn#/garden`，`/login` 返回 200；公网 `/healthz` 仍被 Nginx 403，因此这里不把公网响应当成新的提交号探针。提交号以 GitHub `main` `d948212` 与运维写回的 `SKILLTREE_COMMIT` 为准。

## Status

- [x] Day 2 fidelity offline + docs
- [ ] Day 2 live model DOCX recheck（R06 真实模型首讲；本环境无模型密钥，未做）
- [x] 4A registration + members（代码与离线测试；三个正式库测试管理员仍待运维，见 R09）
- [x] Day 3 publish/assign + employee start（PR #18 起改为发布已确认草稿，并保留课程语义）
- [x] Day 4 Dashboard
- [x] Day 5 Full demo rehearsal (offline isolated)
- [x] R06 离线检测（否定、主体、条件）；真实模型证据未补
- [x] R07 PDF 拆章离线回归
- [ ] R08 真实模型浏览器闭环（未做）
- [ ] R09 生产三个测试管理员（未创建）

## Tests

专项与全量离线结果记在 [FIX_REPORT.md](FIX_REPORT.md)，不在这里拼接不同日期的通过数。

## Deploy readiness

2026-11-06 的生产部署目标是当前 `main` `d948212`。本地演示脚本不得指向 `work/training-demo/production`，也不得清空库或用本地示例密码初始化公网。服务器更新仍走备份、快进与 `SKILLTREE_COMMIT` 写回，而不是把 Windows 工作区强制覆盖上去。

## Next

1. 用户自行同步 Windows 本机仓（保留未提交文件）
2. R08：隔离实例上的真实模型浏览器闭环
3. R09：运维在正式库创建三个测试管理员，密码只进私密文件
