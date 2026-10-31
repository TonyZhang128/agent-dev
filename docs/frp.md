# 通过 frp 访问本机 FastAPI（仅开发）

> **仅开发环境。** frp 公网接入用于把 Mac 开发机 API 临时暴露给其他电脑联调，不进入上线部署。Linux 生产环境不安装、不启动 frpc/frps，不使用 `config/dev/frp/`；生产对外入口按实际部署环境的网关、TLS 和权限方案单独设计。

## 开发隧道部署

2026-10-24 已完成本机到公网服务器的真实开发隧道部署与验收：

| 组件 | 位置 / 版本 |
| --- | --- |
| FastAPI / Ollama | 本机现有服务，保持回环监听 |
| frpc | 本机 Homebrew `0.71.1`，项目 launchd 任务 |
| frps | `107.182.190.191`，AlmaLinux 9.8 x86_64，官方 `0.71.1` |
| HTTPS 公网入口 | 复用服务器已有 Caddy `2.6.4`，8443入口无需账户密码 |
| 公网 API | `https://107.182.190.191:8443` |
| 公网 Swagger | `https://107.182.190.191:8443/docs` |

```text
调用方 --HTTPS，无需登录--> 107.182.190.191:8443 (Caddy)
                                      |
                               127.0.0.1:18000 (frps)
                                      |
                              TLS 隧道，frpc 主动连接 :7000
                                      |
                               Mac 127.0.0.1:8309 (FastAPI)
                                      |
                               本机 Ollama 模型推理
```

本次只在 Linux 公网服务器部署开发隧道接入组件，模型仍运行在 Mac；没有部署 Linux GPU/vLLM，也不代表生产 API 已上线。服务器已有站点、443端口和本机业务 `.env` 均保留。服务器的 TCP 18000 仅监听回环地址，7000为隧道入口，8443为 HTTPS 业务入口。

## 另一台电脑上的系统如何调用

公网服务无需账户、密码、API key 或 `Authorization` 请求头。另一台电脑的后端系统可以直接调用这些 REST API。`user_id`、`session_id` 仍按原接口契约提供，它们是业务标识，不是登录凭据。

公网入口与隧道均验证 TLS。当前为私有 CA 签发的 IP 证书，SAN 包含 `IP:107.182.190.191`。调用方需要信任 `.secrets/frp/ca.crt`；浏览器访问前需按浏览器/系统策略导入该 CA 的信任。不要通过关闭证书校验代替正确信任配置。

先把本机 `.secrets/frp/ca.crt` 复制到调用方电脑，例如调用程序目录下的 `ca.crt`。只需分发这个公开 CA 证书，私钥和 frp token 保留在部署端。然后在调用方执行：

```zsh
curl --cacert ./ca.crt -fsS \
  https://107.182.190.191:8443/health
curl --cacert ./ca.crt -fsS \
  https://107.182.190.191:8443/ready
curl --cacert ./ca.crt -fsS \
  https://107.182.190.191:8443/agents/intent \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"example-user","session_id":"example-session","history":[],"text":"打开图片库"}'
```

Python 调用示例（调用方环境安装 `httpx`）：

```python
import ssl

import httpx

context = ssl.create_default_context(cafile="./ca.crt")
with httpx.Client(
    base_url="https://107.182.190.191:8443",
    verify=context,
    timeout=210,
) as client:
    response = client.post(
        "/agents/intent",
        json={
            "user_id": "remote-system-user",
            "session_id": "remote-session-001",
            "history": [],
            "text": "打开图片库",
        },
    )
    response.raise_for_status()
    print(response.json())
```

其他业务接口使用相同的公网地址，路径和请求体见 [API 契约](agents-api.md)。如果由浏览器里的前端 JavaScript 跨域直连，还需按前端实际域名配置 CORS；后端系统直接发 HTTP 请求不受浏览器 CORS 限制。本次未新增 CORS 放行规则。

本机 `.secrets/frp/curl.conf` 现在仅包含 CA 路径，不含账户密码，仍可使用 `curl --config .secrets/frp/curl.conf ...`。项目移动后需更新其中 CA 的绝对路径。原 `api-password`、密码哈希等本地旧文件已不参与公网访问，保留文件不会启用鉴权。

frpc 与 frps 之间仍使用专用 token，这是隧道内部认证，业务调用方不需要提供。凭据和私钥在 Git 忽略的 `.secrets/` 中，目录权限为700，常规文件权限为600。

## 本机服务管理

```zsh
# 新机器先安装客户端；本机已安装
brew install frpc
# 启动或复用本机 API / Ollama
zsh scripts/dev/services.sh start
# 检查配置、凭据和本机 API，不启动新隧道
zsh scripts/dev/start-frpc.sh --check
# 启动 / 重启 / 单独停止公网隧道
zsh scripts/dev/services.sh start-frpc
zsh scripts/dev/services.sh restart-frpc
zsh scripts/dev/services.sh stop-frpc
# 本项目所有任务状态
zsh scripts/dev/services.sh status
```

frpc 任务名为 `local.highway-agent.frpc`，配置为 `config/dev/frp/frpc.toml`，日志为 `.logs/frpc-service.out.log` 和 `.logs/frpc-service.err.log`。通过项目脚本启动可确保相对路径始终从项目根目录解析。旧版本注册的 `local.qwen-business-dev.*` 任务不会被新脚本接管，切换前先手动 `launchctl remove` 旧标签，避免同一代理重复注册。

普通 `services.sh start` 只启动 Ollama/API（API 默认监听 `127.0.0.1:8309`），公网转发通过 `start-frpc` 显式启用。`services.sh stop` 会先停止本项目隧道，再停止 API/Ollama。任务属于当前用户会话，退出登录后按需重新启动。Mac 休眠、断网或 API 停止时，公网服务会中断；网络恢复后 frpc 会尝试重连，进行中的请求需要调用方自行处理失败。该隧道只在开发期使用，上线环境不部署本节脚本和配置。

不要同时使用 `brew services start frpc`，它使用 Homebrew 的另一份配置。前台调试前先运行 `stop-frpc`，然后执行 `zsh scripts/dev/start-frpc.sh`，避免重复注册同一代理。

## 服务端文件和运维

| 文件 | 用途 |
| --- | --- |
| `/usr/local/bin/frps` | 已校验官方发布包的0.71.1可执行文件 |
| `/etc/frp/frps.toml` | 专用 frps 配置，模板在 `config/dev/frp/frps.toml.example` |
| `/etc/frp/token` | 隧道 token，与本机 `.secrets/frp/token` 一致 |
| `/etc/frp/server.crt`、`server.key` | 隧道服务端证书 / 私钥 |
| `/etc/systemd/system/highway-frps.service` | 专用低权限用户 `frp` 托管服务 |
| `/etc/caddy/highway-frp/Caddyfile` | HTTPS 和公开访问的反向代理配置 |
| `/etc/caddy/highway-frp/server.crt`、`server.key` | 公网入口证书 / 私钥 |

原 `/etc/caddy/Caddyfile` 新增了对专用配置的 import，原站点继续保留；初次部署前备份为 `/root/qwen-frp-deploy-20261024/Caddyfile.before`。模板在 `config/dev/frp/Caddyfile.example`，当前没有 BasicAuth 配置。移除鉴权前的专用站点配置另有私有备份。已按旧名部署的主机仍是 `qwen-frps.service` 和 `/etc/caddy/qwen-frp/`；按本节改名时需同时移动证书与配置、停用旧单元并重载 Caddy，否则 frps 或 Caddy 会因路径不存在而启动失败。

服务端通过已授权的 SSH 登录后，可执行：

```bash
systemctl status highway-frps caddy --no-pager
journalctl -u highway-frps -n 50 --no-pager
frps verify -c /etc/frp/frps.toml
# 修改 frps 后
systemctl restart highway-frps
# 修改 Caddy 后先校验，再重载
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
# 核对只监听本机的业务转发端口
ss -lntp | grep ':18000'
curl --noproxy '*' -fsS http://127.0.0.1:18000/health
```

现有 Caddy 已在运行，不需要额外安装 nginx。公网端口、隧道端口或证书名称变更时，需同步调整客户端、服务端、网关及实际防火墙/安全组规则。

## 更新凭据、证书和配置

frp token 位于两端受控文件内。轮换时生成新的随机 token，安全替换两端文件，重启 `highway-frps` 和本机 `restart-frpc`，不要输出 token。

公网 API 没有访问密码，无需执行账户或密码轮换。隧道 token 的变更不影响业务调用方的请求格式。

CA 私钥 `.secrets/frp/ca.key` 仅保留在开发机，未传到服务器。服务端证书有效期397天；到期前用对应 CA 续签，更新 frps/Caddy 的证书和私钥，再重启/重载服务。更换 CA 时还需向所有调用方分发新的 CA，并更新本机 frpc 信任文件。

业务默认总推理超时为180秒，Caddy 上游响应头超时配置为210秒；修改业务超时后同步调整网关和调用方。公网访问无需认证，业务响应和请求字段保持原接口约定。

## 验收记录和边界

初次部署检查了真实 frpc/frps 配置校验、服务启动与 CA/IP 校验。移除公网鉴权后的验收要求是：不发送任何认证头时，健康/就绪/Swagger返回200，非法请求返回422，并能经公网完成真实 `image_library` 意图识别。当前验收报告为本地 `verification/frp-noauth-result.json`，修改前401基线为 `verification/frp-noauth-before.json`。初次部署报告 `verification/frp-public-result.json` 保留为历史记录，其鉴权要求已失效。Mac真实模型/GPU验收为 `verification/live-result.json`。这些文件不提交 Git。

离线检查运行项目的全量 pytest 和 Ruff。AGENTS.md 中 `tests/unit/ tests/integration/` 命令因目录尚不存在而失败，实际测试文件位于 `tests/`。公网真实验收覆盖一次意图业务调用，不代表完整模型评测集已通过公网重跑。

官方资料：[frp v0.71.1](https://github.com/fatedier/frp/releases/tag/v0.71.1)、[frp TLS](https://gofrp.org/zh-cn/docs/features/common/network/network-tls/)、[Caddy 反向代理](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)、[Homebrew frpc](https://formulae.brew.sh/formula/frpc)。
