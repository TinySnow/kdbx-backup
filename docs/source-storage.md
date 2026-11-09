# 选择主库所在的云盘

你的密码库可以放在 OneDrive、Google Drive、坚果云 WebDAV 或其他 rclone 支持的存储中。选择哪种主库，不会改变保存历史和上传校验的方式。

本指南以 **Google Drive 中的 `密码库/PASSWD.kdbx`** 为例。你将连接这个账号，并告诉备份服务到哪里读取文件。

## 开始之前

先完成[首次设置](deploy-from-zero.md)的第 1 至 3 步。如果正在更换一个已运行任务的主库，先另存当前数据库，并停止该任务。

以下命令在项目文件夹执行。默认任务使用 `.secrets/rclone/rclone.conf`；哥哥的任务使用 `profiles/brother/.secrets/rclone/rclone.conf`。Windows 原生终端使用 `.tools/rclone.exe`，Python 命令使用 `python`。

## 1. 为主库创建一个连接

默认任务运行：

```sh
docker compose stop backup
.tools/rclone --config .secrets/rclone/rclone.conf config
```

如果操作的是哥哥的任务，改用：

```sh
python3 scripts/manage.py configure --profile brother
```

在向导中选择 `n`，将新连接命名为 `primary`。再根据主库所在的云盘选择类型：

| 主库所在云盘 | 在 Storage 输入 | 授权方式 |
| --- | --- | --- |
| Google Drive | `drive` | 使用 Google OAuth 客户端，再登录主库所属 Google 账号 |
| OneDrive | `onedrive` | 通过浏览器登录主库所属微软账号 |
| 坚果云 | `webdav` | 填写 WebDAV 地址、账号和第三方应用密码 |
| Dropbox | `dropbox` | 按向导打开浏览器并授权 |

Google 的详细填写步骤见[连接 Google Drive](google-drive-oauth.md)。本例连接名称使用 `primary`，将该指南中的 `name: gdrive` 改为 `name: primary` 即可。坚果云的填写方法见[连接坚果云](deploy-from-zero.md#连接坚果云)。

**确认结果：** 保存并退出向导后，连接列表中应有 `primary`：

```sh
.tools/rclone --config .secrets/rclone/rclone.conf listremotes
```

操作哥哥任务时，以上命令的授权文件路径也换成哥哥的路径。`primary` 是你给连接起的名字，它所使用的云盘和账号由刚才的授权决定。

## 2. 找到数据库的完整路径

检查本例中的文件夹：

```sh
.tools/rclone --config .secrets/rclone/rclone.conf lsf 'primary:密码库/' --files-only --max-depth 1
```

**确认结果：** 列表中有 `PASSWD.kdbx`。文件在根目录时，把 `primary:密码库/` 改成 `primary:`。

路径写法可以这样理解：

```text
primary:密码库/PASSWD.kdbx
└连接名 └── 云盘内的文件路径 ──┘
```

这里填写云盘里的路径，不是浏览器网址，也不是 Mac 上的同步文件夹路径。

## 3. 连接备份云盘

按照[首次设置的第 5 步](deploy-from-zero.md#5-连接两个备份云盘)连接 Google Drive 和坚果云，或只连接其中一个。

主库与备份属于不同 Google 账号时，要建立两个连接。例如：

| 名称 | 登录账号 | 用途 |
| --- | --- | --- |
| `primary` | 保存日常数据库的 Google 账号 | 读取主库 |
| `gdrive` | 用于保存备份的 Google 账号 | 写入历史 |
| `jianguoyun` | 用于保存备份的坚果云账号 | 写入历史 |

即使两个 Google 连接的类型都叫 `drive`，账号也可以不同。

## 4. 修改 source 并启用

默认任务编辑 `config/config.json`；哥哥的任务编辑 `profiles/brother/config/config.json`。

把 `source` 设为第 2 步确认的完整路径，将 `enabled` 设为 `true`。以下是默认任务的完整示例：

```json
{
  "enabled": true,
  "source": "primary:密码库/PASSWD.kdbx",
  "poll_seconds": 60,
  "targets": [
    {"name": "google-drive", "path": "gdrive:KDBX-Backups/me"},
    {"name": "jianguoyun", "path": "jianguoyun:KDBX-Backups/me"}
  ]
}
```

哥哥的任务将目标目录末尾改为 `/brother`。已有任务只修改 `source` 和需要调整的字段，保留原目标路径。

## 5. 开始备份

默认任务运行：

```sh
docker compose run --rm --no-deps backup check-config
docker compose up -d --build
```

哥哥的任务运行：

```sh
python3 scripts/manage.py check --profile brother
python3 scripts/manage.py start --profile brother
```

等一两分钟后，按[状态检查步骤](operations.md)确认各目标待上传数为零，再下载一份历史数据库试开。

## 更换已有任务的主库时

保留该任务原有的本地历史目录和 `targets`，只连接新来源并修改 `source`。新文件内容与上一份快照相同，服务会跳过；内容不同，会新增历史。原有历史不会被清空。

如果同时修改目标目录，服务会把本地已有历史补传到新目标。仅更换主库时，无需移动备份文件夹。

## 找不到文件或出现多个数据库时

优先填写完整文件路径。只有 `source` 以 `:` 或 `/` 结尾时才会自动寻找文件，例如 `primary:`、`primary:密码库/`。

自动寻找仅检查该目录第一层，要求恰好有一个 `.kdbx`。服务不会递归搜索，也不会按大小或时间选文件。找到后，本次运行会继续读取这个路径；改名或换目录后，需要修改配置并重启。

## 其他云盘能用吗？

先确认当前镜像内的 rclone 支持该存储，再验证连接、列出文件和实际备份。支持 rclone 不代表所有网盘都能直接接入；没有可用标准接口的网盘需要另行适配。

官方连接说明：[OneDrive](https://rclone.org/onedrive/)、[Google Drive](https://rclone.org/drive/)、[WebDAV](https://rclone.org/webdav/)、[Dropbox](https://rclone.org/dropbox/)。
