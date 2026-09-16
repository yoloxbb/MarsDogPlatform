# 日志容量管理

## 项目日志

每个日志组单文件上限 20 MiB，当前文件加 4 个备份共 5 个文件。
`vision_interaction.log` 和 `vision_trace_current.jsonl` 各自最多 100 MiB。
备份后缀 `.1` 最新、`.4` 最旧。重启继续追加固定名称，避免每日或每次启动新增一组。
独立相机驱动使用 `camera_driver.log`，同样最多 100 MiB。
单条记录超过上限时，文件中写入 `log_record_omitted` JSON 提示；终端仍保留原记录。

部署新代码并重启节点后生效。历史日期/PID 文件保留，需取证归档后人工清理。
不同并发视觉实例必须使用不同 `log_dir`；同一组文件仅支持一个进程写入。
新日志上限不包含 ROS launch 日志、`tee` 输出、旧版文件或不同测试目录的累计占用。
需要长期留存时，应定期将测试证据转移至外部存储。

## 系统日志：同时限制两套存储

测试截图中的文件实际为 `/var/log/kern.log.1`、`/var/log/syslog.1`，
各约 6.8 GB。它们由系统日志服务管理；只限制项目日志或 journal 都不能限制这两个文件。
相机连接/驱动故障仍需独立排查；截图不足以证明物理连接是唯一原因。

以下为 Ubuntu/systemd/rsyslog 的建议配置，需在测试设备核对后应用。
本次代码修改未改动系统配置。

### 1. 限制 journal

在 `/etc/systemd/journald.conf.d/60-log-budget.conf` 配置：

```ini
[Journal]
SystemMaxUse=200M
SystemKeepFree=1G
SystemMaxFileSize=20M
RuntimeMaxUse=50M
```

应用后重启 `systemd-journald`，用 `journalctl --disk-usage` 检查占用。
这些限制只影响 journal，不影响 syslog/kern.log；清理以归档 journal 文件为单位，
并非整个 `/var/log` 的绝对硬配额。原有磁盘不足也不会被 `SystemKeepFree` 自动修复。
参见 [systemd journald 配置](https://www.freedesktop.org/software/systemd/man/252/journald.conf.html)。

### 2. 给 syslog/kern.log 加容量轮转并提高检查频率

先核对 `/etc/logrotate.d/rsyslog`。在已经包含目标文件的规则中设置：

```text
daily
maxsize 20M
rotate 4
compress
delaycompress
missingok
notifempty
```

保留设备原有权限配置、`sharedscripts` 和 `postrotate` 中通知 rsyslog
重新打开文件的逻辑；不要另建重复匹配同一文件的规则，也不要额外使用 `copytruncate`。
同时替换原有 `weekly` 等周期配置。当前文件加 4 个备份共 5 个。

通过 `systemctl edit logrotate.timer` 设置每分钟检查：

```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* *:*:00
AccuracySec=1s
RandomizedDelaySec=0
```

运行 `systemctl daemon-reload`、`systemctl restart logrotate.timer` 应用，
用 `systemctl list-timers logrotate.timer` 核对下次执行时间。
修改后先执行 `logrotate -d /etc/logrotate.conf` 检查规则，无需强制轮转。

`maxsize` 只在 logrotate 执行时检查！即使每分钟检查，也可能在一分钟内超过
20 MB，因此必须配合下述限频。压缩和数量限制不能保证严格的 100 MB 总容量。
参见 [logrotate 官方手册](https://github.com/logrotate/logrotate/blob/main/logrotate.8.in)。

### 3. 限制内核错误写入速率

若设备从 `imklog` 接收内核日志，可修改已有的模块加载语句，保留原有其他参数：

```text
module(load="imklog" permitnonkernelfacility="on"
       RatelimitInterval="5" RatelimitBurst="100")
```

这是建议起点：每 5 秒最多接收 100 条，超出的丢弃。
此限制影响该输入的所有内核消息，可能丢失其他故障证据；测试取证时应评估阈值。
不要重复加载 imklog。先用 `rsyslogd -N1` 检查版本和语法，再重启 rsyslog。
如果设备改用 `imjournal` 或 journal 转发路径，应配置实际输入的限频，
不能照搬 imklog 配置；journal 自身存储仍依靠第 1 项限制。
参见 [rsyslog imklog 官方文档](https://docs.rsyslog.com/doc/configuration/modules/imklog.html)。

驱动维护方还应对同一相机错误做源头限频和失败重试退避，保留首次报错及重复次数。
这样能减少日志产生及 CPU/I/O 开销，而不仅是减少落盘。上述系统配置不能修复相机故障。

### 4. 验收与存量处理

复测时观察 `kern.log`、`syslog` 的增长速度、轮转文件数和
`journalctl --disk-usage`；同时用 `df -h`、`df -i` 检查磁盘和 inode。
设置剩余空间低于 1 GB 的运维告警。若必须保证绝不挤占根分区，
可进一步规划独立日志分区或文件系统配额；达到配额后日志写入会失败。

轮转后仍可能有旧的大文件。先保存故障时间段、首条报错和退出前日志，
再由设备维护方清理明确的旧文件。不要直接清空整个 `/var/log`。
回退时恢复 rsyslog/logrotate 原配置及 timer，移除本次 journal 配置片段并重启服务；
限频已丢弃、轮转已淘汰的日志无法靠回退恢复。
