# 部署通道一次性配置（人工操作清单）

CI 通过 cloudflared SSH 进 VPS 执行部署。以下操作只做一次，完成后在 GitHub 仓库
设置 repo variable `DEPLOY_ENABLED=true`，deploy job 即生效。

## 1. Cloudflare：SSH 的 Access 应用

在 Zero Trust 控制台（one.dash.cloudflare.com）：

1. **Networks → Tunnels** 选中现有 tunnel → Public Hostname 加一条：
   `ssh.<你的域名>` → 服务类型 `SSH`，URL `localhost:22`。
2. **Access → Applications → Add an application → Self-hosted**：
   域名填 `ssh.<你的域名>`。
3. 给这个应用建两条 Policy：
   - `Service Auth`（action 选 Service Auth，不是 Allow）：include 选 Service Token（下一步创建的那个）。
   - 可选：你自己的邮箱 Allow 策略，便于手动 `cloudflared access ssh` 调试。
4. **Access → Service Auth → Service Tokens → Create**：
   名字如 `github-ci`，记下 Client ID 和 Client Secret（只显示一次）。

## 2. VPS：部署用户与 SSH key

```bash
# 本地生成专用密钥对（不要复用个人 key）
ssh-keygen -t ed25519 -f unspun-deploy -N "" -C "unspun-ci"
# 公钥追加到 VPS 部署用户的 authorized_keys
```

VPS 上准备：

```bash
mkdir -p ~/unspun
# 按 deploy/env.example 创建 ~/unspun/.env，填入真实 POSTGRES_PASSWORD 等
chmod 600 ~/unspun/.env
# GHCR 只读登录（GitHub 上创建仅 read:packages 的 classic PAT）
docker login ghcr.io -u <github用户名> -p <PAT>
```

## 3. 网站的 Public Hostname

Tunnel 再加一条 Public Hostname：`unspun.<你的域名>`（或你想要的子域）→
服务类型 `HTTP`，URL `localhost:8080`。并给它建 Access 应用（Allow 你的邮箱），
保证网站先登录才能看。

## 4. GitHub 仓库配置

Settings → Secrets and variables → Actions：

| 类型 | 名称 | 值 |
| --- | --- | --- |
| Secret | `VPS_SSH_KEY` | `unspun-deploy` 私钥全文 |
| Secret | `VPS_SSH_USER` | VPS 部署用户名 |
| Secret | `VPS_SSH_HOSTNAME` | `ssh.<你的域名>` |
| Secret | `CF_ACCESS_CLIENT_ID` | Service Token 的 Client ID |
| Secret | `CF_ACCESS_CLIENT_SECRET` | Service Token 的 Client Secret |
| Variable | `DEPLOY_ENABLED` | `true`（全部就绪后最后设置） |

## 5. 验证

合并任意 PR 到 main（或手动 re-run deploy job），CI 绿后：

- 浏览器访问 `https://unspun.<你的域名>`：先 Access 登录，然后看到占位页和健康状态。
- VPS 上 `ss -tlnp | grep -v 127.0.0.1` 确认没有对外监听端口。
