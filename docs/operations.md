# 查看状态和解决常见问题

使用本页确认备份是否完成，以及查找保存后没有新版本的原因。所有终端命令都在项目文件夹执行。

## 查看自己的备份状态

```sh
docker compose ps
docker compose exec -T backup python -m kdbx_backup.service status
```

第一条确认容器有没有运行，第二条显示备份进度。如果第二条提示服务未运行，先执行：

```sh
docker compose up -d --build
```

再查看一次状态。

## 查看家人的备份状态

例如查看哥哥的任务：

```sh
python3 scripts/manage.py status --profile brother
```

将 `brother` 换成实际实例名。查看有哪些任务以及所有任务的状态：

```sh
python3 scripts/manage.py profiles
python3 scripts/manage.py status --all
```

管理工具需要 Python 3.9+；Windows 原生终端将 `python3` 换成 `python`。

## 怎样判断已经成功？

找到状态输出中的以下字段。使用管理工具时，它们在 `backup` 下面。

| 字段 | 你希望看到什么 | 含义 |
| --- | --- | --- |
| `mode` | `running` | 已进入备份流程 |
| `healthy` | `true` | 当前没有报告健康异常 |
| `snapshots` | 至少 `1` | 本地已有历史版本 |
| 每个目标的 `pending` | `0` | 这个云盘没有尚未完成的上传 |
| `source_error` | `null` | 当前没有来源读取错误 |
| `target_errors` | `{}` | 当前没有目标上传错误 |

**确认首份备份成功，需要同时看快照数量和每个目标的 `pending`。** 刚产生新历史时，健康状态可能仍为正常，但上传尚未结束。

最后到目标云盘下载一份数据库试开。哈希一致证明上传内容一致，不能代替解锁和核对条目。

## 保存以后，为什么没有立刻出现新文件？

按以下顺序检查：

1. 确认密码管理器已把修改上传到主库云盘。Mac 或 iPad 的本地保存可能还没有完成云端上传。
2. 等一两分钟。服务默认每 60 秒检查一次，还需要下载、上传和校验时间。
3. 查看状态。如果 `snapshots` 已增加，但 `pending` 还大于零，说明正在上传或等待重试。
4. 在目标云盘打开配置中 `targets` 指定的文件夹，不一定是云盘根目录。
5. 找 `vault_` 开头的文件。历史不沿用 `PASSWD.kdbx` 的名称，时间使用 UTC，比北京时间少 8 小时。

文件内容与上一份历史完全相同时，不会再生成一份。两次检查之间多次覆盖的中间版本，也可能没有被服务读到。

## 查看错误日志

自己的任务：

```sh
docker compose logs --tail 100 backup
```

哥哥的任务：

```sh
python3 scripts/manage.py logs --profile brother
```

哥哥的命令会继续显示新日志，按 Ctrl+C 只退出查看，不停止备份。

| 日志或状态提示 | 接下来怎么做 |
| --- | --- |
| `waiting_config` | 检查对应 JSON 是否为 `enabled: true`，确认连接配置齐全后重启任务 |
| `capture_failed` | 检查主库账号、文件路径和网络；先用本机 rclone 确认能列出该文件 |
| `source changed during capture` | 读取期间文件被更新，服务会放弃该次读取并在下一轮重试。偶尔出现可稍后再查 |
| `delivery_failed` | 检查报错目标的授权、空间、目录和网络；另一目标仍可独立上传 |
| `source directory must contain exactly one .kdbx` | 目录有多个数据库或没有数据库。把 `source` 改成正确文件的完整路径 |
| `local archive missing or corrupted` | 保留数据目录，检查磁盘及历史文件；不要通过删除 SQLite 或唯一历史来消除报错 |
| `rclone operation failed` | 这是概括错误，不能仅凭它判断授权过期。先分别检查账号、路径和网络 |

`snapshot_saved` 表示本地保存成功；`snapshot_verified target=...` 表示该目标完成了上传和校验。

## 主库被删除、替换或重命名后怎么办？

删除主库不会让服务删除已保存的历史。先确认你准备保留哪个文件，再检查其完整路径。

- **在相同路径替换文件：** 服务下一轮会读取该路径；内容变化时新增历史。
- **文件改名或移动了：** 修改对应 JSON 的 `source`，再重启任务。
- **出现两个冲突副本：** 先分别保存副本，在密码管理器中比较内容，再决定主库。文件大小和条目总数都不能证明全部字段相同。

需要找回旧版本时，按[恢复步骤](restore.md)操作。

## 修改设置后，运行哪个命令？

| 你修改了什么 | 默认任务 | 哥哥的任务 |
| --- | --- | --- |
| `config.json` | `docker compose restart backup` | `python3 scripts/manage.py restart --profile brother` |
| `.env`、镜像或 Compose | `docker compose up -d --build` | `python3 scripts/manage.py start --profile brother` |
| 云盘授权 | 先停止任务，再编辑它的授权文件，完成后启动 | `configure --profile brother` 会先停止；授权完成仍需 `start --profile brother` |

修改本地历史位置需要先[搬运数据](data-migration.md)，不能只修改 `.env`。

## Docker 网络或代理报错

如果提示 `homelab` 网络不存在，先执行 `docker network inspect homelab` 确认。确实不存在时运行一次：

```sh
docker network create homelab
```

再启动任务。它是共享的外部网络，项目不会自动创建它，停止备份也不需要删除它。

容器默认直连，不继承终端中的普通代理变量。需要宿主机代理时，在 `.env` 使用 `KDBX_BACKUP_HTTPS_PROXY` 等设置，参考[代理配置](configuration.md#网络和代理)。容器里的 `127.0.0.1` 指向容器自身，不能用来访问宿主机代理。

## 在没有浏览器的服务器上授权

默认任务在服务器运行：

```sh
docker compose stop backup
docker compose run --rm --no-deps --entrypoint rclone backup config
```

哥哥的任务在服务器运行：

```sh
python3 scripts/manage.py configure --profile brother --headless
```

然后：

1. 正常填写连接信息；询问是否自动打开浏览器时选 **N**。
2. 在另一台有浏览器的电脑准备相同版本的 rclone。
3. 在那台电脑执行向导显示的完整 `rclone authorize ...` 命令，登录正确账号。
4. 将返回结果粘贴回服务器的 `config_token` 提示处，确认保存。
5. 退出向导，启动对应备份任务，再检查状态。

使用本项目工具时，把命令开头的 `rclone` 换成 `.tools/rclone`，保留其余参数。授权结果可能包含敏感信息，只在你自己的终端之间传递。

详细流程见 [rclone 官方说明](https://rclone.org/remote_setup/)。
