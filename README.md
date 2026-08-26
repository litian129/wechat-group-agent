# 企业微信群聊智能体

企业微信群聊消息的智能触发与自动回复智能体，支持命令行处理与 FastAPI 异步任务服务两种模式。

## 快速开始

```bash
# 安装依赖 (仅 API 服务模式需要)
pip install -r requirements.txt

# 运行测试
python tests/test_agent.py

# 命令行处理单个输入文件 (自动识别传统格式/导出格式)
python src/main.py --input input/1787379786.json

# 处理并保存输出
python src/main.py --input input.json --output output.json

# 编程调用
from src.main import WeComGroupAgent
agent = WeComGroupAgent()
result = agent.process_data(input_data)
```

## API 服务模式

```bash
# 启动服务 (默认读取 config/api_config.json)
python src/server.py
# 或指定端口
python src/server.py --host 127.0.0.1 --port 8000
```

交互式 API 文档: http://127.0.0.1:8000/docs

### 接口列表

| 方法 | 路径                          | 说明                                          |
| ---- | ----------------------------- | --------------------------------------------- |
| GET  | `/health`                     | 健康检查                                      |
| POST | `/api/tasks`                  | 开始任务，立即返回 `task_id` (202)            |
| GET  | `/api/tasks`                  | 任务列表                                      |
| GET  | `/api/tasks/{task_id}/status` | 获取任务状态 (pending/running/success/failed) |
| GET  | `/api/tasks/{task_id}/result` | 获取任务结果 (未完成返回 409，失败返回 500)   |

### 调用示例

```bash
# 1. 开始任务 (input_file 为 input/ 下的时间戳文件)
curl -X POST http://127.0.0.1:8000/api/tasks \
     -H "Content-Type: application/json" \
     -d '{"input_file": "input/1787379786.json"}'
# -> {"task_id": "e01f86694769", "status": "pending", ...}

# 2. 查询状态
curl http://127.0.0.1:8000/api/tasks/e01f86694769/status

# 3. 获取结果
curl http://127.0.0.1:8000/api/tasks/e01f86694769/result
```

任务成功后结果同时落盘到 `output/{输入文件名}_result.json`。

### input 文件夹自动监听

服务启动后自动轮询 `input/` 目录（间隔见 `config/api_config.json` 的 `watcher.poll_interval_seconds`）：

- 输入文件以**时间戳命名**（如 `1787379786.json`）
- 发现新增/更新的文件且写入完成后，自动调用 `POST /api/tasks` 开始智能体任务
- 已处理记录持久化在 `state/watcher_state.json`，服务重启不重复提交；文件内容变化后重新处理

## Docker 部署

```bash
# 一键构建并启动 (推荐)
docker compose up -d --build

# 或手动构建
docker build -t wecom-group-agent .
docker run -d --name wecom-group-agent -p 8000:8000 \
  -v $(pwd)/config:/app/config:ro \
  -v $(pwd)/input:/app/input \
  -v $(pwd)/output:/app/output \
  -v $(pwd)/state:/app/state \
  wecom-group-agent

# 查看日志 / 停止
docker compose logs -f
docker compose down
```

部署要点：

- 容器内服务监听 `0.0.0.0:8000`，通过环境变量 `AGENT_API_HOST` / `AGENT_API_PORT` 控制
- `config`、`input`、`output`、`state` 四个目录均通过卷挂载，配置修改后 `docker compose restart` 生效
- 启用大模型时在 compose 中注入 `LLM_API_KEY` 环境变量
- 内置健康检查 (`/health`)，镜像带 HEALTHCHECK 指令
- 往宿主机 `input/` 目录放入时间戳命名的 `.json` 文件，容器内监听器自动触发任务

## 日志与问题排查

日志同时输出到控制台 (stderr) 与滚动文件 `logs/agent.log` (单文件 10MB，保留 5 个备份)。

**级别控制** (优先级从高到低):

| 入口     | 方式                                            |
| -------- | ----------------------------------------------- |
| 命令行   | `python src/server.py --log-level DEBUG`        |
| 环境变量 | `AGENT_LOG_LEVEL=DEBUG` (Docker compose 中可改) |
| 配置文件 | `config/api_config.json` 的 `log_level`         |

**关键日志点** (排查定位用):

- 模型调用: `LLM请求开始` / `LLM响应成功(耗时)` / `LLM调用失败(重试次数)` / `LLM兜底判断命中`
- 智能体处理: `输入识别为导出格式` / `解析会话[...](角色分布)` / `会话[...] 触发: type/intent/score` / `应用LLM兜底响应`
- 任务生命周期: `任务已创建` / `任务开始执行` / `任务执行成功(耗时)` / `任务执行失败(堆栈)` / `任务结果已落盘`
- 文件夹监听: `发现新增/变化文件` / `文件写入稳定, 准备提交` / `文件已提交并记录状态`

排查建议: 无触发时开 `DEBUG` 级别查看角色推断与意图评分细节; 容器环境用
`docker compose logs -f` 或直接查看宿主机 `logs/agent.log`。

## 输入格式

支持两种格式，自动识别：

1. **传统格式**: `{"group_name": "...", "messages": [...]}`
2. **导出格式**: `[{"meta": {"sessionTitle", ...}, "message": [...]}]`
   （会话导出文件，支持一个文件包含多个会话；消息按时间排序，自动推断角色与响应状态）

导出格式的角色推断：命中 `config/role_mapping.json` 映射的使用映射结果，
本方账号(`isSend=true`)视为内部人员，其余外部发送者默认为客户
（可由 `default_external_role` 配置）。内部工作人员请显式加入 `role_mapping.json`。

## 大模型配置

`config/llm_config.json` 配置智能体大模型（OpenAI 兼容协议）：

| 字段                                   | 说明                                                 |
| -------------------------------------- | ---------------------------------------------------- |
| `enabled`                              | 是否启用大模型兜底（默认 `false`，关闭时纯规则引擎） |
| `base_url`                             | OpenAI 兼容接口地址                                  |
| `api_key`                              | 支持 `${LLM_API_KEY}` 环境变量注入                   |
| `model` / `temperature` / `max_tokens` | 模型与生成参数                                       |

启用后：规则引擎未触发的会话会交由大模型兜底判断是否需要干预，
并生成个性化安抚回复（响应中带 `"generated_by": "llm"`）；大模型调用失败自动忽略，不影响规则结果。

## 项目结构

```
wechat-group-agent/
├── config/
│   ├── agent_config.json        # 意图关键词、响应模板、触发配置
│   ├── master_info.json         # 师傅/客服/工程负责人信息
│   ├── role_mapping.json        # 用户到角色映射 + 外部默认角色
│   ├── llm_config.json          # 大模型配置
│   └── api_config.json          # API 服务配置 (端口/目录/监听器)
├── src/
│   ├── main.py                  # 主入口 + WeComGroupAgent 主控类 (同步/异步)
│   ├── server.py                # API 服务启动入口
│   ├── watcher.py               # input 文件夹监听器
│   ├── utils/
│   │   └── logging_config.py    # 统一日志配置 (控制台+滚动文件)
│   ├── api/
│   │   ├── app.py               # FastAPI 应用 (开始/状态/结果接口)
│   │   ├── task_manager.py      # 异步任务管理器
│   │   └── schemas.py           # 请求/响应模型
│   ├── llm/
│   │   └── llm_client.py        # 大模型客户端 (OpenAI 兼容)
│   ├── models/
│   │   ├── message.py           # Message / ChatSession 数据模型
│   │   └── response.py          # AgentResponse / ResponseItem 数据模型
│   ├── core/
│   │   ├── message_parser.py    # JSON解析 + 订单信息提取
│   │   ├── export_parser.py     # 会话导出格式(meta/message)解析
│   │   ├── role_manager.py      # 角色映射 + 中文角色标准化
│   │   ├── intent_classifier.py # 关键词加权评分意图分类
│   │   ├── trigger_engine.py    # 5个触发条件评估
│   │   └── response_generator.py# 模板填充 + 响应生成
│   └── handlers/
│       ├── booking_handler.py   # 触发1: 销售订单
│       └── timeout_handler.py   # 触发2-5: 客户超时
├── input/                       # 时间戳命名的输入文件 (自动监听)
├── output/                      # 任务结果落盘目录
├── state/                       # 监听器处理状态
├── logs/                        # 运行日志 (agent.log 滚动分割)
├── tests/
│   ├── test_agent.py            # 24个单元测试
│   └── test_data/               # 7个测试用例JSON
├── requirements.txt             # API 服务依赖 (fastapi/uvicorn/httpx)
├── Dockerfile                   # Docker 镜像构建
├── docker-compose.yml           # 一键部署编排
└── .dockerignore
```

## 技术栈

- Python 3.12+
- 核心引擎零外部依赖 (仅标准库)
- API 服务: FastAPI + uvicorn + httpx
