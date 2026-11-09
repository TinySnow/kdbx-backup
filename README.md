# KDBX Backup 使用指南

将密码数据库的历史版本自动备份到多个云盘。误删或误改主库后，你可以下载以前的版本，再用自己的密码管理器打开。

你仍在 StrongBox、KeePass 或 KeePassXC 中使用原来的 `.kdbx` 文件。KDBX Backup 默认每分钟读取一次这个文件，发现内容变化后，在服务器和备份云盘中各保存一份新版本。它不需要数据库主密码，也不解密密码条目。

例如，你可以这样使用：

```text
你日常编辑的 PASSWD.kdbx
          │
          ▼
服务器保存一份带时间的历史版本
          ├── 上传到 Google Drive
          └── 上传到坚果云
```

每份历史都有独立的文件名。删除主库或保存了错误内容，不会让本服务删除已经保存的历史。

## 你想做什么？

| 你的情况 | 从这里开始 |
| --- | --- |
| 第一次使用，想备份自己的密码库 | [设置第一份备份](docs/deploy-from-zero.md) |
| 自己的备份已经运行，想给哥哥或其他家人添加备份 | [为家人设置备份](docs/family-profiles.md) |
| 密码库在 Google Drive、坚果云或其他云盘 | [选择主库所在的云盘](docs/source-storage.md) |
| Google 授权失败，或不知道 Client ID 怎么填 | [连接 Google Drive](docs/google-drive-oauth.md) |
| 想知道备份是否成功，或保存后没有看到新文件 | [查看状态和解决常见问题](docs/operations.md) |
| 误删或误改了数据库 | [找回以前的数据库版本](docs/restore.md) |
| 想更改服务器保存历史的位置 | [更改本地备份位置](docs/data-migration.md) |

## 先认识三个名称

**主库**是你平时打开和修改的 `.kdbx` 文件，例如 OneDrive 里的 `PASSWD.kdbx`。

**备份目标**是保存历史版本的云盘和文件夹，例如你的 Google Drive 中的 `KDBX-Backups/me/`。主库和备份目标可以属于不同账号。

**实例**是一份独立的备份任务。自己的任务叫 `default`；哥哥的可以叫 `brother`。每个实例备份一个数据库，有自己的云盘连接、配置和历史。示例中的 `family` 也只代表一个实例，不是全家共用的目录。

## 开始前，你需要知道

- 服务在 Docker 中运行，支持 AMD64 和 ARM64。可使用 Linux、Mac 上的 Docker 环境，或 Windows 的 Docker Desktop Linux 容器。
- 服务器和 Docker 需要保持运行。关机、休眠或断网期间，服务不能取得新版本。
- 默认每分钟检查一次，可能错过这一分钟内多次保存的中间版本。需要保留每次保存时，请同时启用密码管理器自己的备份功能。
- 历史不会自动清理。服务器和云盘都需要留有足够空间。
- 上传完成后，服务会下载回读并核对 SHA-256，确认上传内容一致。你仍应实际下载并试开一份数据库。

## 配置和文件在哪里？

默认实例的设置在 `config/config.json`，云盘授权在 `.secrets/rclone/rclone.conf`。家人的设置在 `profiles/实例名/` 下。

本地历史存放位置由 `.env` 中的 `KDBX_BACKUP_DATA_ROOT` 决定。该目录下的 `default/`、`brother/` 等子目录分别保存每个人的历史。配置文件、授权和实际数据库不会提交到 Git，也不会进入镜像构建内容。

详细说明见[配置参考](docs/configuration.md)。开发、测试和镜像发布见[维护者指南](docs/releasing.md)。项目使用 [MIT 许可证](LICENSE)。
