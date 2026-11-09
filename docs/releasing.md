# 测试和发布镜像

本页供维护项目源码和发布 Docker 镜像的人使用。只想运行备份时，请使用[首次设置指南](deploy-from-zero.md)，无需创建版本标签或上传镜像。

项目以 Linux 容器运行，目标架构为 `linux/amd64`、`linux/arm64`。宿主管理工具使用 Python 3.9+，支持 Windows、macOS 和 Linux。

## 在提交前运行测试

在项目文件夹运行宿主管理工具测试：

```sh
python3 scripts/manage.py test
```

在 Docker 中分别运行两个架构的完整测试：

```sh
python3 scripts/manage.py test-integration --platform linux/amd64
python3 scripts/manage.py test-integration --platform linux/arm64
```

**确认结果：** 测试成功退出。异构测试需要 Docker 提供 QEMU、Rosetta 等模拟支持。这些命令使用合成数据和临时目录，不挂载真实云盘凭据或生产数据。

## 检查 GitHub Actions

推送分支或创建 Pull Request 后，在仓库的 **Actions → Tests** 查看结果：

- Linux、macOS、Windows 的管理工具测试。
- AMD64、ARM64 原生 Linux runner 的容器测试。
- Compose 配置及纯 Docker 初始化检查。

工作流文件位于 `.github/workflows/ci.yml`。实际是否通过以该次运行结果为准。Windows/macOS 的宿主工具测试不代替真实 Docker Desktop 挂载和 OAuth 授权的人工检查。

## 发布一个版本

开始前，确认你有仓库和 GHCR 包的写入权限。当前仓库为私有；发布包时也要单独核对包的可见性，不要假定它与源码仓库自动一致。

1. 修改 `VERSION`，例如设为 `0.1.0`，同步修改 `deploy/Dockerfile` 的默认 `ARG VERSION`。
2. 提交并推送版本修改，确认测试通过。
3. 创建并推送相同版本的标签：

   ```sh
   git tag v0.1.0
   git push origin v0.1.0
   ```

   使用你实际准备发布的版本号；已存在的标签不要重复创建或覆盖。
4. 在 **Actions → Publish image** 查看发布结果。

**确认结果：** 完整测试通过后，工作流向 GHCR 上传双架构镜像。这个仓库的地址形式为 `ghcr.io/tinysnow/kdbx-backup:版本号`；它只有在发布成功后才可拉取。

版本标签必须与 `VERSION` 一致。稳定版同时更新 `latest`；带 `-rc.1` 等后缀的预发布版本只更新对应版本标签。工作流使用 `GITHUB_TOKEN`，需要 Packages 写权限。

## 验证发布的镜像

私有包先按 GitHub 的包访问要求完成 `docker login ghcr.io`。在有读取权限的干净环境中验证拉取，以及 AMD64、ARM64 两个平台运行。

只有确认镜像已经存在，使用者才能在 `.env` 设置：

```dotenv
KDBX_BACKUP_IMAGE=ghcr.io/tinysnow/kdbx-backup:0.1.0
```

替换为实际发布版本。新部署用此镜像初始化：

```sh
docker compose -f compose.init.yaml pull init
docker compose -f compose.init.yaml run --rm init
```

再拉取并启动默认任务：

```sh
docker compose pull backup
docker compose up -d --no-build
```

已有服务仍需保留配置、授权和持久化数据。命名任务可用 `python3 scripts/manage.py start --profile brother --pull`。

## 维护依赖和发布内容

- `scripts/bootstrap_rclone.py` 的 `VERSION` 与 `deploy/Dockerfile` 的 `RCLONE_VERSION` 保持一致。
- 升级 rclone 时，运行上传不可覆盖的回归测试。当前上传使用目录复制加精确文件过滤，避免单文件复制绕过不可变检查。
- Git 忽略规则排除实际配置、授权、工具和历史。提交前再次检查暂存区，尤其不要用强制添加来纳入这些文件。
- 镜像构建只包含运行源码和许可证，不包含实际数据库或云盘授权。
- 项目使用 MIT；第三方组件遵守各自许可证。

本地验证记录不作为所有系统都已验收的证明。新版本应在实际使用的宿主系统、挂载文件系统和云盘连接上完成一次首份备份与恢复检查。
