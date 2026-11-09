# 从零部署：以两个 OneDrive 账号为例

目标：自己的密码库与家人的密码库分别保留在各自的 OneDrive，服务器按默认 60 秒周期检查，为读到的每次内容变化保存独立历史，再分别上传到 Google Drive、坚果云。两个人使用独立容器、授权、历史和队列。

以下以当前项目的源码部署方式为准。镜像尚未对外发布，无需填写示例 GHCR 地址。日常运行通过 Docker Compose，宿主机无需安装 Python。本文在有浏览器的电脑上使用原生 rclone 完成首次授权。

本文的 `family` 是第二个人的实例名，不是全家共用的分组。已部署好自己的服务、现在要给哥哥等其他家人添加实例，可直接看[为每位家人添加独立实例](family-profiles.md)，无需重做基础部署。主库不在 OneDrive 时，按[其他主库云盘指南](source-storage.md)替换来源授权和 `source`，其余部署与验收流程相同。

## 1. 准备环境和项目

安装并启动 Docker / OrbStack，取得本项目源码，进入项目目录：

```sh
cd kdbx-backup
docker version
docker compose version
```

macOS 可使用 OrbStack 或 Docker Desktop。Windows 使用 Docker Desktop 的 Linux 容器模式，建议把项目放在 WSL2 的 Linux 文件系统中。Linux 使用 Docker Engine 和 Compose v2。

各端密码管理器继续使用 OneDrive 上的主库，备份目标的历史文件不作为日常编辑入口。

## 2. 网络、初始化和镜像

先检查共享网络：

```sh
docker network inspect homelab
```

只有显示网络不存在时才创建：

```sh
docker network create homelab
```

先编辑项目根目录 `.env` 的 `KDBX_BACKUP_DATA_ROOT`，例如 `/srv/homelab/data/kdbx-backup`；项目在 `homelab/projects/kdbx-backup` 时也可以填写 `../../data/kdbx-backup`。不指定时通用部署使用 `var/data/`。已有历史迁移前必须先阅读[迁移步骤](data-migration.md)，不要只改路径。

初始化会构建镜像，在配置的数据根目录下创建 `default/` 和 `family/`，同时保留已有配置和凭据：

```sh
docker compose -f compose.init.yaml run --rm --build init
```

检查 `.env` 中的时区和网络设置，可按需使用：

```dotenv
TZ=Asia/Shanghai
KDBX_BACKUP_NETWORK=homelab
```

初始化写入的 UID/GID 保持原值即可；不要用 `.env.example` 覆盖整个现有 `.env`。需要容器代理时参考 `.env.example`，填写容器能够访问的代理地址。

## 3. 准备浏览器授权工具

项目的 Mac 部署已经准备好 `.tools/rclone`。新电脑可从 [rclone 官方版本目录](https://downloads.rclone.org/v1.75.2/) 下载匹配系统和架构的 1.75.2 二进制，与官方 SHA256SUMS 核对后解压，将可执行文件放进项目的 `.tools/`。Windows 文件名为 `rclone.exe`，下文相应替换即可。

macOS / Linux 检查工具：

```sh
chmod +x .tools/rclone
.tools/rclone version
```

这是首次浏览器登录用的工具，长期备份进程运行在 Docker 中。官方说明见 [rclone 安装文档](https://rclone.org/install/)。

## 4. 授权自己的三个网盘连接

配置凭据之前先停止自己的服务：

```sh
docker compose stop backup
.tools/rclone --config .secrets/rclone/rclone.conf config
```

在同一配置向导内，用 `n` 新建三个 remote。remote 名称必须与后面的 JSON 配置一致：

| 名称 | 类型 | 用途 |
| --- | --- | --- |
| `onedrive` | `onedrive` | 登录自己的微软账号，读取根目录密码库 |
| `gdrive` | `drive` | 登录备份目标 Google 账号 |
| `jianguoyun` | `webdav` | 使用坚果云账号与第三方应用密码 |

OneDrive：一般将 client ID / client secret 留空，它们不是微软账号密码。区域普通个人账号选 `global`，世纪互联中国版服务才选 `cn`，与使用者所在地区无关。询问高级配置时选 N，询问是否通过浏览器自动授权时选 Y。浏览器登录自己的微软账号，回到终端选择实际保存密码库的 OneDrive。参考 [rclone OneDrive 配置](https://rclone.org/onedrive/)。

Google Drive：先按[Google Drive OAuth 配置说明](google-drive-oauth.md)创建自己的桌面客户端，填写 Google 签发的 client ID / secret；不要填应用名称、账号密码等自定义字符串。类型使用 `drive`，当前配置的 scope 为 `drive`，再通过浏览器登录。个人盘通常将 root folder ID 留空，共享盘选 N；组织共享盘按实际设置。rclone 的共享 Google 客户端正在退役，长期备份应使用自己的客户端。参考 [rclone Google Drive 配置](https://rclone.org/drive/)。

坚果云：在其账号设置中生成独立的第三方应用密码。WebDAV URL 为 `https://dav.jianguoyun.com/dav/`，vendor 为 `other`，用户名为坚果云账号，密码使用第三方应用密码。参考 [坚果云官方授权说明](https://help.jianguoyun.com/?p=2064)。

每个 remote 完成后确认保存，最终用 `q` 退出。不需要将主密码、授权 token、应用密码或完整配置发送到聊天里。

## 5. 单独授权家人的账号

```sh
docker compose -f compose.family.yaml stop backup
.tools/rclone --config profiles/family/.secrets/rclone/rclone.conf config
```

同样创建 `onedrive`、`gdrive`、`jianguoyun` 三个 remote。家人的 `onedrive` 必须切换到家人的微软账号，避免浏览器自动沿用自己的登录。两个实例可使用相同 remote 名称，因为凭据文件分开保存。

Google Drive / 坚果云可以使用家人自己的账号，也可以使用你的备份账号；每套配置中都要有对应目标连接，后面用不同目录区分两个人的历史。共用你的账号时，可以在此重新授权，也可以仅复制两个目标连接，具体步骤见[家人实例指南中的授权方法](family-profiles.md#方法-b只复制自己的两个备份目标授权再授权哥哥的-onedrive)。不要整份复制自己的授权文件，否则会把自己的 OneDrive 来源一起带过去。若只使用一个备份目标，只创建该目标，并从 JSON 的 `targets` 中删除另一个目标。

需要第三位、第四位家人时，使用 `init --profile brother`、`init --profile mother` 等独立实例，按[完整步骤](family-profiles.md)逐人配置；`compose.family.yaml` 始终只操作名为 `family` 的那一个实例。

## 6. 确认两个实例能读到正确主库

只列出根目录的 KDBX 文件名：

```sh
docker compose run --rm --entrypoint rclone backup lsf onedrive: --files-only --max-depth 1 --include '*.kdbx'
docker compose -f compose.family.yaml run --rm --entrypoint rclone backup lsf onedrive: --files-only --max-depth 1 --include '*.kdbx'
```

第一条应列出自己的密码库，第二条应列出家人的密码库。这不会解密或打印密码内容。如果报错或看不到目标文件，先纠正授权账号或路径，再启用服务。

## 7. 启用备份配置

自己的 `config/config.json` 可以使用以下完整最小配置，未列出的参数使用程序默认值：

```json
{
  "enabled": true,
  "source": "onedrive:",
  "poll_seconds": 60,
  "targets": [
    {"name": "google-drive", "path": "gdrive:KDBX-Backups/me"},
    {"name": "jianguoyun", "path": "jianguoyun:KDBX-Backups/me"}
  ]
}
```

家人的 `profiles/family/config/config.json`：

```json
{
  "enabled": true,
  "source": "onedrive:",
  "poll_seconds": 60,
  "targets": [
    {"name": "google-drive", "path": "gdrive:KDBX-Backups/family"},
    {"name": "jianguoyun", "path": "jianguoyun:KDBX-Backups/family"}
  ]
}
```

`onedrive:` 表示在根目录自动寻找唯一的 `.kdbx`。若有多个，改为完整路径，例如 `onedrive:passwords.kdbx`；两个人的文件名可以不同。只保留已授权目标。默认单文件上限 32 MiB，大型密码库可在配置中调整 `max_file_bytes`。

上面的 `/me`、`/family` 是新部署示例。已有服务应保留现有目标路径；添加家人无需移动你自己的历史。新实例初始化使用示例模板，仍需核对目标账号与路径，不会自动继承默认实例的自定义配置。

检查配置语法：

```sh
docker compose run --rm backup check-config
docker compose -f compose.family.yaml run --rm backup check-config
```

显示 `Configuration syntax OK` 才继续；语法检查不验证网盘授权。

## 8. 启动两个服务

```sh
docker compose up -d --build
docker compose -f compose.family.yaml up -d --build
```

等待一个检查周期后查看，较慢网络可能需要更久：

```sh
docker compose logs --tail 100 backup
docker compose -f compose.family.yaml logs --tail 100 backup
docker compose exec -T backup python -m kdbx_backup.service status
docker compose -f compose.family.yaml exec -T backup python -m kdbx_backup.service status
```

验收条件：状态 `mode` 为 `running`、`healthy` 为 `true`、`snapshots` 至少 1，所有目标的 `pending` 为 0，且没有 `source_error` 或 `target_errors`。日志应出现 `snapshot_saved` 与各目标的 `snapshot_verified`。

`waiting_config` 表示还没启用配置；持续出现 `capture_failed` 应检查源账号与路径，`delivery_failed` 应检查对应备份目标的授权、目录和网络。

## 9. 验证新版本与恢复

到两个备份网盘检查 `KDBX-Backups/me/` 和 `KDBX-Backups/family/`，应有独立 `.kdbx` 文件及同名 `.sha256`。先下载一份副本，用各自的密码管理器解锁，确认内容正确。

测试新增版本可以修改一个测试条目的备注并保存，等待 OneDrive 上传及服务器下一次检查，再确认云端多出一个快照，旧快照仍保留。恢复备注后保存也可能产生新版本。

若在 Mac 的同一目录下载了 `.kdbx` 与 `.sha256`，可在该目录运行：

```sh
shasum -a 256 -c 实际文件名.kdbx.sha256
```

应显示 `OK`。校验成功后仍需试开密码库。恢复时先另存当前主库，再人工将选定快照恢复到 OneDrive 的日常主库位置。

## 10. 日常管理

查看状态使用第 8 步的命令；重启或停止只操作对应实例：

```sh
docker compose restart
docker compose -f compose.family.yaml restart
docker compose stop
docker compose -f compose.family.yaml stop
```

修改普通 JSON 配置后用 `restart`。修改 `.env`、镜像或 Compose 后用 `up -d` 让 Compose 重新创建受影响的容器。

两套凭据和配置仍位于 `.secrets/`、`config/`、`profiles/family/`；快照、SQLite 和运行状态位于 `KDBX_BACKUP_DATA_ROOT` 指定根目录下的 `default/`、`family/`。容器重建会保留它们。迁移时先停两套服务，再完整复制两人的配置、凭据和实际数据目录。

默认每分钟检查只能保存读取到的版本，可能漏掉两次检查之间被覆盖的中间版本。历史默认长期保留，需要自行关注磁盘容量。Mac 与 Docker 应保持运行，按需求设置自启与睡眠策略。

## 没有浏览器的服务器

服务器可直接运行容器内的配置向导：

```sh
docker compose stop backup
docker compose run --rm --entrypoint rclone backup config
```

家人实例用对应的 `-f compose.family.yaml` 命令。容器内询问浏览器自动授权时选 N，在另一台有浏览器的电脑上执行向导打印的完整 `rclone authorize ...` 命令，再将结果粘贴回服务器的 `config_token`。使用本项目 `.tools/rclone` 时只替换命令开头的 `rclone`，保留后面的所有参数。参考 [rclone 官方无界面授权流程](https://rclone.org/remote_setup/)。
