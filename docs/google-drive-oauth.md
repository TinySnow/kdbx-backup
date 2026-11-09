# 连接 Google Drive

要让备份服务访问 Google Drive，需要先在 Google Cloud 创建一个应用，再用 Google 账号同意授权。你只需为自己的部署创建客户端，无需把密码数据库上传到 Google Cloud 项目。

完成后，rclone 会保存一个名为 `gdrive` 的云盘连接。

## 开始之前

准备一个 Google 账号，并打开 [Google Cloud Console](https://console.cloud.google.com/)。你可以使用这个账号保存备份。

先确认你在配置哪份任务：

| 任务 | 停止并打开连接向导 |
| --- | --- |
| 自己的默认任务 | 先运行 `docker compose stop backup`，再运行 `.tools/rclone --config .secrets/rclone/rclone.conf config` |
| 哥哥的任务 | 运行 `python3 scripts/manage.py configure --profile brother` |

命令在项目文件夹执行，使用[首次设置](deploy-from-zero.md)准备的工具。Windows 原生终端将 `python3` 换成 `python`，工具名换成 `.tools/rclone.exe`。

> **Client ID 不是账号或应用名称。** `client_id` 和 `client_secret` 都由 Google 生成。不要填微软密码、Google 密码或自己起的 `Backup`、`macmini` 等名称。

## 1. 选择 Google Cloud 项目

1. 登录 Google Cloud Console。
2. 点击顶部的项目选择器。
3. 新建一个项目，例如 `KDBX Backup`；已有专用项目时也可以直接选择。
4. 确认顶部显示刚选择的项目。

后面的 API、受众和客户端都要在**同一个项目**里配置。

## 2. 启用 Google Drive API

1. 在控制台搜索框搜索 `Google Drive API`。
2. 打开对应 API 页面。
3. 点击“启用”（Enable）。已经启用时无需再次操作。

## 3. 设置应用信息和测试账号

打开 **Google Auth Platform**。如果首次打开时显示入门向导，先按提示完成：

1. 在 **Branding（品牌信息）** 填写应用名称和联系邮箱。应用名可以叫 `Backup`。
2. 在 **Audience（受众）** 为个人账号选择 **External（外部）**。
3. 应用处于 **Testing（测试）** 时，在 **Test users（测试用户）** 添加稍后真正登录 Google Drive 的 Google 邮箱。
4. 在 **Data Access（数据访问）** 添加本次所需的 Drive 权限 `https://www.googleapis.com/auth/drive`。

**确认结果：** 测试用户列表里有你要授权的 Google 账号。给家人建立任务、但备份到你的云盘时，这里仍添加你的 Google 账号。

## 4. 创建桌面客户端

1. 打开 **Clients（客户端）**。
2. 点击创建客户端。
3. 应用类型选择 **Desktop app（桌面应用）**。
4. 输入一个显示名称，例如 `KDBX Backup Desktop`。
5. 创建后，保存 Google 显示的 **Client ID** 和 **Client secret**。

**确认结果：** 得到由 Google 签发的一对凭据。Client ID 通常以 `.apps.googleusercontent.com` 结尾。它们与第 3 步的应用显示名称不同。

创建入口见 [Google 官方凭据说明](https://developers.google.com/workspace/guides/create-credentials#desktop-app)。rclone 也提供[自建客户端说明](https://rclone.org/drive/#making-your-own-client-id)。共享 Google 客户端正在退役，长期部署请使用自己的客户端。

## 5. 在终端授权 Google Drive

按页首表格打开对应任务的连接向导。输入 `n` 新建连接；已有 `gdrive` 时，输入 `e` 并选择它，修改现有连接。

| 向导提示 | 填写或选择 |
| --- | --- |
| `name`（新建时） | `gdrive` |
| `Storage` | `drive` |
| `client_id` | 第 4 步 Google 给出的完整 Client ID |
| `client_secret` | 第 4 步 Google 给出的 Client secret |
| `scope` | `drive` |
| `service_account_file` | 普通个人登录留空 |
| 高级配置 | `n` |
| 本机浏览器自动授权 | 有浏览器时选 `y` |
| Shared Drive / 团队云端硬盘 | 普通个人云盘选 `n` |

如果编辑已有连接时询问是否重新授权，选择重新授权。

在浏览器里选择**保存备份的 Google 账号**，核对应用名称并同意授权。回到终端确认保存，输入 `q` 退出。不要将显示出来的 token 或客户端密钥贴进聊天或提交 Git。

## 6. 检查连接

默认任务运行：

```sh
.tools/rclone --config .secrets/rclone/rclone.conf lsd gdrive:
```

哥哥的任务运行：

```sh
.tools/rclone --config profiles/brother/.secrets/rclone/rclone.conf lsd gdrive:
```

**确认结果：** 命令正常结束。空云盘可能没有目录输出。成功后回到[首次设置](deploy-from-zero.md#6-告诉服务备份哪个文件)或[家人设置](family-profiles.md#4-设置文件路径和备份文件夹)继续，不要停在授权完成这一步。

## 7. 让授权适合长期运行

个人账号的 External 应用保持 Testing 时，带 Drive 权限的刷新令牌通常在 7 天后过期。测试通过后：

1. 回到同一 Google Cloud 项目的 **Google Auth Platform → Audience**。
2. 在 **Publishing status（发布状态）** 点击 **Publish app（发布应用）**。
3. 确认状态变成 **In production**。按钮不可用时，按页面要求补全 Branding 信息。
4. 对于你和少数认识的家人使用的应用，可查看 Google 的个人用途验证豁免；仍可能显示未验证应用提示。

这里发布的是 OAuth 应用的使用状态，不是公开你的密码库，也不会更改 GitHub 仓库的可见性。In production 与“通过 Google 验证”是两件事。

状态切换后，建议重新授权，避免继续沿用 Testing 阶段取得的令牌。默认任务运行：

```sh
docker compose stop backup
.tools/rclone --config .secrets/rclone/rclone.conf config reconnect gdrive:
.tools/rclone --config .secrets/rclone/rclone.conf lsd gdrive:
docker compose up -d
```

其他任务先停止对应任务，将授权文件路径换成自己的路径，再启动该任务。取消 Testing 的 7 天限制不表示授权永远不会失效；撤销权限等情况仍需重新授权。

依据：[Google 受众与发布状态](https://support.google.com/cloud/answer/15549945)、[个人用途验证豁免](https://support.google.com/cloud/answer/13464323)、[刷新令牌过期说明](https://developers.google.com/identity/protocols/oauth2#expiration)。

## 如果授权失败

| 你看到的提示 | 先检查什么 |
| --- | --- |
| `401 invalid_client` | 是否误填应用名、账号密码，或 Client ID 与 secret 来自不同客户端。回到第 4、5 步核对 |
| “尚未完成 Google 验证，仅限获准测试人员” | 同一项目的 Test users 是否包含当前登录的 Google 邮箱；浏览器是否选错账号 |
| 浏览器没有打开 | 使用终端给出的本机授权链接；服务器没有浏览器时，按[无浏览器授权方法](operations.md#在没有浏览器的服务器上授权)操作 |
| 每隔约一周需要重登 | 检查是否仍处于 Testing，按第 7 步设置长期运行 |
| 授权成功但没有备份文件 | 授权只是连接云盘；还要配置 `enabled: true` 并启动备份任务 |
