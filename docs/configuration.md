# 配置参考

本页用于查询文件位置、配置字段和高级选项。第一次设置时，请先按[设置第一份备份](deploy-from-zero.md)操作。

## 找到要编辑的文件

| 内容 | 默认任务 | 哥哥的任务 |
| --- | --- | --- |
| 备份设置 | `config/config.json` | `profiles/brother/config/config.json` |
| 云盘连接和授权 | `.secrets/rclone/rclone.conf` | `profiles/brother/.secrets/rclone/rclone.conf` |
| 本地历史和运行状态 | 数据根目录下的 `default/` | 数据根目录下的 `brother/` |
| Docker 项目名 | `kdbx-backup` | `kdbx-backup-brother` |

所有任务共用项目根目录的 `.env`，包括镜像、数据根目录、网络、时区和代理。一个实例对应一个数据库；一个微软账号里的多个数据库，也应分别建立任务。

授权文件含有访问云盘所需的凭据。拥有服务器文件访问权限的管理员可读取它；实例目录用于分开管理，不提供不同操作系统用户之间的访问隔离。

## config.json 字段

完整默认示例在 `examples/config.example.json`。实际配置至少需要 `enabled`、`source` 和 `targets`。

| 字段 | 默认值或要求 | 用途 |
| --- | --- | --- |
| `enabled` | 必须为 `true` 或 `false` | 是否启用备份；初始化为 `false` |
| `source` | 必填字符串 | 要读取的主库路径，例如 `onedrive:PASSWD.kdbx` |
| `targets` | 必填，1 至 8 个目标 | 每个目标有 `name` 和 `path` |
| `poll_seconds` | `60` | 两次来源检查之间等待的秒数 |
| `settle_seconds` | `3` | 读取前等待文件稳定的秒数 |
| `command_timeout_seconds` | `120` | 单次 rclone 命令允许的最长时间 |
| `max_file_bytes` | `33554432`，即 32 MiB | 允许备份的最大单文件大小 |
| `retry_seconds` | `60` | 上传失败后的基础重试等待时间；失败继续累积时逐步延长，最长一小时 |
| `health_grace_seconds` | `900` | 来源长时间未成功或上传积压时的健康判断宽限 |

`settle_seconds` 可以为零，其余数值字段必须是正整数。目标名称只允许字母、数字、下划线和连字符，最长 64 字符；同一配置内名称和目标路径不能重复。

### source 的路径写法

```text
onedrive:PASSWD.kdbx           根目录里的文件
onedrive:密码库/PASSWD.kdbx    子文件夹里的文件
primary:密码库/PASSWD.kdbx     名为 primary 的连接里的文件
```

冒号前是 rclone 连接名。连接类型和账号在该任务的授权文件里配置，不由名字决定。

路径以 `:` 或 `/` 结尾时，服务会在该目录第一层自动寻找唯一的 `.kdbx`。有零个或多个时会报错。建议直接指定完整文件路径。

### targets 的路径写法

```json
{
  "name": "google-drive",
  "path": "gdrive:KDBX-Backups/brother"
}
```

`name` 是显示在状态和日志中的标签。`path` 是云盘连接名和保存历史的文件夹。添加新目标或改为新的目标路径后，服务会补传本地保留的历史。

## 本地数据位置

在 `.env` 设置：

```dotenv
KDBX_BACKUP_DATA_ROOT=../../data/kdbx-backup
```

这个相对路径适用于项目位于 `homelab/projects/kdbx-backup` 的情况。也可填写绝对路径，例如 `/srv/homelab/data/kdbx-backup`；含空格时加英文引号。填写实际路径，不要在值里继续使用环境变量表达式。

各任务自动在根目录下使用自己的子目录：

```text
数据根目录/
├── default/
│   ├── snapshots/       KDBX 历史和 SHA-256 校验文件
│   ├── staging/         尚未完成的下载
│   ├── state.sqlite3    历史索引和上传进度
│   └── status.json      当前状态
└── brother/
```

没有配置时，通用部署使用项目内的 `var/data/`。宿主机首次运行管理工具的初始化命令时，如果识别到 `homelab/projects/` 布局，会优先选择对应的 `homelab/data/kdbx-backup/`。纯 Docker 初始化使用 `.env` 中的位置，不自动识别宿主机布局。

实际修改位置前，先按[迁移指南](data-migration.md)搬运完整目录。本地文件系统需要支持硬链接、文件锁和 SQLite；Windows 建议使用 WSL2 的 Linux 文件系统。

## 网络和代理

```dotenv
KDBX_BACKUP_NETWORK=homelab
TZ=Asia/Shanghai
```

网络必须已存在；项目不会自动创建它。备份容器共用这个外部网络，初始化容器不联网。`TZ` 影响日志时区；快照文件名始终使用 UTC。

容器默认直连。如果需要访问宿主机代理，可在 `.env` 添加：

```dotenv
KDBX_BACKUP_HTTP_PROXY=http://host.docker.internal:7890
KDBX_BACKUP_HTTPS_PROXY=http://host.docker.internal:7890
KDBX_BACKUP_NO_PROXY=localhost,127.0.0.1
```

将地址和端口改成自己的代理设置，并确保代理允许容器访问。可选的 `KDBX_BACKUP_ALL_PROXY` 用于其他代理协议。服务不会直接继承终端的 `HTTP_PROXY`、`HTTPS_PROXY` 或 `ALL_PROXY`。

## 容器用户和镜像

初始化会记录 `KDBX_BACKUP_UID`、`KDBX_BACKUP_GID`。已有值会保留；仅在理解宿主机目录权限时修改它们。

默认从源码构建 `homelab/kdbx-backup:local`。只有维护者确实发布了镜像后，才能在 `KDBX_BACKUP_IMAGE` 填写该镜像地址；填写不存在的 GHCR 地址不会自动发布镜像。

`KDBX_BACKUP_CONFIG_DIR`、`KDBX_BACKUP_PROFILE`、`KDBX_BACKUP_RCLONE_DIR` 用于管理工具为所选实例指定挂载。一般不在共享 `.env` 手动设置这些值。

## 只用 Docker 管理 family 示例

初始化已准备好名为 `family` 的单人任务，不需要宿主机 Python。按下面顺序连接、编辑、检查和启动：

1. 停止该任务并打开它的连接向导：

   ```sh
   docker compose -f compose.family.yaml stop backup
   docker compose -f compose.family.yaml run --rm --no-deps --entrypoint rclone backup config
   ```

2. 按[家人设置指南](family-profiles.md)创建来源和目标连接。容器内浏览器授权选 N，使用[无浏览器授权方法](operations.md#在没有浏览器的服务器上授权)。
3. 编辑 `profiles/family/config/config.json`，填写来源、`KDBX-Backups/family` 等独立目标路径，并设置 `enabled: true`。
4. 检查并启动：

   ```sh
   docker compose -f compose.family.yaml run --rm --no-deps backup check-config
   docker compose -f compose.family.yaml up -d --build
   docker compose -f compose.family.yaml exec -T backup python -m kdbx_backup.service status
   ```

`compose.family.yaml` 只管理 `family`。创建 `brother`、`mother` 等任意名字的任务，目前使用[Python 管理入口](family-profiles.md)。

## 项目文件布局

```text
compose.yaml                  默认任务
compose.family.yaml           family 示例任务
compose.init.yaml             一次性创建目录和初始配置
src/kdbx_backup/               备份服务
scripts/                      管理和初始化工具
deploy/Dockerfile             镜像构建文件
examples/config.example.json  初始配置模板
tests/                        测试
docs/                         使用说明
third_party/                  第三方许可证
```

实际授权、`config/config.json`、`profiles/`、`.env` 和历史文件已被 Git 忽略。镜像构建仅包含运行源码及许可证。
