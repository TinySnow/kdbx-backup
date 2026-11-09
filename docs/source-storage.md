# 使用其他云盘作为主库

备份核心通过 rclone 读取文件，并不限定 OneDrive。初始化生成的 `source: "onedrive:"` 和从零部署指南使用 OneDrive 作为示例；使用其他来源时，需要配置对应 remote，并修改 `source`。后续的历史快照、独立上传重试及读回 SHA-256 校验相同。

本文假定已经按[从零部署指南](deploy-from-zero.md)准备好项目、Docker 镜像和授权工具。命令均在项目根目录执行；原生工具示例使用 macOS/Linux 的 `.tools/rclone`，Windows 改为 `.tools/rclone.exe`，`python3` 改为 `python`。

## 主库、remote 和备份目标

- `source`：日常密码管理器编辑的那一个 `.kdbx` 文件，服务只读取。
- remote：rclone 中一个存储连接的名字，决定存储类型及账号，例如 `primary`。
- `targets`：保存独立历史快照的位置，可以有多个。它们与主库分别配置账号。

`primary`、`onedrive`、`gdrive` 都是自定义名字；名字本身不能决定云盘类型。同一凭据文件中，来源和目标若使用同一种云盘的不同账号，应建立不同名称的 remote，例如 `primary` 和 `gdrive`。

每个实例只跟踪一个主库文件；同一账号的多个数据库也应分别使用多个实例，步骤见[家人实例指南](family-profiles.md)。

## 1. 配置来源连接

默认实例先停止服务，再打开自己的授权文件：

```sh
docker compose stop backup
.tools/rclone --config .secrets/rclone/rclone.conf config
```

如果操作的是 `brother` 实例，改为：

```sh
python3 scripts/manage.py configure --profile brother
```

管理工具需要宿主机 Python 3.9+，会先停止所选实例，再使用其独立的凭据文件。没有浏览器时使用 `configure --profile brother --headless`，并按 [rclone 无界面授权流程](https://rclone.org/remote_setup/)完成授权；镜像必须能从本地构建，或使用项目支持的已发布镜像部署方式。

在向导中选择 `n`，新建名为 `primary` 的 remote，按实际存储选择类型：

| 主库位置 | rclone 类型 | 授权要点 | `source` 示例 |
| --- | --- | --- | --- |
| OneDrive | `onedrive` | 登录主库所属微软账号；普通个人账号选 `global`，世纪互联中国版选 `cn` | `primary:PASSWD.kdbx` |
| Google Drive | `drive` | 使用自己的 Google OAuth 客户端，登录主库所属 Google 账号 | `primary:密码库/PASSWD.kdbx` |
| 坚果云 | `webdav` | URL 为 `https://dav.jianguoyun.com/dav/`，vendor 为 `other`，使用第三方应用密码 | `primary:密码库/PASSWD.kdbx` |
| Dropbox | `dropbox` | 按向导通过浏览器授权主库所属账号 | `primary:密码库/PASSWD.kdbx` |

Google Drive 的客户端创建和长期授权设置见 [Google OAuth 指南](google-drive-oauth.md)。不要因为来源改为 Google Drive，就沿用备份账号的 remote 去读取另一个人的主库。

支持范围以当前镜像内 rclone 版本及服务商开放接口为准，不能将“支持 rclone”理解为所有网盘都可直接接入。例如夸克等未提供相应标准连接方式的网盘，需要另行验证集成，本文不提供其可用性保证。

## 2. 核对路径和账号

仅列出主库所在目录的文件，不读取密码内容。默认实例示例：

```sh
.tools/rclone --config .secrets/rclone/rclone.conf lsf 'primary:密码库/' --files-only --max-depth 1
.tools/rclone --config .secrets/rclone/rclone.conf lsjson --stat 'primary:密码库/PASSWD.kdbx'
```

其他实例将 `--config` 的参数改为 `profiles/<实例名>/.secrets/rclone/rclone.conf`。确认文件名、大小和最近修改时间符合预期。

推荐填写完整文件路径。目录自动发现仅在 `source` 以 `:` 或 `/` 结尾时启用，例如 `primary:` 或 `primary:密码库/`；该目录第一层必须恰好有一个 `.kdbx`，不会递归寻找，也不会自动挑选最新或最大的文件。

自动发现成功后，服务在本次运行中继续跟踪该文件路径。若主库改名或换目录，需要修改配置并重启；如果只是同一路径的文件被替换，后续检查会重新读取该路径。不要依赖自动发现来处理多个冲突副本。

## 3. 修改配置并启动

编辑默认实例的 `config/config.json`，或命名实例的 `profiles/<实例名>/config/config.json`。例如 Google Drive 主库，备份到另一个 Google Drive 连接和坚果云：

```json
{
  "enabled": true,
  "source": "primary:密码库/PASSWD.kdbx",
  "poll_seconds": 60,
  "targets": [
    {"name": "google-drive", "path": "gdrive:KDBX-Backups/brother"},
    {"name": "jianguoyun", "path": "jianguoyun:KDBX-Backups/brother"}
  ]
}
```

这份示例中 `primary`、`gdrive`、`jianguoyun` 必须都存在于该实例的凭据文件中。目标不必包含 Google Drive；只保留实际已配置的目标即可。若来源和备份使用同一云盘账号，要将快照放在主库目录以外的独立目录；同一账号内的副本也不能抵御该账号整体不可访问。

默认实例检查并启动：

```sh
docker compose run --rm --no-deps backup check-config
docker compose up -d --build
docker compose exec -T backup python -m kdbx_backup.service status
```

`brother` 实例对应命令：

```sh
python3 scripts/manage.py check --profile brother
python3 scripts/manage.py start --profile brother
python3 scripts/manage.py status --profile brother
```

语法检查不验证云端账号和权限。等待一个检查周期后，确认 `healthy: true`、`snapshots` 至少为 1、每个目标 `pending: 0`，并实际下载试开一份快照。

## 已有实例迁移主库

先停止该实例，在新云盘上传并确认准备使用的数据库，配置新的来源 remote，再将 `source` 改为新文件路径。保留该实例原有数据目录及目标目录，然后启动并验收。

不要为了换主库而删除本地快照、SQLite 或上传队列。服务按内容 SHA-256 判断是否生成新快照：新来源与上一份内容相同会跳过，内容不同则新增一份，旧历史继续保留。改动其他备份目标的路径会触发向新目录补传本地历史，因此只迁移来源时应保留 `targets`。

## 官方连接说明

- [rclone OneDrive](https://rclone.org/onedrive/)
- [rclone Google Drive](https://rclone.org/drive/)
- [rclone WebDAV](https://rclone.org/webdav/)
- [坚果云第三方应用授权](https://help.jianguoyun.com/?p=2064)
- [rclone Dropbox](https://rclone.org/dropbox/)
