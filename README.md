# KDBX Backup · 多云历史备份

为 `.kdbx` 密码库保存独立历史快照，并自动备份到 Google Drive、坚果云等 rclone 目标。主库可以放在 OneDrive、Google Drive、坚果云 WebDAV 等 rclone 支持的存储中；服务默认每分钟检查一次变化，上传后读回验证 SHA-256。无需主密码，不解密密码库。

部署文档：

- [从零部署指南](docs/deploy-from-zero.md)：以两个 OneDrive 账号为例，包含 Docker 初始化和首份备份验收。
- [为每位家人添加实例](docs/family-profiles.md)：以 `brother` 为例，说明独立授权、共用备份账号和日常管理。
- [使用其他云盘作为主库](docs/source-storage.md)：Google Drive、坚果云 WebDAV 等来源的配置与切换。
- [Google OAuth 指南](docs/google-drive-oauth.md)：创建客户端、授权和长期运行。

## 项目结构

```text
compose.yaml                  自己的实例，标准 Docker 启动入口
compose.family.yaml           名为 family 的单人实例示例
compose.init.yaml             一次性初始化
src/kdbx_backup/               备份服务源码
scripts/                      管理、初始化、路径配置及授权工具下载
  manage.py
  manage.sh / manage.ps1
  layout.py
  container_init.py
  bootstrap_rclone.py
deploy/Dockerfile             镜像构建配置
examples/config.example.json  公共配置示例
tests/                        单元及真实 rclone 集成测试
docs/                         部署、授权、发布与迁移说明
third_party/                  第三方许可证
```

根目录保留 Compose 入口、README、LICENSE、VERSION 和环境配置；源码、脚本与构建文件分目录存放。`compose.build.yaml` 已移除，源码构建直接使用标准 Compose 入口。

默认实例的实际配置和凭据分别位于 `config/config.json`、`.secrets/rclone/`；其他人的对应文件位于 `profiles/<实例名>/`。它们被 Git 忽略，也不会进入镜像构建上下文。一个实例跟踪一个主库文件；`family` 只是一个实例名，每位家人应分别创建 `brother`、`mother` 等实例。

## 数据目录由你配置

在项目根目录 `.env` 中设置统一的数据根目录：

```dotenv
KDBX_BACKUP_DATA_ROOT=/srv/homelab/data/kdbx-backup
TZ=Asia/Shanghai
KDBX_BACKUP_NETWORK=homelab
```

路径可以是绝对路径，也可以相对于项目根目录，例如本项目位于 `homelab/projects/kdbx-backup` 时：

```dotenv
KDBX_BACKUP_DATA_ROOT=../../data/kdbx-backup
```

包含空格时用引号。建议填写已经展开的路径，不要在路径值中再使用环境变量表达式。

各实例的数据自动分开：

```text
<数据根目录>/
├── default/
│   ├── snapshots/        独立 KDBX 历史及 SHA-256
│   ├── staging/          未发布的下载
│   ├── state.sqlite3     快照索引、上传进度及重试
│   └── status.json       运行状态
├── family/
└── 其他实例名/
```

未配置时，通用部署使用项目内被忽略的 `var/data/`。宿主机执行 `python scripts/manage.py init` 且未配置数据根目录时，会识别 `homelab/projects/` 布局，优先使用对应的 `homelab/data/kdbx-backup/`。纯 Docker 初始化始终以 `.env` 为准。

**修改路径不会自动搬运已有历史。** 已有备份必须先停止服务、完整复制并校验数据，再改配置启动；步骤见[数据迁移指南](docs/data-migration.md)。初始化检测到旧版 `data/` 中有数据库或快照时会报错，避免跳过旧历史启动一个空目录。

数据目录应使用支持硬链接、文件锁与 SQLite 的本地持久化文件系统。Windows 推荐 WSL2 Linux 文件系统；不要将运行数据放入 OneDrive、SMB/NFS 同步或共享目录。

## 直接用 Docker 部署

支持 `linux/amd64`、`linux/arm64`；宿主机使用 Linux、macOS 的 Docker 环境或 Windows Docker Desktop 的 Linux 容器模式。

首次部署先复制 `.env.example` 为 `.env` 并配置数据根目录。已有 `.env` 请直接编辑，保留镜像、UID/GID、时区和代理设置。

共享网络若尚不存在，先运行一次：

```sh
docker network create homelab
```

初始化并启动：

```sh
docker compose -f compose.init.yaml run --rm --build init
docker compose up -d --build
docker compose -f compose.family.yaml up -d --build
```

初始化在容器内完成，宿主机无需 Python。初始化容器通过独立 `/storage` 挂载创建外部数据目录，不要求容器内存在宿主机的绝对路径。备份容器均加入外部 `homelab` 网络，`down` 不会删除共享网络。初始化容器不联网。

初始化会保留已有配置、凭据和 UID/GID 设置；新配置默认 `enabled: false`。**启动容器后仍需授权网盘并启用 JSON 配置。** `waiting_config` / unhealthy 表示尚未启用备份。

容器默认直连，不继承宿主终端的 `HTTP_PROXY` 等变量。需要代理时，在 `.env` 显式设置 `KDBX_BACKUP_HTTPS_PROXY`、`KDBX_BACKUP_HTTP_PROXY`，地址应使用容器可访问的宿主地址，如 `http://host.docker.internal:7890`。不要将宿主机的 `127.0.0.1` 代理地址直接填入容器配置。

## 网盘授权与配置

先停止对应实例，再编辑各自的凭据，避免与 token 刷新同时写入：

```sh
docker compose stop backup
docker compose run --rm --entrypoint rclone backup config

docker compose -f compose.family.yaml stop backup
docker compose -f compose.family.yaml run --rm --entrypoint rclone backup config
```

容器内的浏览器自动授权选 N，按 [rclone 无界面授权流程](https://rclone.org/remote_setup/)操作。有浏览器的电脑也可以直接使用本机 rclone，凭据文件分别为 `.secrets/rclone/rclone.conf` 和 `profiles/family/.secrets/rclone/rclone.conf`。

| remote 名称 | 类型 | 设置 |
| --- | --- | --- |
| `onedrive` | `onedrive` | 各自的微软账号 |
| `gdrive` | `drive` | 自建 Google OAuth 桌面客户端，再登录备份 Google 账号 |
| `jianguoyun` | `webdav` | `https://dav.jianguoyun.com/dav/`，vendor `other`，坚果云第三方应用密码 |

Google 共享客户端正在退役，按 [Google OAuth 指南](docs/google-drive-oauth.md)创建真实 client ID / secret。

编辑对应实例的配置（默认实例为 `config/config.json`，其他实例为 `profiles/<实例名>/config/config.json`）：`source: "onedrive:"` 会在根目录寻找唯一 `.kdbx`；多个文件时应明确填写完整路径。`targets` 只保留已授权的目标，将 `enabled` 改为 `true`。新命名实例的示例目标自动增加实例名，分开每个人的云端历史。

remote 名称由你定义，不要求叫 `onedrive`。其他主库使用如 `primary:密码库/PASSWD.kdbx`，并在同一实例的凭据文件中配置 `primary`。初始化模板仍默认为 `onedrive:`，更换来源需手动修改；具体步骤见[主库配置指南](docs/source-storage.md)。

## 管理实例

日常使用 Docker：

```sh
docker compose ps
docker compose logs --tail 100 backup
docker compose exec -T backup python -m kdbx_backup.service status
docker compose restart

docker compose -f compose.family.yaml ps
docker compose -f compose.family.yaml exec -T backup python -m kdbx_backup.service status
```

可选管理工具需要宿主机 Python 3.9+，无第三方依赖：

```sh
python scripts/manage.py init --profile parents
python scripts/manage.py configure --profile parents
python scripts/manage.py start --profile parents
python scripts/manage.py status --all
python scripts/manage.py start --all
python scripts/manage.py stop --all
```

这些是管理命令，授权、启用配置和验收步骤见[家人实例指南](docs/family-profiles.md)。`compose.family.yaml` 固定管理 `family`，不会自动管理 `brother` 等其他实例；任意命名实例使用 `--profile <实例名>`。

macOS/Linux 可使用 `./scripts/manage.sh`；Windows 可用 `scripts/manage.ps1`。各实例共用镜像和宿主授权工具，各自拥有配置、凭据、数据及 Docker 项目名。全局 `.env` 共用数据根目录、镜像、网络、时区与代理。直接 Compose 与管理工具按同一个数据根目录解析挂载。

普通 JSON 修改后用 `restart`；修改 `.env`、镜像或 Compose 后用 `up -d` 重建容器配置。`healthy: true` 且快照数至少为 1、各目标 `pending: 0` 表示首份备份完成验证。状态超过 45 秒未更新会使健康检查失败。

## 已发布镜像

镜像需要先由维护者发布，以下地址为替换示例：

```dotenv
KDBX_BACKUP_IMAGE=ghcr.io/yourname/kdbx-backup:0.1.0
```

```sh
docker compose -f compose.init.yaml pull init
docker compose -f compose.init.yaml run --rm init
docker compose pull
docker compose up -d --no-build
docker compose -f compose.family.yaml up -d --no-build
```

发布工作流与验证范围见[维护者指南](docs/releasing.md)。

## 历史与恢复

下载目标 `.kdbx` 和同名 `.sha256`，可用 `python scripts/manage.py verify 文件路径` 校验，再用自己的密码管理器解锁检查。确认后先另存当前主库，再人工恢复到对应云盘的日常主库位置。

服务保存每次观察到的内容变化，只新增历史，不删除旧快照。两次轮询之间被覆盖的中间版本仍可能漏掉；严格保存每次客户端保存，需要配合客户端备份。文件头和哈希检查不能证明库可解锁，投入使用后应实际试开。程序没有云端 WORM / Object Lock 保证，也没有自动清理策略，需关注磁盘容量。主机睡眠或 Docker 未运行期间不采集。

## 测试

```sh
python scripts/manage.py test
python scripts/manage.py test-integration --platform linux/amd64
python scripts/manage.py test-integration --platform linux/arm64
```

测试仅使用合成文件和临时目录，不挂载真实凭据或生产数据。CI 包含三种宿主工具测试、双架构容器测试和纯 Docker 初始化验证。项目采用 [MIT 许可证](LICENSE)。
