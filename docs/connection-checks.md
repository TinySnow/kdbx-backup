# 自动检查云盘连接与查看日志

即使密码库几个月没有变化，备份目标也需要被实际访问，才能让 rclone 在需要时刷新授权，并及早发现网络、目录或账号权限问题。

服务默认在启动时检查每个目标，成功后每 24 小时再次检查。每份实例各自执行，不需要另建 cron 或其他定时任务。

## 你需要设置什么？

**已有配置不需要修改。** 新版本默认启用检查。检查间隔由 `target_check_seconds` 控制，默认 `86400` 秒。

更新代码并重建容器即可。默认任务在项目目录运行：

```sh
docker compose up -d --build
```

家人的任务运行：

```sh
python3 scripts/manage.py start --profile brother
python3 scripts/manage.py start --profile father
```

只重启旧容器不会换成新程序；源码更新后需要重新构建或拉取已发布的新镜像。

## 检查会访问什么？

服务读取 `targets` 中每个备份文件夹的元数据，使用 `rclone lsjson --stat`。这一检查不上传测试文件、不改动主库，也不删除历史。

- 启动服务后立即检查一次，重启后也会立即检查。
- 成功后等待 24 小时；这是间隔计时，不是每天固定在零点执行。
- 失败后从 `retry_seconds` 开始重试，连续失败时延长等待，最长一小时。
- 每个目标有独立的工作线程；一个目标失败不会停止另一目标或来源采集。
- 新建目标文件夹尚不存在时，首次检查可能失败。正常的首次上传创建目录后，服务会立即重新检查。

读取目录成功表示该目录当前可访问。真实上传仍会另外执行读回校验，完成后才减少 `pending`。

## 怎样确认检查正在运行？

等启动检查完成后查看状态：

```sh
docker compose exec -T backup python -m kdbx_backup.service status
```

家人的任务使用 `python3 scripts/manage.py status --profile brother`，将实例名换成实际名字。

每个目标下新增 `connection_check`。以下是状态中的一部分：

```json
{
  "connection_check": {
    "last_attempt": 1794229200,
    "last_success": 1794229200,
    "next_check": 1794315600,
    "failures": 0,
    "error": null,
    "state": "ok"
  }
}
```

| 字段 | 怎样理解 |
| --- | --- |
| `state: ok` | 最近检查成功，且仍在有效检查时间内 |
| `state: pending` | 还没有成功检查记录，等待首次检查 |
| `state: error` | 最近检查失败，正在等待重试 |
| `state: stale` | 超过检查间隔和健康宽限，仍没有成功记录 |
| `last_attempt` | 最近一次检查完成的时间 |
| `last_success` | 最近一次检查成功的时间 |
| `next_check` | 下一次计划检查或重试的时间 |
| `failures` | 连续失败次数，成功后归零 |
| `error` | 最近检查的概括错误；成功后为 `null` |

时间字段是 Unix 时间戳。想直接阅读本地时区的日期和时间，可以查看文件日志。

检查失败、尚未完成首次检查或长期未完成，会影响 `healthy`；失败和超时信息也会出现在 `target_errors`。一次成功的目录检查不会消除尚未解决的上传错误。

检查摘要保存在该实例的 `state.sqlite3`，状态写到 `status.json`。这些记录随原有数据目录持久化，升级不清空历史和上传队列。

## 日志文件在哪里？

每个实例的数据目录中都会自动创建 `logs/service.log`：

```text
数据根目录/
├── default/logs/service.log
├── brother/logs/service.log
└── father/logs/service.log
```

数据根目录就是 `.env` 中的 `KDBX_BACKUP_DATA_ROOT`。日志同时输出到 Docker，仍可使用原来的 `docker compose logs` 或管理工具的 `logs` 命令。

在默认容器内查看文件日志：

```sh
docker compose exec -T backup tail -n 50 /data/logs/service.log
```

也可以直接在宿主机打开相应文件。每个文件约 5 MiB 后轮转，保留 `service.log.1`、`service.log.2`、`service.log.3` 三份旧日志，总大小约 20 MiB；日志文件权限为 `0600`。

例如：

```text
2026-11-09 21:00:00 INFO target_check_ok target=google-drive
2026-11-09 21:00:01 ERROR target_check_failed target=jianguoyun reason=rclone operation timed out
```

`target_check_ok` 表示目录连接检查成功。`target_check_failed` 不一定是授权过期，也可能是网络、路径或目录权限问题。服务不记录云盘密码、授权令牌、服务商原始错误响应或数据库内容。

## 检查失败后怎么办？

1. 在日志中确认哪个目标失败。
2. 检查该目标的网络和目录路径，使用同一实例的 rclone 配置验证连接。
3. 确实是授权问题时，停止该实例后重新授权。Google 的方法见[连接 Google Drive](google-drive-oauth.md)。
4. 重新启动实例，确认 `connection_check.state` 恢复为 `ok`，并检查所有目标的 `pending` 为 `0`。

失败会反映到文件日志、状态和 Docker 健康检查；本功能没有新增邮件或消息推送。

## 这能保证授权永远有效吗？

定期访问减少长期闲置，也使失效更早被发现。它不能恢复已撤销的权限，不能绕过 Google Testing 的 7 天限制，也不能替你重新登录账号。

OneDrive 长时间闲置、Google 刷新令牌 6 个月未使用、令牌数量限制或账号策略变化等，仍需按服务商规则处理。长期运行的 Google 应用应配置为 Production。

依据：[rclone OneDrive 限制](https://rclone.org/onedrive/#limitations)、[Google 刷新令牌失效条件](https://developers.google.com/identity/protocols/oauth2#expiration)。
