# 配置与迁移数据目录

配置、凭据仍由各实例保存在项目的 `config/`、`.secrets/` 或 `profiles/<name>/`。备份历史、SQLite 上传队列、临时下载和运行状态统一放在可配置的数据根目录中。

## 配置路径

在根目录 `.env` 中设置 `KDBX_BACKUP_DATA_ROOT`。绝对路径或相对于项目根目录的路径均可，含空格时加引号：

```dotenv
KDBX_BACKUP_DATA_ROOT=/srv/homelab/data/kdbx-backup
```

若项目位于 `homelab/projects/kdbx-backup`，可以用 `../../data/kdbx-backup`。实例自动使用 `default/`、`family/` 等子目录，直接 Compose 与管理脚本遵守同一配置。环境中显式设置的值优先于 `.env`；不要在路径值里使用 `${HOME}` 等额外插值表达式，请填写实际路径。

没有配置时，通用部署使用 `var/data/`。宿主脚本初次初始化可识别 `homelab/projects/`，优先写入对应的 homelab 数据根路径。纯 Docker 应先编辑 `.env`，再执行初始化命令。

## 迁移已有历史

**修改 `.env` 不会自动搬运数据。** 迁移必须停止实例，避免复制写入中的 SQLite 和下载中的文件。

下文以 `default`、`family` 两套实例为例。另有 `brother`、`mother` 等命名实例时，也必须逐个停止、复制并重建，不能遗漏；安装了管理工具可先用 `python3 scripts/manage.py profiles` 列出实例，再用 `python3 scripts/manage.py stop --all` 停止全部，迁移后用 `python3 scripts/manage.py start --all` 重建并启动。

1. 记录当前配置和挂载，停止两个实例：

   ```sh
   docker compose stop backup
   docker compose -f compose.family.yaml stop backup
   ```

2. 将每个实例的整个旧数据目录复制到新根目录下的同名子目录，保留权限。旧版布局对应如下：

   | 旧路径 | 新路径 |
   | --- | --- |
   | `data/` | `<新根目录>/default/` |
   | `profiles/family/data/` | `<新根目录>/family/` |

   新版更换根目录时，同样逐个复制 `<旧根目录>/<实例名>/`。不要只复制 `.kdbx`：`state.sqlite3` 和可能存在的 `-wal`、`-shm` 文件也需要完整保留，才能继续上传队列并记住已完成的备份。

3. 核对复制前后的相对文件清单、大小和 SHA-256；对复制后的 SQLite 执行 `PRAGMA integrity_check`，应返回 `ok`。文件内容不需要解密。
4. 校验通过后，把旧目录另外归档，保留回退副本。旧版项目目录中的 `data/` 有数据库或快照时，新的初始化器会要求先完成迁移，防止忽略旧历史。
5. 将 `.env` 的 `KDBX_BACKUP_DATA_ROOT` 改为新根路径。
6. 重新创建容器：

   ```sh
   docker compose up -d --build
   docker compose -f compose.family.yaml up -d --build
   ```

7. 用 `docker inspect` 确认 `/data` 已指向新目录，再检查状态中的历史快照数、待上传数量。已验证的上传任务应保持完成，不应因迁移重新生成相同内容的快照。

若启动失败，停止服务，保留新目录排查；可将 `.env` 指回完整回退副本的根目录后重新创建。不要删除唯一一份历史或凭据。

## 权限与 Docker 初始化

初始化容器会将宿主机选定的数据根目录绑定到 `/storage`，再创建各实例子目录。因此，即使宿主路径在项目外，容器也不需要直接访问该宿主绝对路径。新的空目录会按项目所有者调整归属；已有非空目录归属不匹配时要求先人工处理，避免修改不相关数据。

运行服务使用 `.env` 的 UID/GID。数据应位于支持硬链接、文件锁和 SQLite 的本地文件系统，不建议将其放入云盘同步目录或 SMB/NFS 网络共享。
