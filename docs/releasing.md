# 维护者发布指南

项目以 Linux 容器分发，目标架构为 `linux/amd64`、`linux/arm64`。宿主管理工具支持 Windows、macOS、Linux，Python 3.9+，无第三方 Python 依赖。备份服务本身在容器内运行，未承诺 Windows 原生 Python 服务。

## 自动测试

`.github/workflows/ci.yml` 对分支 push 和 PR 运行：

- Linux、macOS、Windows 上的管理工具测试；最低 Python 3.9 在 Linux 上验证。
- AMD64 与 ARM64 的原生 Linux runner 上构建镜像，并在容器中运行全部测试。
- 检查默认、家庭实例、初始化、本地构建与命名实例的 Compose 配置。

测试只使用合成文件和临时目录，不需要网盘账号。Windows/macOS runner 测试管理工具；完整 Docker Desktop 主机挂载和真实 OAuth 授权仍需要相应设备上的人工验收。

本地等价命令：

```sh
python3 scripts/manage.py test
python3 scripts/manage.py test-integration --platform linux/amd64
python3 scripts/manage.py test-integration --platform linux/arm64
```

异构架构测试需要 Docker 的 QEMU／Rosetta 等模拟支持。实际发布 CI 分别使用原生 runner。

## 镜像发布

1. 将项目上传到你拥有的 GitHub 仓库，允许 Actions 使用 `GITHUB_TOKEN` 写入 Packages。
2. 修改 `VERSION`，例如 `0.1.0`，同时更新 deploy/Dockerfile 的默认 `ARG VERSION`。
3. 推送对应的 `v0.1.0` 标签。
4. `release.yml` 先调用完整测试，全部通过后才向 GHCR 推送双架构镜像。

镜像地址自动使用当前仓库的小写路径：`ghcr.io/owner/repository:0.1.0`。稳定版同时更新 `latest`；带 `-rc.1` 等后缀的预发布版本只推送版本标签。标签必须与 `VERSION` 完全匹配。发布不需要另建 PAT，使用仓库提供的 `GITHUB_TOKEN`。

首次发布后，按面向用户的访问范围设置 GHCR 包的可见性，并用干净环境验证拉取。私有包的使用者需要先完成 `docker login ghcr.io`。

源码和自动化配置已准备好，不代表镜像已经存在。当前适配工作不创建远端仓库、不推送标签、不上传任何镜像。

## 无 GitHub Actions 的构建

```sh
docker buildx build -f deploy/Dockerfile --platform linux/amd64,linux/arm64 \
  --build-arg VERSION=0.1.0 \
  --tag ghcr.io/yourname/kdbx-backup:0.1.0 \
  --push .
```

在已登录的仓库执行上述命令会直接发布镜像，应由维护者在验证完成后运行。普通用户从源码使用 `python scripts/manage.py start` 即可，无需发布。

## 版本维护

- `tools/bootstrap_rclone.py` 的 `VERSION` 与 deploy/Dockerfile 的 `RCLONE_VERSION` 保持一致。
- 升级 rclone 后，必须保留并运行“单文件复制绕过 immutable”的回归测试。历史上传使用目录复制加精确过滤，避免切回单文件路径。
- 发布包只包含源码与示例。实际 `config/config.json`、`.secrets/`、`.tools/`、`data/`、整个 `profiles/` 已从 Git 和镜像构建上下文排除。
- 本项目采用 MIT，rclone 等第三方组件遵守各自许可证。

## 2026-11-02 本地验证

适配前：本机 macOS ARM64 / OrbStack，18 项容器测试通过。

适配后：本机 macOS 的 13 项宿主管理工具测试通过；ARM64 原生容器、AMD64 模拟容器各 31 项测试通过，包含原备份逻辑、真实 rclone、本地模拟 WebDAV 和管理工具测试。两份工作流通过 actionlint 检查。Windows 实机、其他 NAS 的挂载文件系统与实际云盘 OAuth 尚未验收；GitHub Actions 尚未连接远端仓库，不能将配置存在视为远端 CI 已运行。

多账号适配后：宿主管理工具测试增至 24 项；ARM64 原生与 AMD64 模拟容器各 43 项测试通过。新增测试覆盖多实例目录与凭据隔离、默认配置兼容、未知实例拒绝创建、批量管理、停止与未创建状态展示，以及两个独立服务进程同时使用相同 remote 名称、相同密码库文件名时的独立备份。一个账号的源文件删除后，另一个账号仍可继续上传新版本。更新后的工作流也通过 actionlint 检查。

纯 Docker 入口适配后：宿主管理测试 25 项通过；本机已实测 `compose.init.yaml` 初始化、默认 Compose 启动、`compose.family.yaml` 启动，确认与管理工具使用相同实例及挂载。另在容器内部的临时 Linux 文件系统中，以 UID 1001 验证首次初始化、目录归属和服务配置读取、状态写入。真实账号仍需分别授权。

目录整理及可配置存储适配后：源码移到 `src/kdbx_backup/`，管理和初始化工具移到 `scripts/`，Dockerfile 移到 `deploy/`，配置示例移到 `examples/`。宿主管理测试 32 项通过；ARM64 原生容器和 AMD64 模拟容器各 52 项通过，包括自定义绝对/相对数据根、homelab 自动推断、环境优先级以及迁移后保留快照和已完成上传进度。实际 homelab 的旧数据已逐文件 SHA-256 校验并迁到外置数据根，数据库完整性校验通过，保留旧数据回退副本。
