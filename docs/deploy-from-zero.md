# 设置第一份备份

按照本指南，将 OneDrive 中的一个密码数据库备份到 Google Drive 和坚果云。完成后，你可以在两个云盘中找到带时间的历史版本。

自己的备份已经运行时，直接阅读[为家人设置备份](family-profiles.md)。主库在其他云盘时，先完成第 1 至 3 步，再按[选择主库所在的云盘](source-storage.md)连接来源。

## 开始之前

准备以下内容：

- 一台保持运行的电脑，已安装并启动 Docker。Mac 可用 OrbStack 或 Docker Desktop；Windows 使用 Docker Desktop 的 Linux 容器模式。
- 已安装 Git。若使用本项目的私有副本，还需要具有仓库访问权限的 Git 账号。
- 一个能正常打开的 `.kdbx` 文件，并知道它在 OneDrive 里的位置。
- 用于备份的 Google 和坚果云账号。先只用一个目标也可以。
- Python 3.9 或更高版本。本指南用它下载本机授权工具；长期运行的备份进程仍在 Docker 中。

以下命令用于 macOS、Linux 或 Windows 的 WSL2 终端。Windows 建议把项目放在 WSL2 的 Linux 文件系统中。原生 PowerShell 将 `python3` 改为 `python`，`.tools/rclone` 改为 `.tools/rclone.exe`，复制文件使用 `Copy-Item`。

> **不想在服务器安装 Python？** 可以手动安装 [rclone](https://rclone.org/install/)，用 `rclone` 替换下文的 `.tools/rclone`，跳过下载工具的命令。初始化和备份都可直接使用 Docker。无浏览器服务器见[授权说明](operations.md#在没有浏览器的服务器上授权)。

## 1. 取得项目并检查 Docker

在终端进入你想存放项目的文件夹，运行：

```sh
git clone https://github.com/TinySnow/kdbx-backup.git
cd kdbx-backup
docker version
docker compose version
```

**确认结果：** `docker version` 同时显示 Client 和 Server 信息。只显示 Client 或提示无法连接时，先启动 Docker 应用。

后面的命令都在这个 `kdbx-backup` 文件夹里执行。如果重新打开了终端，先回到该文件夹。

## 2. 选择服务器保存历史的位置

第一次设置、项目里还没有 `.env` 文件时，运行：

```sh
cp .env.example .env
```

用文本编辑器打开 `.env`，找到并修改下面两行：

```dotenv
KDBX_BACKUP_DATA_ROOT=./var/data
TZ=Asia/Shanghai
```

`./var/data` 表示保存在项目里的 `var/data` 文件夹。如果项目或部署目录位于 `homelab/projects/kdbx-backup` 或 `homelab/services/kdbx-backup`，希望历史存到 `homelab/data/kdbx-backup`，将第一行改成：

```dotenv
KDBX_BACKUP_DATA_ROOT=../../data/kdbx-backup
```

选择其中一个位置，保存文件。不要把这个运行目录放进 OneDrive 同步文件夹或网络共享盘。

> **已有 `.env`？** 直接编辑现有文件，不要用示例覆盖它。已有备份历史时，换位置请使用[迁移步骤](data-migration.md)。

## 3. 创建所需目录并准备授权工具

先检查 Docker 网络：

```sh
docker network inspect homelab
```

如果提示网络不存在，运行一次：

```sh
docker network create homelab
```

然后初始化项目并下载本机授权工具：

```sh
docker compose -f compose.init.yaml run --rm --build init
python3 scripts/manage.py bootstrap
.tools/rclone version
```

首次初始化需要下载基础镜像和构建，可能花费几分钟。工具下载会核对官方 SHA-256。

**确认结果：** 初始化成功退出，工具显示版本号。项目中出现 `config/config.json` 和 `.secrets/rclone/` 文件夹。初始化也会准备一个叫 `family` 的示例配置，此时不需要启动它。

## 4. 连接自己的 OneDrive

运行以下命令。第一条只停止自己的备份服务；首次部署时还没有运行中的备份：

```sh
docker compose stop backup
.tools/rclone --config .secrets/rclone/rclone.conf config
```

这是 rclone 的连接向导。它把一个云盘连接称为 **remote**。按提示填写：

| 终端显示的提示 | 输入或选择 |
| --- | --- |
| 主菜单 `n) New remote` | `n` |
| `name` | `onedrive` |
| `Storage` | `onedrive` |
| `client_id` | 直接回车 |
| `client_secret` | 直接回车；这里不填微软账号密码 |
| `region` | 普通个人账号选 `global`；世纪互联中国版服务才选 `cn` |
| `Edit advanced config?` | `n` |
| `Use web browser to automatically authenticate...` | 本机有浏览器时选 `y` |

浏览器打开后登录自己的微软账号并同意授权。回到终端，选择 **OneDrive Personal or Business**，再选择实际保存密码库的网盘。确认保存后输入 `q` 退出。

**确认结果：** 下面的命令应能列出根目录里的文件名：

```sh
.tools/rclone --config .secrets/rclone/rclone.conf lsf onedrive: --files-only --max-depth 1
```

数据库在子文件夹时，检查对应目录，例如：

```sh
.tools/rclone --config .secrets/rclone/rclone.conf lsf 'onedrive:密码库/' --files-only --max-depth 1
```

记下正确路径，例如 `onedrive:PASSWD.kdbx` 或 `onedrive:密码库/PASSWD.kdbx`。

## 5. 连接两个备份云盘

### 连接 Google Drive

按[连接 Google Drive](google-drive-oauth.md)创建 Google OAuth 客户端，并在本实例的授权文件中建立名为 `gdrive` 的连接。完成后回到这里继续。

### 连接坚果云

1. 登录坚果云网页，在账户设置的安全选项中添加第三方应用，取得应用密码。入口见[坚果云说明](https://help.jianguoyun.com/?p=2064)。
2. 再次打开连接向导：

   ```sh
   .tools/rclone --config .secrets/rclone/rclone.conf config
   ```

3. 输入 `n` 新建连接，按下表填写。

| 提示 | 填写内容 |
| --- | --- |
| `name` | `jianguoyun` |
| `Storage` | `webdav` |
| `url` | `https://dav.jianguoyun.com/dav/` |
| `vendor` | `other` |
| `user` | 坚果云登录账号 |
| `password` / `pass` | 选择输入自己的密码，填写第三方应用密码 |
| 高级配置 | 通常选 `n` |

确认保存，输入 `q` 退出，然后检查两个连接：

```sh
.tools/rclone --config .secrets/rclone/rclone.conf lsd gdrive:
.tools/rclone --config .secrets/rclone/rclone.conf lsd jianguoyun:
```

**确认结果：** 两条命令正常结束。空云盘可能没有目录输出，这不代表失败。

只使用一个备份云盘时，跳过另一个连接，在下一步删除对应的目标配置。

## 6. 告诉服务备份哪个文件

用文本编辑器打开 `config/config.json`。首次设置可使用下面的完整内容；已有配置时只修改对应字段：

```json
{
  "enabled": true,
  "source": "onedrive:PASSWD.kdbx",
  "poll_seconds": 60,
  "targets": [
    {"name": "google-drive", "path": "gdrive:KDBX-Backups/me"},
    {"name": "jianguoyun", "path": "jianguoyun:KDBX-Backups/me"}
  ]
}
```

这里有三处需要确认：

- `source`：换成第 4 步找到的完整路径，不要照抄不存在的文件名。
- `targets`：只保留已经连接的云盘。`KDBX-Backups/me` 是保存新历史的目标目录。
- `enabled`：设为 `true`，表示允许开始备份。

JSON 使用英文双引号，最后一个目标后面不能加逗号。保存文件后运行：

```sh
docker compose run --rm --no-deps backup check-config
```

**确认结果：** 显示 `Configuration syntax OK`。这一步只检查写法，还没有开始上传。

## 7. 开始备份

```sh
docker compose up -d --build
```

命令结束后，服务会在后台继续运行，可以关闭终端。等待一两分钟，再运行：

```sh
docker compose exec -T backup python -m kdbx_backup.service status
```

**确认结果：** `healthy` 为 `true`、`snapshots` 至少为 `1`，并且两个目标各自的 `pending` 都为 `0`。还没完成时稍后再查；持续报错时看[常见问题](operations.md)。

## 8. 打开第一份备份

在 Google Drive 和坚果云网页中分别打开 `KDBX-Backups/me`。你应看到一份以 `vault_` 开头的 `.kdbx`，以及同名的 `.kdbx.sha256` 文件。

下载其中一份 `.kdbx`，用密码管理器作为另一份数据库打开，确认能解锁、条目符合预期。不要把下载的历史副本设成日常自动填充的主库。

第一份备份设置完成后，可以[给家人添加备份](family-profiles.md)，或了解[怎样查看新版本](operations.md)。
