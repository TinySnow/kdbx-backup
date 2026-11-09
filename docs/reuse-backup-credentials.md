# 复用已有的备份云盘连接

如果哥哥的历史要放进你正在使用的 Google Drive 和坚果云，可以把这两个备份连接复制到哥哥的配置中，省去再次登录。

这是可选的高级操作。更熟悉登录向导时，直接按[家人设置的第 3 步](family-profiles.md#3-连接你的两个备份云盘)分别授权即可。

## 开始之前

本页只复制默认任务的 `gdrive` 和 `jianguoyun`，保留哥哥已有的 `onedrive`。不会复制你的 OneDrive 来源。

确认以下条件：

- 已执行 `python3 scripts/manage.py init --profile brother`。
- 默认任务的两个备份连接分别叫 `gdrive`、`jianguoyun`，类型是 `drive`、`webdav`。
- 哥哥的配置里还没有这两个目标连接。若已准备好，跳过本页。
- 授权文件没有额外设置 rclone 配置加密密码；否则改用登录向导。
- 使用 macOS、Linux 或 WSL2 终端，并有 Python 3.9+。

复制后，两份文件分别保存和刷新授权，但仍复用服务商发放的原有授权。撤销它可能影响两个任务。

## 1. 暂停两个任务

在项目文件夹运行：

```sh
docker compose stop backup
python3 scripts/manage.py stop --profile brother
```

这避免复制时恰好发生授权令牌刷新。你的任务稍后会恢复。

## 2. 复制两个目标连接

将下面整段复制到同一个终端运行。脚本不会输出密钥；发现已有目标连接时会停止，不会覆盖。

```sh
python3 - <<'PY'
import configparser
import os
from pathlib import Path
import tempfile

source = Path('.secrets/rclone/rclone.conf')
destination = Path('profiles/brother/.secrets/rclone/rclone.conf')
if source.is_symlink() or destination.is_symlink():
    raise SystemExit('不处理链接文件，请使用连接向导。')
original = configparser.RawConfigParser()
with source.open(encoding='utf-8') as stream:
    original.read_file(stream)
current = configparser.RawConfigParser()
if destination.exists():
    with destination.open(encoding='utf-8') as stream:
        current.read_file(stream)
if original.defaults() or current.defaults():
    raise SystemExit('有全局配置，请使用连接向导。')
for name, kind in {'gdrive': 'drive', 'jianguoyun': 'webdav'}.items():
    if original.get(name, 'type', fallback=None) != kind:
        raise SystemExit('默认任务的目标名称或类型不匹配。')
    if current.has_section(name):
        raise SystemExit('目标连接已存在；不复制，请检查现有连接。')
for name in ('gdrive', 'jianguoyun'):
    current.add_section(name)
    for key, value in original.items(name, raw=True):
        current.set(name, key, value)
os.umask(0o077)
descriptor, temporary = tempfile.mkstemp(dir=destination.parent, prefix='.reuse-')
try:
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        current.write(stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, destination)
finally:
    Path(temporary).unlink(missing_ok=True)
print('两个备份连接已复制；哥哥原有的来源连接已保留。')
PY
```

**确认结果：** 显示“两个备份连接已复制”。若报错，不要删除现有授权文件来强行重跑；先按下一步恢复自己的任务，再用向导补齐连接。

## 3. 恢复自己的任务并检查哥哥的连接

无论上一步是否成功，都先恢复自己的备份：

```sh
docker compose up -d
```

复制成功后检查哥哥的两个目标：

```sh
.tools/rclone --config profiles/brother/.secrets/rclone/rclone.conf lsd gdrive:
.tools/rclone --config profiles/brother/.secrets/rclone/rclone.conf lsd jianguoyun:
```

两条命令正常结束后，回到[家人设置的第 4 步](family-profiles.md#4-设置文件路径和备份文件夹)，配置来源和独立目标目录。如果哥哥的 OneDrive 尚未授权，先完成该指南的第 2 步。

本页没有自动启动哥哥的任务，仍需完成配置、启动和首份备份检查。
