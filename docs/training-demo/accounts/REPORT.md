# 4A 账号与成员管理交付

更新日期：2026-11-05（Asia/Shanghai）。

## 已实现

| 能力 | 说明 |
|---|---|
| 个人注册 | `POST /auth/register` 在学习实例开放；忽略客户端 `role` / `unit_id` |
| 游客升级 | 注册时保留 canonical account，课程／资料／进度继续归属本人 |
| 个人身份 | `/session.training.role=personal`，可自由学习与上传资料；无单位任务／管理权限 |
| 成员查找 | `GET /training/api/admin/members/lookup?q=` 精确邮箱或账号 ID |
| 加入单位 | `POST /training/api/admin/members` → 仅 `employee`；幂等；跨单位 409 |
| 移出单位 | `POST /training/api/admin/members/remove` 只撤成员关系，保留个人数据 |
| 后端管理员 | `python -m deploy.training_admins --qa-admins ...`；非公开 HTTP |

## 预置与 QA 管理员

- 原四个演示成员仍由 `deploy.training_demo.seed` 保证存在且不重置已有密码。
- 目标 QA 管理员：`admin.qa1@example.test`、`admin.qa2@example.test`、`admin.qa3@example.test`。
- 本地／验收实例创建示例：

```bash
python -m deploy.training_admins \
  --auth-db work/training-demo/<instance>/auth.sqlite \
  --training-db work/training-demo/<instance>/training.sqlite \
  --qa-admins \
  --private-out work/training-demo/private/QA_ADMINS.json
```

- 密码只写入 `--private-out`（`work/` 已 gitignore），不进入 README／GitHub／聊天。
- 重复执行幂等：已存在账号不改密码；已是管理员则报告 `already_admin`。
- **生产实例**需在明确授权后对 `work/training-demo/production` 执行同一脚本，并单独保存私密文件。

## 测试

```bash
.venv/bin/python -m pytest tests/test_training_registration_members.py tests/test_training_demo.py -q
```

本交付记录：相关用例通过（含游客升级保留课程、个人注册、管理员加人／幂等／跨单位拒绝、移出保留账号、QA 脚本登录与 overview）。

## 仍未实现（后续阶段）

- Day 3 课程发布与任务下发
- Day 4 看板
- Day 5 完整演练
- 邮箱归属验证、邀请邮件、多单位
