# 对话功能使用说明（chat）

`copilot_chat` 插件让 QQ 机器人通过本地 [copilot-api](https://github.com/ericc-ch/copilot-api) 代理与 GitHub Copilot 模型对话，自动带入最近聊天历史作为上下文，支持在对话中查看 / 切换模型，并在回复末尾附带模型与时间签名。

> 配置、原理与常见问题详见 [copilot-chat-plugin.md](copilot-chat-plugin.md)，本文聚焦对话与模型相关命令。

## 触发方式

| 场景 | 触发方式 |
| --- | --- |
| 私聊 | 直接发送任意文字 |
| 群聊 | `@机器人` 并附上内容 |
| 命令 | `/chat <内容>`，别名 `/问`、`/ai` |

若消息内容为空，机器人会提示：`请在消息中附上要对话的内容~`。

## 命令一览

| 命令 | 别名 | 作用 |
| --- | --- | --- |
| `/chat <内容>` | `问`、`ai` | 与当前会话所选模型对话 |
| `/models` | `模型`、`模型列表` | 查看代理可用模型列表 |
| `/model` | `选模型`、`切换模型`、`用模型` | 查看当前所选模型 |
| `/model <名称>` | 同上 | 切换当前会话使用的模型 |

> 命令前缀由 `COMMAND_START` 控制，默认包含 `/` 和空前缀。

## 选择模型

每个会话可独立选择模型，后续对话（`/chat`、私聊、群内 @）都会使用所选模型。

```text
/model                 # 查看当前与默认模型
/models                # 列出所有可用模型
/model gpt-4o          # 切换为 gpt-4o
```

切换成功示例：

```text
✅ 已切换为：gpt-4o
```

### 切换校验

切换时机器人会做两步校验：

1. 模型名是否存在于 `/models` 列表，否则提示：

   ```text
   ⚠️ 未知模型：xxx
   用「/models」查看可用模型
   ```

2. 模型是否支持 `/chat/completions`（实地探测一次）。部分模型（如 `gpt-5.x`、`gpt-41-copilot`）虽在列表中，但不支持对话端点，会被拒绝：

   ```text
   ⚠️ 模型「gpt-5.5」不可用于对话（HTTP 400）
   该模型不支持 /chat/completions，请换一个（如 gpt-4o）
   ```

### 会话隔离与持久化

- 选择按 `session_id` 隔离：
  - 群聊：`group:<group_id>`（同群共享所选模型）。
  - 私聊：`private:<user_id>`（每个用户独立）。
- 选择保存在内存中，**机器人重启后重置为默认模型** `COPILOT_MODEL`。

## 回复签名

每条对话回复末尾会附带签名 `——{模型名称}，{时间}`，模型名取自 API 实际返回值（可能比配置别名更具体）：

```text
快速排序的实现如下……

——gpt-4o-2024-11-20，2026-06-26 20:01
```

> 签名只加在发送给用户的消息上，不会写入 MySQL 历史，因此不会污染后续上下文。

## 上下文与会话隔离

- 历史按 `session_id` 隔离（规则同上）。
- 每次对话最多带入 `2 * COPILOT_MAX_TURNS` 条历史消息，按时间从旧到新排列。
- 历史由 `message_recorder` 插件写入 MySQL，`copilot_chat` 负责读取。

## 模型健康检查

`llm_health` 插件每 10 分钟自动探测一次所有可对话模型，并把结果写入 `llm_health` 表（`model / healthy / status_code / latency_ms / error / checked_at`）。

也可手动跑一次填表：

```bash
uv run python scripts/check_llm_health.py
```

查询最近结果：

```sql
SELECT model, healthy, status_code, latency_ms, checked_at
FROM llm_health
ORDER BY id DESC
LIMIT 30;
```

## 常见问题

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| `⚠️ 对话失败：请求失败: ...` | 代理未启动或地址错误 | 确认 copilot-api 在 `4141` 运行，核对 `COPILOT_API_URL` |
| `⚠️ 对话失败：... HTTP 502` | 代理已启动但上游 Copilot 授权失效 | 运行 `npx copilot-api@latest debug` 重新授权 |
| `⚠️ 对话失败：... HTTP 400 ... unsupported_api_for_model` | 选中的模型不支持对话端点 | 用 `/model gpt-4o` 切换为可用模型 |
| `⚠️ 模型「xxx」不可用于对话` | 切换到不支持 `/chat/completions` 的模型 | 换一个模型，或用 `/models` 查看 |
| `模型未返回内容` | 模型返回空回复 | 重试或更换模型 |
| 机器人无响应 | 未 `@` 或命令前缀不匹配 | 私聊直接发送，群聊需 `@机器人` 或使用 `/chat` |

## 相关文件

| 路径 | 说明 |
| --- | --- |
| [`src/plugins/copilot_chat/__init__.py`](../src/plugins/copilot_chat/__init__.py) | 对话、模型列表与选择命令 |
| [`src/plugins/llm_health/__init__.py`](../src/plugins/llm_health/__init__.py) | 每 10 分钟的健康检查定时任务 |
| [src/qq_copilot_bot/services/copilot/copilot_service.py](../src/qq_copilot_bot/services/copilot/copilot_service.py) | Copilot API 客户端（对话、模型列表、健康探测） |
| [src/qq_copilot_bot/services/copilot/health.py](../src/qq_copilot_bot/services/copilot/health.py) | 健康检查编排逻辑 |
| [scripts/check_llm_health.py](../scripts/check_llm_health.py) | 一次性健康检查脚本 |
