# Google Drive OAuth 配置与 invalid_client 修复

`client_id` 和 `client_secret` 是 Google 签发的应用凭据。应用名如 `macmini` 可用于控制台的显示名称，不能当成 client ID；client secret 也不是个人账号密码。随意填写会导致授权时出现 `401 invalid_client`。

rclone 官方说明共享 Google 客户端将在 2026 年退役，长期部署应创建自己的客户端。来源：[rclone 配置说明](https://rclone.org/drive/#making-your-own-client-id)。

## 创建真实客户端

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)，创建或选择自己的项目。
2. 在 API 库中启用 **Google Drive API**。
3. 进入 **Google Auth Platform**，完成 Branding / 品牌信息；个人 Google 账号通常选择 External。用于测试时，将实际登录 Drive 的 Google 账号加入 Test users。
4. 在 Data Access 中配置本次所需的 Drive scope。当前部署使用 `https://www.googleapis.com/auth/drive`，与 rclone 中的 `scope=drive` 一致。
5. 进入 Clients，新建 OAuth 客户端，应用类型选择 **Desktop app / 桌面应用**。显示名称可以是 `macmini-backup`。
6. 保存 Google 给出的完整 **Client ID** 和 **Client secret**。ID 通常以 `.apps.googleusercontent.com` 结尾；secret 是 Google 自动生成的字符串。只在本地向导中填写，不贴进聊天或提交 Git。

客户端类型和创建入口见 [Google 官方凭据文档](https://developers.google.com/workspace/guides/create-credentials#desktop-app)，同意屏幕配置见 [Google 官方说明](https://developers.google.com/workspace/guides/configure-oauth-consent)。

## 修改现有 gdrive

在 Mac 的项目目录内操作，先停下对应实例，避免与 token 刷新同时写文件：

```sh
docker compose stop backup
.tools/rclone --config .secrets/rclone/rclone.conf config
```

选择 `e` 编辑现有 remote，再选 `gdrive`；填写刚创建的真实 Client ID 与 secret。保留 scope `drive`；service account file 使用普通个人登录时留空；高级配置选 N；本机浏览器自动授权选 Y。如果询问是否替换已有 token，选 Y。个人 Drive 的 Shared Drive 问题通常选 N，最后确认保存。

若向导里没有 `gdrive`，用 `n` 创建，类型选 `drive`。只处理这个 remote，已完成的 `onedrive` 不需要重做。

退出后验证：

```sh
.tools/rclone --config .secrets/rclone/rclone.conf lsd gdrive:
```

命令应成功结束；空盘可能没有目录输出。随后继续配置剩余目标、启用 JSON 配置并启动备份。

名为 `family` 的实例使用相同流程，但 stop 命令改为 `docker compose -f compose.family.yaml stop backup`，配置文件改为 `profiles/family/.secrets/rclone/rclone.conf`。任意命名实例如 `brother` 可使用 `python3 scripts/manage.py configure --profile brother` 打开各自的配置。两个实例可使用同一 OAuth 应用；使用不同 Google 账号时分别授权，若均处于测试名单限制下，需要都加入 Test users。若备份到同一账号，也可以按[家人实例指南](family-profiles.md)只复制备份目标连接。

## 长期运行

External 应用保持 Testing 状态时，带 Drive 权限的 refresh token 通常只保留 7 天。测试通过后，按 Google Console 要求完成 In production 设置；应用发布、验证要求以实际控制台提示为准。避免将每周重新授权当作无人值守备份的正常运行方式。来源：[Google OAuth token 过期说明](https://developers.google.com/identity/protocols/oauth2#expiration)。

### 切换为 Production

1. 在 Google Cloud Console 选择创建当前 Client ID 的项目，进入 Google Auth Platform → Audience。
2. 在 Publishing status 下点击 Publish app 并确认，确认状态变为 In production。
3. 若按钮不可用，按控制台提示补全 Branding 的必填信息；rclone 文档说明可能需要主页、隐私政策及相关域名设置。
4. 对你和少数认识的家人自用，Google 提供个人用途的验证豁免。仍可能出现未验证应用提示；只在确认它是自己创建的应用、请求权限符合预期时继续授权。发布状态与是否完成验证是两个独立设置。来源：[Google 个人用途豁免](https://support.google.com/cloud/answer/13464323)、[受众与发布状态](https://support.google.com/cloud/answer/15549945)。

切换后建议重新授权一次，避免继续沿用 Testing 阶段取得的授权；无需更换同一客户端的 ID / secret：

```sh
docker compose stop backup
.tools/rclone --config .secrets/rclone/rclone.conf config reconnect gdrive:
.tools/rclone --config .secrets/rclone/rclone.conf lsd gdrive:
docker compose up -d
```

如果家人的 Google 连接也已配置，对应实例同样处理：

```sh
docker compose -f compose.family.yaml stop backup
.tools/rclone --config profiles/family/.secrets/rclone/rclone.conf config reconnect gdrive:
.tools/rclone --config profiles/family/.secrets/rclone/rclone.conf lsd gdrive:
docker compose -f compose.family.yaml up -d
```

Production 取消的是 Testing 的特定 7 天限制，不代表 token 永远不会失效；用户撤销权限等情形仍需重新授权。
