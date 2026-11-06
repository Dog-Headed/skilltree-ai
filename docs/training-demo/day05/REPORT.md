# Day 5 报告：隔离实例完整演练

更新日期：2026-11-05（Asia/Shanghai）。

## 完成标准对照

| 项 | 结果 |
|---|---|
| 新隔离演示实例（保留现用实例） | `tests/test_training_day05_rehearsal.py` 使用临时 `root`，不触碰生产目录 |
| 初始化虚构单位与四成员；游客入口 | 启动自动种子；`visit()` 游客可进 `/training/home` |
| 上传四格式并核对解析；损坏/不支持正确失败 | samples 下 pdf/docx/xlsx/pptx 均 ready；`broken.exe` 失败 |
| 管理员发布短课并下发甲乙 | publish + assign；丙任务列表为空 |
| 一人完整通过；另一人答错进入补弱/诊断 | 甲 3/3 必学节点；乙 `guard.passed=false` 且 `mode=remediate` |
| 丙与游客自主学习（不计单位任务） | 各自 `POST /projects` 201；看板仍仅 2 人 |
| 看板反映真实状态；幂等下发 | completed=1 / started=2；同 `request_id` assign 复用 |
| 重启同实例恢复进度 | `test_day05_restart_keeps_progress`：lease 释放后重开，完成记录与乙进行中仍在 |
| 不降低通过标准 | Fake 评测仍走原引擎守卫与节点推进 |

## 测试

```bash
.venv/bin/python -m pytest tests/test_training_day05_rehearsal.py -q
```

本机记录：**2 passed**（完整闭环 + 重启保持）。

与 Day3/Day4 一并：

```bash
.venv/bin/python -m pytest \
  tests/test_training_day05_rehearsal.py \
  tests/test_training_dashboard.py \
  tests/test_training_employee_start.py \
  tests/test_training_publish_assign.py -q
```

## 生产部署

2026-11-05 本文适用提交为 Day 5 合并 PR #7（`3a98441`）。当时写的是：**未部署。** 公网仍停在 `80d53f4`。那份报告本身不构成部署许可，也不能再当成当前生产版本。

2026-11-06：GitHub `main` 为 `d948212`（含 PR #18 `bbdb3bc` 与 PR #19 squash `d948212`），生产按该 `main` 部署。此前 healthz 与目录不一致，是因为 `/healthz` 返回 `SKILLTREE_COMMIT` 而不是目录 `HEAD`；该标记已在运维侧按实际部署提交写回。GitHub 与服务器已同步。Windows 本机仓未强制覆盖、待用户自行同步。不要为同步覆盖用户未提交文件。详见 [PROGRESS.md](../PROGRESS.md)。

## 交付物

- `DEMO_SCRIPT.md`：5–8 分钟演示脚本
- `LIMITATIONS.md`：演示边界与已知限制
- 更新 `START.md` / `CONTRACTS.md` / `PROGRESS.md`
