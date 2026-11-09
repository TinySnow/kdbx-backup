# 为家人设置备份

自己的备份运行后，可以再给每位家人创建独立任务。本指南以哥哥为例：从哥哥的 OneDrive 读取密码库，把历史放进你的 Google Drive 和坚果云。

完成后，两个云盘中都会有 `KDBX-Backups/brother` 文件夹。哥哥的历史和你的历史分开保存。

## 开始之前

确认自己的备份已经按[首次设置指南](deploy-from-zero.md)运行，并准备好哥哥的微软账号授权。你不需要知道他的数据库主密码。

以下命令在项目文件夹执行，使用 Python 3.9+ 和项目的 `.tools/rclone`。Windows 原生 PowerShell 将 `python3` 换成 `python`，工具名换成 `.tools/rclone.exe`。

这里把哥哥的任务命名为 `brother`。添加其他家人时，换成 `mother`、`father` 等独立名字，再重复本指南。一个任务备份一个数据库。

> **已经准备过 `brother`？** 保留现有文件。初始化可以重复运行；连接已经存在时，直接补齐尚未授权的连接。

## 1. 创建哥哥的任务

```sh
python3 scripts/manage.py init --profile brother
```

`--profile brother` 表示只操作哥哥的任务，后面的管理命令都要保留这个参数。

**确认结果：** 终端显示已初始化 `brother`，项目中出现 `profiles/brother/config/config.json`。它还没有启用，不会立即开始备份。

## 2. 连接哥哥的 OneDrive

```sh
python3 scripts/manage.py configure --profile brother
```

这会停止哥哥的任务并打开他的连接向导，不影响你自己的任务。按提示填写：

| 提示 | 选择或填写 |
| --- | --- |
| 主菜单 | `n`，新建连接 |
| `name` | `onedrive` |
| `Storage` | `onedrive` |
| `client_id`、`client_secret` | 直接回车，不填微软账号密码 |
| `region` | 普通个人账号选 `global`；世纪互联中国版服务才选 `cn` |
| 高级配置 | 通常选 `n` |
| 浏览器自动授权 | 本机有浏览器时选 `y` |

浏览器打开后，选择“使用其他账户”，登录**哥哥的微软账号**。不要沿用你自己的登录。

回到终端，选择 **OneDrive Personal or Business**，选中他的网盘并确认保存。输入 `q` 退出。

**确认结果：** 以下命令能列出哥哥 OneDrive 根目录的文件：

```sh
.tools/rclone --config profiles/brother/.secrets/rclone/rclone.conf lsf onedrive: --files-only --max-depth 1
```

没看到数据库时，先检查账号。文件在子文件夹时，检查该目录，例如：

```sh
.tools/rclone --config profiles/brother/.secrets/rclone/rclone.conf lsf 'onedrive:密码库/' --files-only --max-depth 1
```

记下完整路径，例如 `onedrive:PASSWD.kdbx`。

## 3. 连接你的两个备份云盘

再次打开哥哥的连接向导：

```sh
python3 scripts/manage.py configure --profile brother
```

在这份配置中添加以下连接。已有对应连接时跳过：

| 连接名称 | 类型 | 登录哪个账号 |
| --- | --- | --- |
| `gdrive` | `drive` | **你的 Google 账号** |
| `jianguoyun` | `webdav` | **你的坚果云账号** |

Google 的填写步骤见[连接 Google Drive](google-drive-oauth.md)，其中的配置文件选用 `profiles/brother/.secrets/rclone/rclone.conf`。坚果云的填写方法见[首次设置指南](deploy-from-zero.md#连接坚果云)。

两个目标用你的账号，只会决定历史放在哪个云盘，不会改变第 2 步已连接的哥哥 OneDrive。

> **不想再授权两个备份账号？** 可以[复用已有备份连接](reuse-backup-credentials.md)。这是可选的高级操作；普通设置按本步骤分别登录即可。

退出向导后检查：

```sh
.tools/rclone --config profiles/brother/.secrets/rclone/rclone.conf lsd gdrive:
.tools/rclone --config profiles/brother/.secrets/rclone/rclone.conf lsd jianguoyun:
```

**确认结果：** 两条命令正常结束。空云盘没有目录输出也可以。

## 4. 设置文件路径和备份文件夹

用文本编辑器打开 **`profiles/brother/config/config.json`**。根目录的 `config/config.json` 是你自己的任务，这一步不修改它。

首次设置可使用以下内容：

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

将 `source` 换成哥哥实际的文件路径。保留两个目标末尾的 `/brother`，历史就会进入他的文件夹。只连接了一个目标时，删除另一个目标那一行，并调整逗号。

已有额外设置时，只修改这些字段，不必替换整个文件。你自己的备份目录保持原样，无需移动历史。

## 5. 开始备份并检查结果

```sh
python3 scripts/manage.py check --profile brother
python3 scripts/manage.py start --profile brother
```

第一条应显示 `Configuration syntax OK`。第二条构建并启动哥哥的 Docker 容器。等一两分钟后检查：

```sh
python3 scripts/manage.py status --profile brother
```

**确认结果：** `container_state` 为 `running`；`backup` 下的 `healthy` 为 `true`、`snapshots` 至少为 `1`，两个目标的 `pending` 都为 `0`。

在你的两个云盘网页中打开 `KDBX-Backups/brother`，应看到以 `vault_` 开头的历史文件。下载一份，让哥哥用他的密码管理器试开，确认条目正确。

## 以后怎样管理？

查看哥哥的状态：

```sh
python3 scripts/manage.py status --profile brother
```

更改哥哥的 JSON 配置后，重新启动他的任务：

```sh
python3 scripts/manage.py restart --profile brother
```

其他操作和报错说明见[查看状态和解决常见问题](operations.md)。

## 关于 family 和账号的常见问题

**为什么不用 `compose.family.yaml`？** 这个文件只管理名为 `family` 的单个任务。`brother` 使用 `--profile brother` 管理，不需要再写一个 Compose 文件。没有宿主机 Python 时，可用现有固定 `family` 示例，见[配置参考](configuration.md#只用-docker-管理-family-示例)。

**一定要放在我的云盘吗？** 不需要。第 3 步登录谁的 Google、坚果云账号，历史就进入谁的云盘。登录家人的账号时，其他步骤相同。

**不同家人能用相同的 remote 名称吗？** 可以。每个人的授权文件不同，`onedrive` 这个名字分别指向各自登录的账号。

**家人的主库不在 OneDrive 怎么办？** 按[选择主库所在的云盘](source-storage.md)连接来源，并修改该家人的 `source`。
