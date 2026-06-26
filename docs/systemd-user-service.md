# Ubuntu systemd 用户级服务部署教程

> 适用于：Ubuntu 20.04+，systemd 236+  
> 特性：无需 root、开机自启、journal + 文件双路日志、崩溃自动重启

---

## 背景与适用场景

在服务器或个人机器上长期运行一个后台进程（如 `copilot-api`），通常有以下需求：

- 不希望用 `sudo` 或 root 权限运行
- 机器重启后服务自动拉起，无需手动登录
- 日志既能实时查看，又能持久保存到文件
- 进程崩溃后自动重启

systemd **用户级服务**（user service）完美满足以上需求。

---

## 前提条件

| 项目 | 要求 |
|------|------|
| OS | Ubuntu 20.04 / 22.04 / 24.04 |
| systemd | ≥ 236（`systemd --version` 查看） |
| 可执行文件 | 已安装，能用 `which <cmd>` 找到路径 |

---

## 步骤一：确认可执行文件路径

```bash
which copilot-api
```

示例输出：

```
/home/<user>/.nvm/versions/node/v24.18.0/bin/copilot-api
```

> **nvm 用户注意**：nvm 管理的二进制路径包含 Node.js 版本号。升级 Node 版本后需同步更新服务文件中的路径。

---

## 步骤二：创建日志目录

```bash
mkdir -p ~/.copilot-api/logs
```

---

## 步骤三：编写服务文件

```bash
mkdir -p ~/.config/systemd/user
nano ~/.config/systemd/user/copilot-api.service
```

写入以下内容（将 `ExecStart` 和 `PATH` 替换为实际路径）：

```ini
[Unit]
Description=Copilot API Service
After=network.target

[Service]
Type=simple
ExecStart=/home/<user>/.nvm/versions/node/v24.18.0/bin/copilot-api start

# 将可执行文件所在目录加入 PATH，避免找不到 node 等依赖
Environment="PATH=/home/<user>/.nvm/versions/node/v24.18.0/bin:/usr/local/bin:/usr/bin:/bin"

# 输出同时写入 journal 和终端（journal+console），再追加到文件
StandardOutput=journal+console
StandardError=journal+console
StandardOutputFile=/home/<user>/.copilot-api/logs/app.log
StandardOutputFileAppend=yes
StandardErrorFile=/home/<user>/.copilot-api/logs/app.log
StandardErrorFileAppend=yes

# 崩溃后 3 秒自动重启
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

---

## 步骤四：启用 Linger（开机无需登录即自启）

默认情况下，用户级 systemd 服务仅在该用户**登录后**才会启动。  
开启 **linger** 后，系统启动时会自动为该用户启动 systemd 会话，从而在无人登录时也能拉起服务。

```bash
# 需要 sudo 权限
sudo loginctl enable-linger "$USER"

# 验证（无需 sudo）
loginctl show-user "$USER" | grep Linger
# 期望输出：Linger=yes
```

---

## 步骤五：重载并启动服务

```bash
# 让 systemd 识别新服务文件
systemctl --user daemon-reload

# 设置开机自启
systemctl --user enable copilot-api

# 立即启动
systemctl --user start copilot-api
```

---

## 验证服务状态

```bash
systemctl --user status copilot-api
```

正常输出示例：

```
● copilot-api.service - Copilot API Service
     Loaded: loaded (...; enabled; ...)
     Active: active (running) since ...
   Main PID: 12345 (node)
```

---

## 日常运维命令

### 查看状态

```bash
systemctl --user status copilot-api
```

### 查看日志

```bash
# 实时跟踪文件日志
tail -f ~/.copilot-api/logs/app.log

# 实时跟踪 journal 日志（支持过滤、结构化查询）
journalctl --user -u copilot-api -f

# 查看最近 100 行
journalctl --user -u copilot-api -n 100 --no-pager
```

### 管理服务

```bash
systemctl --user restart copilot-api   # 重启
systemctl --user stop copilot-api      # 停止
systemctl --user start copilot-api     # 启动
systemctl --user disable copilot-api   # 取消开机自启（不停止当前运行）
```

---

## 配置字段说明

| 字段 | 作用 |
|------|------|
| `Type=simple` | 进程启动即视为就绪，适合长驻前台进程 |
| `After=network.target` | 等网络就绪后再启动，避免依赖网络的服务提前启动失败 |
| `Environment="PATH=..."` | 为服务进程设置独立 PATH，nvm/pyenv 等版本管理器路径需显式指定 |
| `StandardOutput=journal+console` | 同时输出到 systemd journal 和 controlling terminal |
| `StandardOutputFile=...` | 追加写入文件（需 systemd ≥ 236） |
| `Restart=on-failure` | 仅在异常退出（非 0 退出码）时重启，正常 `stop` 不触发 |
| `RestartSec=3` | 重启前等待 3 秒，防止快速循环崩溃 |
| `WantedBy=default.target` | 用户级服务的标准 install target |

---

## 常见问题

### Q：升级 Node.js 版本后服务无法启动？

nvm 管理的路径包含版本号。升级后执行：

```bash
# 查看新路径
which copilot-api

# 编辑服务文件，更新 ExecStart 和 PATH 中的版本号
nano ~/.config/systemd/user/copilot-api.service

# 重载并重启
systemctl --user daemon-reload
systemctl --user restart copilot-api
```

### Q：重启机器后服务没有自启？

检查 linger 是否开启：

```bash
loginctl show-user "$USER" | grep Linger
```

若输出 `Linger=no`，执行 `sudo loginctl enable-linger "$USER"` 后重试。

### Q：日志文件一直增大怎么办？

可配合 `logrotate` 定期轮转：

```bash
# 创建 logrotate 配置
cat > ~/.config/logrotate/copilot-api << 'EOF'
/home/<user>/.copilot-api/logs/app.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}
EOF

# 加入 cron（每天凌晨 2 点轮转）
(crontab -l 2>/dev/null; echo "0 2 * * * /usr/sbin/logrotate ~/.config/logrotate/copilot-api") | crontab -
```

### Q：如何彻底卸载服务？

```bash
systemctl --user stop copilot-api
systemctl --user disable copilot-api
rm ~/.config/systemd/user/copilot-api.service
systemctl --user daemon-reload
```

---

## 快速安装脚本（一键版）

将以下脚本保存为 `install-copilot-api-service.sh`，按实际情况修改变量后执行：

```bash
#!/usr/bin/env bash
set -euo pipefail

# ── 按实际情况修改 ──────────────────────────────────────────
EXEC_PATH=$(which copilot-api)          # 自动探测；也可手动指定
EXEC_ARGS="start"                       # 启动参数
LOG_DIR="$HOME/.copilot-api/logs"
# ────────────────────────────────────────────────────────────

EXEC_DIR=$(dirname "$EXEC_PATH")
SERVICE_FILE="$HOME/.config/systemd/user/copilot-api.service"

echo "==> 可执行文件：$EXEC_PATH"
echo "==> 日志目录：  $LOG_DIR"

mkdir -p "$(dirname "$SERVICE_FILE")" "$LOG_DIR"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Copilot API Service
After=network.target

[Service]
Type=simple
ExecStart=${EXEC_PATH} ${EXEC_ARGS}
Environment="PATH=${EXEC_DIR}:/usr/local/bin:/usr/bin:/bin"
StandardOutput=journal+console
StandardError=journal+console
StandardOutputFile=${LOG_DIR}/app.log
StandardOutputFileAppend=yes
StandardErrorFile=${LOG_DIR}/app.log
StandardErrorFileAppend=yes
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF

sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now copilot-api

echo ""
echo "✅ 安装完成"
systemctl --user status copilot-api --no-pager
```
