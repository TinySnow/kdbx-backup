# 为每位家人添加独立实例

每个实例（profile）跟踪一个主库文件，拥有独立的来源授权、配置、快照、SQLite 队列和 Docker Compose 项目。`family` 只是现有示例中一个人的实例名，并不代表把全家的数据库混在一起。

本文以 `brother` 为例：哥哥的 OneDrive 作为主库，Google Drive 和坚果云可以使用你的备份账号，并分别存入 `KDBX-Backups/brother/`。继续添加其他家人时，把实例名换为 `mother`、`father` 等，每人重复一遍。

| 内容 | 默认实例 | 哥哥的实例 |
| --- | --- | --- |
| 配置 | `config/config.json` | `profiles/brother/config/config.json` |
| 授权文件 | `.secrets/rclone/rclone.conf` | `profiles/brother/.secrets/rclone/rclone.conf` |
| 本地数据 | `<数据根目录>/default/` | `<数据根目录>/brother/` |
| Docker 项目 | `kdbx-backup` | `kdbx-backup-brother` |
| 云端备份目录 | 以实际 `targets` 为准 | 示例为 `KDBX-Backups/brother/` |

实例目录用于分开管理，不是不同操作系统用户之间的安全隔离。管理员能够读取服务的云盘授权文件；数据库仍由各自的主密码保护，备份服务不需要主密码。

## 1. 初始化实例

前提是已完成[基础部署](deploy-from-zero.md)，Docker 正在运行，共享网络已创建，`.env` 中的数据根目录已配置，`.tools/rclone` 已准备好。所有命令都在项目根目录执行。

任意命名实例使用宿主机 Python 3.9+ 管理工具，无第三方依赖；备份进程仍在 Docker 里运行。下文用 `python3`，Windows 可改为 `python`，原生 rclone 文件名改为 `.tools/rclone.exe`。

```sh
python3 scripts/manage.py init --profile brother
```

初始化创建独立目录，新配置默认 `enabled: false`。已有配置保留；不会自动复制任何账号授权。新命名实例的示例目标路径自动增加 `/brother`，但仍需检查是否符合实际目标。

实例名必须以小写字母开头，只含小写字母、数字、下划线或连字符，总长不超过 32 字符，并避开 Windows 保留名。每位家人使用唯一名字，不要共用一个 profile。

如前面已有人替你准备好 `brother` 的配置和两个备份目标授权，跳过重复初始化及复制，直接授权来源即可。

## 2. 决定备份到谁的账号

来源和目标独立选择：

- 主库 remote `onedrive`：必须登录哥哥的微软账号。
- 目标 remote `gdrive`、`jianguoyun`：可以登录你的账号，也可以登录哥哥自己的账号。
- 共用你的备份账号时，各人的 `targets` 使用不同子目录，例如 `/brother`、`/mother`。

两种配置方法任选一种。

### 方法 A：在新实例中分别授权三个连接

```sh
python3 scripts/manage.py configure --profile brother
```

管理工具只停止 `brother` 实例，打开其独立的 rclone 配置。在向导内用 `n` 新建连接：

| remote 名称 | 类型 | 登录哪个账号 |
| --- | --- | --- |
| `onedrive` | `onedrive` | 哥哥的微软账号 |
| `gdrive` | `drive` | 你决定用于备份的 Google 账号 |
| `jianguoyun` | `webdav` | 你决定用于备份的坚果云账号 |

即使与默认实例使用同一备份账号，也可以在这里重新授权。Google 需要真实 OAuth 客户端，见 [Google 授权指南](google-drive-oauth.md)；坚果云使用 `https://dav.jianguoyun.com/dav/`、vendor `other` 和第三方应用密码。只接入一个备份目标时，从后面的 JSON 中删除另一个目标。

### 方法 B：只复制自己的两个备份目标授权，再授权哥哥的 OneDrive

适用于默认实例已经配置好名为 `gdrive`、`jianguoyun` 的连接，且新实例要备份到完全相同的账号。只复制这两个连接，不复制默认实例的 `onedrive`。

先停止默认实例和哥哥实例，避免复制过程中发生 token 刷新写入：

```sh
docker compose stop backup
python3 scripts/manage.py stop --profile brother
```

以下为 macOS/Linux 的一次性复制示例，在项目根目录运行。仅适用于未设置 rclone 配置文件加密密码的普通配置；已有目标连接时会报错，不覆盖原授权。

```sh
python3 - <<'PY'
import configparser
import os
from pathlib import Path

source = Path('.secrets/rclone/rclone.conf')
destination = Path('profiles/brother/.secrets/rclone/rclone.conf')
names = {'gdrive': 'drive', 'jianguoyun': 'webdav'}
original = configparser.RawConfigParser()
with source.open(encoding='utf-8') as stream:
    original.read_file(stream)
if original.defaults():
    raise SystemExit('全局配置需要单独检查，请改用分别授权方式。')
for name, kind in names.items():
    if original.get(name, 'type', fallback=None) != kind:
        raise SystemExit('备份连接名称或类型不匹配，请改用分别授权方式。')
copied = configparser.RawConfigParser()
for name in names:
    copied.add_section(name)
    for key, value in original.items(name, raw=True):
        copied.set(name, key, value)
os.umask(0o077)
with destination.open('x', encoding='utf-8') as stream:
    copied.write(stream)
print('只复制了 gdrive、jianguoyun；还需授权哥哥的 OneDrive。')
PY
```

此示例要求目标授权文件尚不存在；若你已配置过来源或已准备好备份连接，不要删除现有文件来强行重跑，使用方法 A 补齐缺失连接即可。复制后的凭据分别存储和刷新，但复用的是原有服务商授权；撤销该授权可能影响两边。

恢复默认实例，再为哥哥配置来源：

```sh
docker compose up -d
python3 scripts/manage.py configure --profile brother
```

若复制步骤报错，也应先恢复默认实例，再排查错误或改用方法 A。不要在终端输出、聊天或 Git 中分享完整授权文件。

## 3. 授权哥哥的 OneDrive

无论采用哪种方法，都需要在 `brother` 的配置向导中创建 `onedrive`。如果已在方法 A 完成，则直接进入下一步。

| 提示 | 填写或选择 |
| --- | --- |
| 主菜单 | `n`，新建连接 |
| `name` | `onedrive` |
| `Storage` | `onedrive` |
| `client_id` / `client_secret` | 普通使用可留空，不是微软用户名或密码 |
| `region` | 普通个人微软账号用 `global`；`cn` 仅用于世纪互联中国版服务，与人在何处无关 |
| 高级配置 | 通常选 `n` |
| 本机浏览器自动授权 | 有浏览器的电脑选 `y` |
| 网盘类型 | 选择 OneDrive Personal or Business，再选实际保存主库的网盘 |

浏览器可能沿用你自己的微软登录；务必选择其他账户并登录哥哥的账号，确认后保存连接，最后输入 `q` 退出向导。官方流程见 [rclone OneDrive](https://rclone.org/onedrive/)。

无浏览器服务器可执行 `python3 scripts/manage.py configure --profile brother --headless`，询问浏览器时选 N，按[rclone 无界面授权说明](https://rclone.org/remote_setup/)在有浏览器的电脑上完成授权。

哥哥的主库若在其他云盘，参照[其他来源指南](source-storage.md)配置 `primary` 等连接，并相应修改 `source`，不需要额外配置 OneDrive。

## 4. 查找并确认哥哥的数据库

只列出根目录文件名及指定文件的元数据：

```sh
.tools/rclone --config profiles/brother/.secrets/rclone/rclone.conf lsf onedrive: --files-only --max-depth 1
.tools/rclone --config profiles/brother/.secrets/rclone/rclone.conf lsjson --stat 'onedrive:PASSWD.kdbx'
```

`PASSWD.kdbx` 只是示例，需替换成实际文件名。若在子目录，把路径改为如 `onedrive:密码库/PASSWD.kdbx`；不知道在哪个目录时，可以先用 `lsd onedrive:` 列出根目录的文件夹，再逐层检查。

确认是哥哥的文件，大小和修改时间符合预期，再启用备份。这些命令不解密数据库，也不打印密码条目。

## 5. 配置来源和独立目标目录

编辑 `profiles/brother/config/config.json`，保留已有其他参数，按实际文件路径修改：

```json
{
  "enabled": true,
  "source": "onedrive:PASSWD.kdbx",
  "poll_seconds": 60,
  "targets": [
    {"name": "google-drive", "path": "gdrive:KDBX-Backups/brother"},
    {"name": "jianguoyun", "path": "jianguoyun:KDBX-Backups/brother"}
  ]
}
```

remote 名称必须与哥哥实例的授权文件对应。推荐指定完整文件路径；`onedrive:` 自动发现要求根目录恰好只有一个 `.kdbx`。

初始化不会读取你当前实例的 `targets` 来自动复制自定义路径。若你的备份连接或目录与示例不同，要手动核对。已有自己的备份目录保持原样即可，无需为了添加哥哥而把它迁移到 `/me`。

## 6. 检查、启动和验收

```sh
python3 scripts/manage.py check --profile brother
python3 scripts/manage.py start --profile brother
python3 scripts/manage.py status --profile brother
```

`check` 只验证配置语法。`start` 使用 Docker 构建或复用构建缓存并启动独立服务，容器加入 `.env` 指定的共享网络；无需新建 `compose.brother.yaml`。

等待一个检查周期后再次查看状态。成功条件：`container_state` 为 `running`，`backup.healthy` 为 `true`，`backup.snapshots` 至少为 1，每个目标的 `pending` 为 0，且没有来源或目标错误。

需要日志时执行以下命令，按 Ctrl+C 退出日志查看，不会停止备份：

```sh
python3 scripts/manage.py logs --profile brother
```

分别到两个云盘的 `KDBX-Backups/brother/` 检查 `.kdbx` 及同名 `.sha256`，下载一份让哥哥用自己的密码管理器试开。快照文件使用 `vault_<UTC时间>_<哈希片段>_<随机标识>.kdbx` 命名，不沿用主库文件名；UTC 比北京时间少 8 小时。

测试变化时，等密码管理器把修改上传到主库云盘，再等服务器检查和备份完成。按默认 60 秒轮询，保存后不会立即出现新快照；旧历史应始终保留。

## 日常管理与继续添加家人

```sh
python3 scripts/manage.py profiles
python3 scripts/manage.py status --all
python3 scripts/manage.py restart --profile brother
python3 scripts/manage.py stop --profile brother
python3 scripts/manage.py start --profile brother
```

普通 JSON 修改后重启所选实例；修改 `.env` 或镜像后用 `start --profile brother` 重新应用容器配置。更换数据根目录需先停止所有实例并按[迁移指南](data-migration.md)搬运完整数据，不能只修改路径。

继续添加家人时，从 `init --profile mother` 开始，并使用自己的授权文件和 `/mother` 目标目录。`compose.family.yaml` 只管理名为 `family` 的实例，不会管理 `brother`、`mother`。宿主机不装 Python 时，现有固定 `family` 实例可直接按照[从零部署指南](deploy-from-zero.md)使用纯 Docker 流程；任意名字的实例目前使用本指南中的 Python 管理入口。
