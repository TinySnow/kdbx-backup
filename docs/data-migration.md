# 更改本地备份位置

你可以把服务器保存历史的位置从项目文件夹移到其他本地磁盘。已经有历史时，需要先复制完整数据，再修改设置。

只想在第一次部署时选择位置，可直接修改 `.env` 的 `KDBX_BACKUP_DATA_ROOT`，不需要执行迁移。

## 开始之前

安排一个可以暂停备份的时间，并确认新位置有足够空间。新旧位置应是两个互不包含的文件夹；新位置应为空。使用本地文件系统，不要使用云盘同步文件夹或 SMB/NFS 共享。

本页复制命令适用于 macOS、Linux 或 WSL2，并需要 `rsync`。检查 SQLite 使用 Python 3.9+。先记录哪些任务正在运行，迁移后只启动这些任务。

> **需要搬哪些东西？** 整个数据根目录，包括 `snapshots`、`state.sqlite3`、可能存在的 `-wal`、`-shm` 和状态文件。只复制 `.kdbx` 会丢失上传进度。项目里的配置和授权不在此次移动范围内，也应另外保管好。

## 1. 记录旧位置并停止任务

在项目文件夹打开 `.env`，记下当前 `KDBX_BACKUP_DATA_ROOT` 的实际绝对路径。相对路径从项目文件夹计算。

安装了管理工具时，列出并停止全部已初始化任务：

```sh
python3 scripts/manage.py profiles
python3 scripts/manage.py status --all
python3 scripts/manage.py stop --all
```

没有管理工具时，停止默认任务及所有正在运行的其他任务。例如：

```sh
docker compose stop backup
docker compose -f compose.family.yaml stop backup
```

**确认结果：** 本项目的所有备份容器已停止。复制期间不要启动它们。

把现有环境设置另存到已经存在的私密目录：

```sh
cp .env .secrets/env.before-data-move
```

## 2. 复制整个数据目录

以下两个路径是示例，**先替换为你的实际绝对路径**，再执行。最后的斜杠表示复制目录里的内容：

```sh
KDBX_OLD_ROOT="/srv/backup-old"
KDBX_NEW_ROOT="/srv/backup-new"
mkdir -p "$KDBX_NEW_ROOT"
rsync -a -- "$KDBX_OLD_ROOT/" "$KDBX_NEW_ROOT/"
```

如果提示权限不足，先检查旧目录的归属及当前运行用户，不要随意修改整块磁盘的权限。

## 3. 核对复制结果

先比较目录中的文件内容：

```sh
rsync -a --checksum --dry-run --itemize-changes -- "$KDBX_OLD_ROOT/" "$KDBX_NEW_ROOT/"
```

**确认结果：** 命令成功结束，且没有文件差异输出。如果列出差异，先处理并重新核对，不要继续切换位置。

再检查新目录中各任务的 SQLite 数据库：

```sh
python3 - "$KDBX_NEW_ROOT" <<'PY'
from pathlib import Path
import sqlite3
import sys

databases = list(Path(sys.argv[1]).glob('*/state.sqlite3'))
if not databases:
    raise SystemExit('没有找到数据库，请确认复制的是正确的数据根目录。')
for path in databases:
    with sqlite3.connect(str(path)) as database:
        result = database.execute('PRAGMA integrity_check').fetchall()
    if result != [('ok',)]:
        raise SystemExit('数据库检查失败：' + str(path))
    print(path.parent.name + ': ok')
PY
```

**确认结果：** 每个已经产生历史的任务显示 `ok`。尚未启用的任务可能没有 SQLite 文件。

## 4. 修改设置并启动

打开 `.env`，将 `KDBX_BACKUP_DATA_ROOT` 改为新位置，保留其他设置：

```dotenv
KDBX_BACKUP_DATA_ROOT=/srv/backup-new
```

把示例换成你的新路径，保存后启动原来运行的任务。例如默认任务和哥哥的任务：

```sh
docker compose up -d --build
python3 scripts/manage.py start --profile brother
```

如果之前使用 `family`，用 `docker compose -f compose.family.yaml up -d --build`。只有确实要启动所有已初始化任务时，才使用 `start --all`；初始化生成但尚未配置的任务也在其范围内。

## 5. 确认服务已使用新位置

检查默认任务的挂载：

```sh
docker compose ps -q backup
```

复制输出的容器 ID，执行 `docker inspect 容器ID`，在 Mounts 中检查目标 `/data` 的 Source 是否为新根目录下的 `default`。其他任务也分别检查。

再按[状态检查步骤](operations.md)确认历史数量保留、待上传进度正常。成功迁移不会因为位置变化重新产生相同内容的快照。

保留旧目录作为回退副本，直到确认新位置和两个云盘中的备份都正常。

## 切换后不能启动怎么办？

停止任务，将 `.env` 的路径改回保留完整数据的旧位置，再重新创建对应容器。保留新目录排查，不要删除唯一一份历史或授权。

如果你使用的是旧版项目内数据目录，复制时使用以下对应关系：

| 旧版目录 | 新数据根目录下的位置 |
| --- | --- |
| 项目中的 `data/` | `default/` |
| `profiles/family/data/` | `family/` |
| `profiles/brother/data/` | `brother/` |

这种旧版布局按每个任务分别复制到新根目录，再核对。初始化器发现旧目录里仍有历史时会要求先迁移，以免直接启用一个空目录。
