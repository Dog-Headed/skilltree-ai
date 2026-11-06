# 公网 Docling 内存配置

2026-11-06 核对，公网 Nginx 代理到 `127.0.0.1:8767`。Docling 文件解析运行在 `skilltree-evaluation.service` 内，服务器已加载以下配置。

文件位于 `/etc/systemd/system/skilltree-evaluation.service.d/docling-mem.conf`，属主 `root:root`，权限 `0644`。

```ini
[Service]
MemoryHigh=1100M
MemoryMax=1400M
```

`MemoryHigh` 是触发内存回收的阈值，`MemoryMax` 是整项服务的硬上限，包含 Docling 与同进程处理的其他请求。核对时主机可用总内存约 1.6 GiB，另有 4 GiB swap。PDF 使用 NativePdfPipeline。上传大小、页面及文本限制见 [自动拆章](AUTO_SPLIT.md)。

新机器恢复该配置时，备份原 drop-in，再将以上内容安装到同名文件。确认学习队列空闲后执行 `sudo systemctl daemon-reload` 和 `sudo systemctl restart skilltree-evaluation`。检查实际生效值和回环健康状态。

```sh
systemctl show skilltree-evaluation -p ActiveState -p DropInPaths -p MemoryHigh -p MemoryMax
curl -fsS http://127.0.0.1:8767/healthz
```

预期值为 `MemoryHigh=1153433600` 和 `MemoryMax=1468006400`（字节）。问题排查可查看 `MemoryCurrent`、`MemoryPeak`、`NRestarts` 和该服务的 journal。回滚时还原先前文件。如果之前无此文件，只移走 `docling-mem.conf`，随后重新加载并重启该服务。培训用 `training.conf` 独立保留。
