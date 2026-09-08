# MCP Server 快速开始

**[English](mcp_quickstart.en.md) | 中文**

对应 TASKS.md Epic 6.2-6.4。这个 MCP Server 在 Claude Desktop / Cursor
里显示的名字是 **Spomory**（`src/memory_core/mcp_server/server.py` 里
`MCPServer("Spomory")`），暴露五个工具：`add_memory`、`search_memory`、
`get_graph`、`export_memory`、`forget_memory`（找到和查询最匹配的一条
记忆并物理删除，是 `export_memory` 背后"真删除"能力第一次有了用户能在
对话里直接触发的入口），默认用本地 `LocalGraphStore`（SQLite 文件
`memory_core.sqlite3`）。

> Python 包名、CLI 命令（`memory-core-mcp`）、代码里的模块名都还叫
> `memory_core`，只有**注册到客户端的显示名字**改成了 Spomory——这两者是
> 独立的：`command` 字段指向哪个可执行文件决定实际跑什么代码，
> `mcpServers` 这个 JSON 对象里的键才是 Claude Desktop/Cursor 界面上显示、
> 以及日志文件命名（`mcp-server-<键名>.log`）用的名字。改名时两处都要跟着
> 改，否则日志文件名和显示名字对不上，排查问题时容易搞混。

## 工具一览

| 工具 | 参数 | 功能 |
|---|---|---|
| `add_memory` | `text`, `source_id="mcp-session"` | 从一段文本里抽取事实（实体+关系）写入记忆图谱，返回新增/合并的实体数和新增关系数 |
| `search_memory` | `query`, `top_k=10` | 先做三元组匹配，再用 Personalized PageRank 在图上扩展排序，组装成一段自然语言上下文返回 |
| `forget_memory` | `query` | 找到与查询语义最匹配的**一条**关系并物理删除；删除后若某个端点实体变成孤立节点也一并清理，并写入审计日志。每次只删一条是故意的保守设计——模糊的查询应该改用更具体的措辞重试，而不是一次性删掉多条 |
| `get_graph` | `entity_name`, `hops=1` | 返回以某实体为中心、指定跳数内的子图，JSON 格式（`entities` + `relations`） |
| `export_memory` | `subject_id="default"` | 把整个记忆图谱导出成 JSON 格式的"记忆护照"（memory passport），对应"数据自主权"承诺 |

## 安装

```bash
uv pip install "memory-core[llm,embedding,mcp] @ git+https://github.com/<org>/<repo>.git"
# 或本地开发：
uv pip install -e ".[llm,embedding,mcp]"
```

## 配置

设置以下环境变量（默认走 OpenAI；国产 OpenAI 兼容 API 只需换
`LLM_BASE_URL`/`LLM_MODEL`）：

```bash
export LLM_API_KEY=...
export LLM_BASE_URL=https://api.deepseek.com   # 可选，默认 OpenAI
export LLM_MODEL=deepseek-v4-flash             # 可选，默认 gpt-4o-mini
export EMBEDDING_MODEL=BAAI/bge-m3             # 可选，默认 bge-m3
```

**存储后端**（Epic 8.2）：不设置 `DATABASE_URL` 时默认用本地 SQLite
（`memory_core.sqlite3`）；设置了就自动切换到 Postgres 云端后端
（`memory_core/mcp_server/server.py::_select_store_from_env()`），接口行为
完全一致，已用 `tests/test_postgres_mcp_parity.py` 验证过：

```bash
export DATABASE_URL=postgresql://user:pass@host:5432/dbname   # 可选
```

## 启动

```bash
memory-core-mcp
```

## 接入 Claude Desktop / Cursor

### ⚠️ macOS 上不要把运行时装在 `~/Documents`（或 Desktop/Downloads）下

**真实踩过的坑**：如果 `command` 指向 `~/Documents/<project>/.venv/...`，
Claude Desktop 启动 MCP Server 子进程时会报 `Server disconnected`，日志
（`~/Library/Logs/Claude/mcp-server-<name>.log`）里能看到：

```
Fatal Python error: init_import_site: Failed to import the site module
...
PermissionError: [Errno 1] Operation not permitted: '.../.venv/pyvenv.cfg'
```

根因是 macOS 的 TCC（隐私保护）机制：`~/Documents`、`~/Desktop`、
`~/Downloads` 这几个文件夹默认对没有被显式授权"完全磁盘访问权限"的
App 及其子进程是保护起来的，Claude Desktop spawn 出的 MCP Server 进程
拿不到这个授权，连 Python 启动时读自己 venv 目录下的 `pyvenv.cfg` 都会被
拒绝——**这和代码本身、和项目仓库放哪里没关系，纯粹是这几个特殊文件夹
的系统级限制**。

**解决办法**：把 MCP Server 实际运行用的虚拟环境装在 `~/Documents`
之外的普通目录（比如 `~/mcp-servers/`），用**非 editable**方式安装
（这样运行时不需要再回头读项目仓库里的源码）：

```bash
mkdir -p ~/mcp-servers
uv venv --python 3.11 ~/mcp-servers/memory-core-venv
uv pip install "/path/to/memory-core[llm,embedding,mcp]" \
    --python ~/mcp-servers/memory-core-venv/bin/python
```

项目仓库本身（源码开发）留在哪里都无所谓，只有**这个专门给 Claude
Desktop 用的运行时副本**需要挪到 `~/Documents` 之外。以后改了代码想让
Claude Desktop 用上最新版本，重新跑一遍上面这条 `uv pip install` 命令
（不带 `-e`）覆盖安装即可。

### 配置

在 `claude_desktop_config.json`（macOS 路径：
`~/Library/Application Support/Claude/claude_desktop_config.json`）里加
一段。`mcpServers` 下面这个键（下例中的 `"Spomory"`）就是 Claude
Desktop 界面上显示的名字，可以按自己喜好改，但**改了之后要连带把下面
"排查方法"里提到的日志文件名一起换**，两者是绑定的。`command` 写上面
那个**非 Documents 路径**虚拟环境里 `memory-core-mcp` 的绝对路径——注意
这个可执行文件名不用跟着显示名字改，它是包安装时固定生成的入口——Claude
Desktop 启动子进程时也不一定继承你终端的 `PATH`，绝对路径最不容易出问题：

```json
{
  "mcpServers": {
    "Spomory": {
      "command": "/Users/<you>/mcp-servers/memory-core-venv/bin/memory-core-mcp",
      "env": {
        "LLM_API_KEY": "...",
        "LLM_BASE_URL": "https://api.deepseek.com",
        "LLM_MODEL": "deepseek-v4-flash"
      }
    }
  }
}
```

如果这个 JSON 文件里已经有别的键（比如 Claude Desktop 自己的其他偏好
设置），只在顶层加 `mcpServers` 这一个键，不要动其他内容——改之前建议
先复制一份备份。改完配置后完全退出并重新打开 Claude Desktop 才会生效。

### Cursor

Cursor 用同样结构的 MCP 配置文件：全局配置在 `~/.cursor/mcp.json`，只想
对单个项目生效则放在项目根目录的 `.cursor/mcp.json`。内容和上面 Claude
Desktop 的 JSON 完全一样（同样是 `mcpServers.Spomory` 这个键决定 Cursor
里显示的名字），改完重启 Cursor 生效。这部分**没有在真实 Cursor 环境里
测试过**（开发/验证机器上没装 Cursor），只是基于 Cursor 官方 MCP 配置文档
的结构类比得出，接入后建议按下面"验证步骤"再实测一遍确认。

### 数据文件存放位置

本地 SQLite 数据文件（图谱数据 + 用量统计）默认存在 `~/.memory-core/`
（`MEMORY_CORE_DATA_DIR` 环境变量可以改)——这也是特意选的一个不在
Documents/Desktop/Downloads 下的普通目录，同样是为了避开上面那个 TCC
限制，而不是依赖进程启动时的当前工作目录（GUI App 拉起子进程时的 cwd
往往不可预测）。

**静态加密默认开启（Epic 11.2）**：`memory_core.sqlite3` 里每条实体/关系
存的都是密文，不是明文——第一次启动时会在同一个目录下自动生成一个
`encryption.key`（权限 600），之后每次启动复用这同一个 key。这个 key 就放
在数据库文件旁边，不是进了什么密钥管理系统——对单用户本地工具来说，
威胁模型是"数据库文件/备份被人拿到"，不是"这台机器整个被攻破"（那种情况
下不管 key 放哪都保不住）。**如果你是从加密上线之前的旧版本升级**：第一
次用新版本启动时会自动检测到旧的明文数据库，就地迁移成加密版本，原文件
会先备份成 `memory_core.sqlite3.pre-encryption-backup`（迁移后不会自动
删除，确认新数据库没问题后可以自己删掉）——不会丢数据，也不需要手动做
任何操作。

**验证步骤**（照着做一遍，10 分钟内应该能跑通）：

1. 打开 Claude Desktop，新建对话，确认输入框附近的 Connectors/MCP 工具
   列表里能看到 `Spomory` 已连接（没连上通常是 `command` 路径写错，或者
   环境变量里 `LLM_API_KEY` 没填）。
2. 让 Claude 调用 `add_memory` 写入一句话，比如"请调用 Spomory 的
   add_memory 工具，记住：我在某某公司做后端开发"。
3. 开一个新对话（或者接着问），让 Claude 调用 `search_memory` 查"我在哪里
   工作"，确认能检索到第 2 步写入的内容。
4. 让 Claude 调用 `forget_memory`，比如"请调用 Spomory 的 forget_memory
   工具，忘记我在某某公司做后端开发这件事"，然后重复第 3 步的查询，确认
   已经查不到刚才那条记忆了。
5. 如果想验证云端后端（Epic 8.2），把 `env` 里加一条 `DATABASE_URL`
   指向 Postgres，重启 Claude Desktop，重复第 2-4 步，确认行为一致。

**排查方法**：如果 Claude Desktop 提示 "Server disconnected"，真实的报错
（不是那句笼统的断连提示）在 `~/Library/Logs/Claude/mcp-server-Spomory.log`
里（文件名跟着 `mcpServers` 里的键名走，改了显示名字后日志文件名也会跟
着变）——先看这个文件，上面那个 TCC 权限问题就是从这里诊断出来的。

## 远程接入（API Key，Epic 11.5，可选）

上面全部内容讲的是本地 stdio 版——免注册、数据留在自己电脑，继续是默认推荐的
接入方式。如果你不想在自己电脑上装 Python 环境（比如想直接从手机/网页版
Claude 连，或者要接入国内"魔搭 MCP 广场"这类只收远程 HTTPS 端点的平台），
`src/memory_core/mcp_server/remote.py` + `src/cloud_api/` 提供了第二种、走
API Key 鉴权的远程接入方式，同样的五个工具，行为一致，区别只是：

- 每个用户的记忆存在共享 Postgres 数据库里的一张按 `user_id` 隔离的图
  （`PostgresGraphStore(dsn, user_id)`），不是本地 SQLite 文件。
- 鉴权靠 API Key（`x-api-key` 请求头），不是完整 OAuth——够用但达不到
  Anthropic 官方 Connector 目录的准入要求（那边需要 OAuth 2.1 + PKCE），
  这条线目标是魔搭/豆包这类只要求可访问 HTTPS 端点的平台。

### 部署

```bash
uv pip install "memory-core[llm,embedding,mcp,cloud] @ git+https://github.com/yliuai/spomory.git"

export DATABASE_URL=postgresql://user:pass@host:5432/dbname   # 必填，没有本地 SQLite 兜底
export LLM_API_KEY=...
export MCP_ALLOWED_HOSTS=memory.example.com,memory.example.com:443  # 必填，见下面的安全说明
export CORS_ALLOWED_ORIGINS=https://spomory.yliuai.com  # 可选，默认就是这个值
export PORT=8000  # 可选，默认 8000

memory-core-mcp-remote
```

**`MCP_ALLOWED_HOSTS` 必须设置成部署后真实对外的域名/端口**（逗号分隔，支持
`host:*` 通配端口）：这是 MCP SDK 自带的 DNS-rebinding 防护，检查请求的
`Host` 头，不在允许列表里直接返回 421——不设置的话不是"默认放行"，而是
默认拒绝所有请求（宁可部署完连不上也不留一个隐性允许所有 Host 的后门），
已经用一个假 Host 头的本地烟雾测试验证过这个行为（见下面"验证状态"）。

**`CORS_ALLOWED_ORIGINS` 是单独一层放行**，跟上面 `MCP_ALLOWED_HOSTS`/
`MCP_ALLOWED_ORIGINS` 管的 MCP 传输层 Origin 校验是两回事——那一层校验
不会给响应加 CORS 头，浏览器发起的 `fetch()` 请求（比如官网的注册表单）
仍然会被浏览器自己挡住，跟这台服务本身返回什么无关。`create_app` 新增
`cors_allowed_origins` 参数，给 `/users/register` 这类普通 HTTP 路由加
`Access-Control-Allow-Origin`；不设置时行为跟之前完全一样（CORS 完全
关闭），不会默认放开成 `*`。逗号分隔可以放多个来源。

### 使用

```bash
curl -X POST https://memory.example.com/users/register \
  -H "Content-Type: application/json" -d '{"email": "you@example.com"}'
# 响应里的 api_key（mck_ 开头）只在这一次返回，记下来
```

Claude Desktop/Cursor 里配一个远程 MCP 连接（具体 JSON 结构以客户端当前
文档为准），`url` 填 `https://memory.example.com/mcp-apikey`，请求头带上
`x-api-key: <上面拿到的 key>`。

**同一个邮箱可以重复调用这个接口**：会解析到同一个账号（`user_id` 不变），
但每次都会签发一把新 Key——弄丢了 Key 就再调一次拿新的，不需要单独的
找回流程；旧 Key 在被显式吊销前继续有效。加了基础限流防止脚本刷（同一
邮箱每小时最多 5 次、同一 IP 每小时最多 20 次，超出返回 429）。

**这个接口本身没有验证邮箱所有权**——响应直接把 Key 返回给调用方，填谁
的邮箱就能拿到谁账号的 Key，限流防不住"专门填别人邮箱"这种针对性滥用。
自己敲 curl 用自己的邮箱没问题，但**不要把这个接口直接接到公开网页表单
上**。

### 邮箱验证版注册（给公开网页表单用）

```bash
curl -X POST https://memory.example.com/users/register/request \
  -H "Content-Type: application/json" -d '{"email": "you@your-real-domain.com"}'
# 响应只是"去查邮件"的提示，Key 不在这次响应里

# 点开邮件里的链接（GET /users/register/verify?token=...），
# 打开的网页上才会显示 Key
```

**这里必须换成一个真实能收信的邮箱，不能照抄 `you@example.com`**——发信
服务商（这里用的是 Resend）会拒绝往 `example.com`/`example.org` 这类
RFC 2606 保留的"文档示例"域名发信，返回 503。这不是猜测：这个坑真的
在部署验证时踩到过一次（当时因为没有捕获 `email_sender.send()` 的异常，
表现是裸的 500），已经修成捕获后返回带清晰提示的 503——用 503 不用 502，
是因为这台服务部署在 Cloudflare 后面，生产环境实测确认 Cloudflare 会把
源站返回的 502/504 响应体整个替换成它自己的通用错误页，我们精心写的
提示信息压根传不到调用方手上，503 才能完整透传。但踩中的前提（用占位
域名）本身还是会发生，所以文档示例直接换掉这个域名，不能只指望报错
信息说清楚。

跟上面的区别：Key 只会在点开邮件链接之后才签发和展示，没收到邮件、没
点链接就拿不到 Key，从根上解决了"填别人邮箱换到别人的 Key"这个问题。
`register_or_reissue_key` 内部逻辑跟直接版一样（同邮箱同账号、每次发新
Key），只是多了邮箱验证这一步。部署上需要设置 `RESEND_API_KEY`/
`EMAIL_FROM`（不需要额外开 OAuth 才能用这一组接口，两者是独立的）；
`PUBLIC_BASE_URL` 可选，默认复用 `OAUTH_ISSUER_URL`（同一个域名的情况下
不用单独设置）。

### 不在这条线里的东西

- Origin 请求头校验（Anthropic 官方 Connector 目录另一项要求，跟 OAuth
  分开做，见下一节的范围说明）。
- 把这台服务实际暴露到公网、域名/证书/防火墙——这些是你自己部署时要做的
  运营决定，这里只提供代码和本地验证。
- 本地↔云端记忆双向同步——本地 stdio 版和这条远程版目前是两个独立的
  分发渠道，不共享数据。

## OAuth 2.1 接入（对齐 Claude 官方 Connector 目录）

上面的 API Key 接入方式够用于魔搭这类平台，但 Anthropic 官方 Connector
目录硬性要求 OAuth 2.1 + PKCE，纯 API Key 会被拒。这是第三种、单独的接入
方式——跟 API Key 版是两个不同的挂载路径（`/mcp-apikey` 走 API Key，
`/mcp` 走 OAuth），两者背后是同一份记忆图谱（同一个 `user_id`
解析到同一个 Postgres 存储），不是两套数据。

**为什么 API Key 版反而叫 `/mcp-apikey`，OAuth 版占了 `/mcp` 这个名字**：
真正会被提交到 Anthropic 官方目录、在市场里被搜索/一键连接的是 OAuth 版，
而目录里公开的 Connector URL 习惯上都以 `mcp` 结尾——所以把这个"好名字"
留给了对外展示的那一个；API Key 版的地址只会被手动粘贴进各个客户端自己
的配置文件，不会被任何人在市场里搜索到，命名上没有这层外部约束。

### 为什么不能挂在同一个端点上

`mcp` SDK 只要给 `MCPServer` 配了 `auth_server_provider`，就会给这个挂载
点的**所有**请求强制套一层 `RequireAuthMiddleware`——没带合法的
`Authorization: Bearer` 直接 401，工具代码根本不会被调用到。也就是说
一旦在同一个挂载点上开 OAuth，现有纯 `x-api-key` 的客户端（Cursor、魔搭、
`mcp-remote`）会全部失效。所以做法是另开一个独立挂载路径专门给走官方
目录审核的客户端用。

### `/mcp` 只是 Connector URL（工具调用的端点），不是授权发生的地方

**`/mcp` 是 MCP 客户端连接、实际调用 `add_memory`/`search_memory`
这些工具时用的那个 URL**（对应 OAuth 术语里的"resource server"）。真正的
授权流程——`/authorize`、`/token`、`/register`、`/.well-known/oauth-
authorization-server` 这些端点——**在域名根路径下**，不是 `/mcp`
底下（比如 `https://api.example.com/authorize`，不是
`https://api.example.com/mcp/authorize`）。

这不是随便选的：`mcp` SDK 生成这些 URL 时是直接拿 `issuer_url` 字符串
拼接固定路径（`mcp/server/auth/routes.py` 里
`str(issuer_url).rstrip("/") + "/authorize"` 这样的写法），完全不知道
这个 ASGI 应用实际被挂载在哪——而这个项目里 `issuer_url` 配的是不带路径
的域名根（`https://api.example.com`），所以这些端点必须真的能在根路径
下访问到。**这是开发过程中一次真实踩到的坑**（当时 OAuth 挂载点的路径
还叫 `/mcp-oauth`，后来因为要满足"Connector URL 以 mcp 结尾"这个约定
才改名成 `/mcp`，坑本身和改名是两件独立的事）：最初的实现把整个 OAuth
配置过的 MCPServer 都挂在这个前缀下面，结果 `/authorize`/`/token`/
`.well-known` 这些也被一起嵌套进了同一个前缀底下——metadata 文档里写的
是 `https://host/authorize`，但这个路径实际只存在于
`https://host/<前缀>/authorize`，真实的 OAuth 客户端按 metadata 文档去
发现端点时会直接 404。修法是把这个 ASGI 应用挂在 FastAPI 根路径
（`app.mount("/", ...)`），用它自己内部的 `streamable_http_path="/mcp"`
来把工具调用端点单独放到 `/mcp`，让 `/authorize` 等端点自然落在根路径。
回归测试见 `tests/test_oauth_mount_routing.py`（含一个专门验证
`/mcp-apikey` 和 `/mcp` 两个挂载点同时存在、互不干扰的用例）。

### 登录方式：邮件 Magic Link

OAuth 的 `/authorize` 需要一个真人证明身份的步骤，项目里没有密码系统，
用的是邮件魔法链接：填邮箱 → 收一封带一次性链接的邮件 → 点开链接才真正
生成 OAuth 授权码、跳回发起连接的客户端。发信走
[Resend](https://resend.com)（不是自己用 VPS 走裸 SMTP——新服务器的出站
IP 没有发信声誉，很容易被邮件服务商拉黑）。

### 部署新增的环境变量

在原有 `memory-core-mcp-remote` 的环境变量基础上加这几个（不设置
`OAUTH_ISSUER_URL` 时 OAuth 挂载点整个不会启用，现有 API Key 部署不受
影响）：

```bash
export OAUTH_ISSUER_URL=https://api.example.com          # 必填，启用 OAuth 的开关
export OAUTH_RESOURCE_SERVER_URL=https://api.example.com/mcp  # 可选，默认按 issuer 拼
export RESEND_API_KEY=re_...    # 去 Resend 官网注册账号拿，域名验证也要在那边做
export EMAIL_FROM="Spomory <noreply@example.com>"
```

### Origin 请求头校验 + RFC 8707 资源（audience）校验

这两项后来都补上了（`create_app`/`SpomoryOAuthProvider` 新增
`allowed_origins`/`resource_url` 参数）：

- **Origin 校验**：查 Anthropic 官方"Testing your connector"文档才发现，
  这不是审核 checklist 里"必须实现"的一条，反而是故障排查里提醒
  "配得太严会把 Claude 自己的请求也拒掉"的一个坑——留空白名单意味着任何
  带 Origin 头的请求都会被拒，这本身就是一种过严配置。修法是加
  `MCP_ALLOWED_ORIGINS` 环境变量（默认 `https://claude.ai`），只放行这一个
  已知合法来源，不放宽对其他任意网站的防护；没带 Origin 头的请求（多数非
  浏览器 MCP 客户端都是这样）不受影响。
- **RFC 8707 resource/audience 校验**：`SpomoryOAuthProvider` 新增
  `resource_url` 参数，`load_access_token` 现在会校验 token 的 `resource`
  声明（如果客户端发了的话）是否匹配这台服务器自己的资源 URL，用规范形式
  比较（`rstrip("/").lower()`）而不是逐字节比较——这是为了防止一个为
  别的服务签发的 token 被拿到这里重放。`resource` 缺失时不视为不匹配
  （这个参数本来就是可选的），刷新 token 时也会保留原始 resource。
  同时确认了 RFC 9728 protected-resource metadata 端点
  （`/.well-known/oauth-protected-resource/mcp`）本来就正常工作。

回归测试见 `tests/test_oauth_store.py`（四个 resource/audience 场景）和
`tests/test_oauth_mount_routing.py`（`test_origin_allowlist_admits_the
_configured_origin_and_rejects_others`）。测试过程中发现两个测试设计上的
坑：辅助路由（`.well-known/*`）根本不受 `TransportSecuritySettings`
保护，只有真正的 MCP 资源端点 `/mcp` 受保护；不带真实有效 Bearer token
的请求会被 `RequireAuthMiddleware` 先一步 401 掉，Origin 校验的 403 根本
轮不到，测 Origin 必须先用 Provider 真实签发一个有效 token。

### 不在这次范围内

- 实际去 Anthropic 开发者后台提交 Connector 审核——这是运营动作，等这次
  代码在真实部署上跑通一次真实 Claude Desktop 的浏览器授权流程之后再做。
- 密码找回/账号设置这类更完整的用户账户体系——魔法链接够用于登录这一件
  事，没有做更大的账户体系。

## 验证状态

- **代码 + 单元测试**：已完成。`tests/test_mcp_server.py` 用官方 `mcp` SDK
  （v2，`MCPServer`）的 `list_tools()` 验证五个工具都正确注册，另有专门测试
  验证 `forget_memory` 删除匹配关系、清理孤立实体、写入审计日志三件事；`server.py`
  的检索/写入逻辑复用了已经用真实 LLM+embedding 验证过的 Epic 1/2 pipeline
  （见 `tests/test_e2e_real_llm.py`），存储后端在本地 SQLite 和云端 Postgres
  之间的切换也做了功能对等性验证（`tests/test_postgres_mcp_parity.py`）。
- **Epic 6.2 要求的"连接 Claude Desktop/Cursor 做真实端到端验证"**：已在
  真实 Claude Desktop 里跑通，包括改名为 Spomory 之后的回归验证——
  `mcp-server-Spomory.log` 里能看到真实的 `tools/call`，DB
  （`~/.memory-core/memory_core.sqlite3`）里能看到 `add_memory` 真实写入
  的新关系，紧接着的 `search_memory` 调用也正常触发了 embedding 检索。
- **`forget_memory` 真实验证**：在 Claude Desktop 里说"记住：我养了一只叫
  小白的猫"，抽取出了两条关系（`我-养了-猫`、`猫-叫-小白`）；接着说"忘记我
  养猫这件事"，`forget_memory` 只删除了语义最匹配的那一条（`猫-叫-小白`及
  孤立后的实体`小白`），`我-养了-猫`原样保留——这正是设计上"每次只删一条
  最匹配的关系"的保守行为，不是 bug，但意味着一句话如果被抽取成多条关系，
  可能需要多次调用 `forget_memory`（用更具体的措辞）才能彻底清干净。
  数据库和 `memory_core_audit.sqlite3` 的审计记录
  （`{"entities_deleted": 1, "relations_deleted": 1}`）都核实了这个行为。
  Cursor 未在本机测试过（未安装），接入步骤见上面"Cursor"一节。

- **远程接入（Epic 11.5）——诚实的验证状态**：`PostgresGraphStore` 加
  `user_id` 隔离、`cloud_api/app.py` 挂载 MCP streamable-http 端点这两块，
  已经用不需要 Postgres 的部分验证过：
  - 用假请求（`TestClient`，本地 `LocalGraphStore` 而非远程用的
    `PostgresGraphStore`）跑通了 `/users/register` → `/mcp` 的 `initialize`
    握手全流程，包括中途发现并修上的两个真实 bug：(1) FastAPI/Starlette
    默认不会把生命周期事件传给 `app.mount()` 挂载的子应用，导致 MCP 的
    session manager 没启动、所有工具调用报
    `RuntimeError: Task group is not initialized`——修法是在 `create_app`
    里手动把子应用的 `lifespan_context` 包进主应用的 `lifespan`；
    (2) MCP SDK 自带的 DNS-rebinding 防护默认拒绝所有 `Host` 头，加了
    `allowed_hosts`/`MCP_ALLOWED_HOSTS` 这条配置项才能连上，两个问题都是
    先复现报错、看 SDK 源码定位、再修，不是凭经验猜的。
  - `tests/test_postgres_store.py` 新增的跨租户隔离测试、
    `tests/test_remote_mcp_server.py`（API Key 鉴权失败/两个用户互相看不到
    对方记忆/用量与审计记录按真实 `user_id` 落盘）都写好了。
  - **2026-09 更新：已经实际部署到公网并验证过**——腾讯云服务器
    （Ubuntu 24.04）+ postgresql 16 + nginx + systemd，域名走 Cloudflare
    代理。上面那几个 Postgres 依赖的测试文件已经在这台服务器的真实
    Postgres 上跑通，公网 `POST /users/register` 和 `POST /mcp/`（真实
    `initialize` 握手）都用真实域名验证过，不是回环测试。部署过程中还
    真实踩到并修复了 Cloudflare "Automatic SSL/TLS" 模式探测源站 443
    导致连接悬挂超时的问题（改成 Flexible 模式解决）。还没做：拿真实
    Claude Desktop/Cursor 客户端连（只用 curl 模拟过 MCP 协议），提交到
    魔搭 MCP 广场。

- **OAuth 2.1 接入——诚实的验证状态**：`SpomoryOAuthProvider` 的全部
  Protocol 方法（客户端注册、`authorize`→pending 记录、授权码签发与
  一次性消费、access/refresh token 签发/校验/轮换/吊销）在
  `tests/test_oauth_store.py` 里单独测过；`/oauth/login`→`/oauth/verify`
  这条魔法链接登录的完整 HTTP 流程在 `tests/test_oauth_login_flow.py`
  里用假的 `EmailSender` 跑通过（真实发信没测，Resend 账号还没配）；
  `remote.py` 解析 OAuth token 得到 `user_id` 这一步（`get_access_token()`
  这个 contextvar 机制）在 `tests/test_remote_oauth_context.py` 里单独
  测过，完整"真实 Postgres + OAuth Bearer token 调 add_memory/
  search_memory"端到端流程在 `tests/test_remote_mcp_server.py` 里也已经
  对着上面那台真实服务器的 Postgres 跑通了。这个过程里也真实发现并修好了
  一个路由挂载 bug——`/mcp-oauth` 最初把整个 OAuth 配置过的 MCPServer 都
  挂在这个前缀下面，导致 `/authorize`/`/token`/`.well-known` 这些端点也
  被一起嵌套进 `/mcp-oauth/` 底下，但 SDK 生成 metadata 文档时是按不带
  路径的 `issuer_url` 拼出 `https://host/authorize` 这样的 URL，实际
  却只存在于 `https://host/mcp-oauth/authorize`——真实客户端按 metadata
  发现端点会直接 404。这是本机测试没测到、被追问"`/mcp-oauth` 到底是不是
  Connector URL"时才回头验证 HTTP 路由才发现的，修复后加了专门的回归
  测试 `tests/test_oauth_mount_routing.py`（4 个用例都验证真实 HTTP 路径
  而不是内部 Python 对象），已经重新在真实 Postgres 上跑过确认修复有效。
  之后又根据"Connector URL 应该以 mcp 结尾"这个真实市场惯例，把 OAuth
  挂载点从 `/mcp-oauth` 改名成 `/mcp`，API Key 版让位改成 `/mcp-apikey`
  ——重新加了一个专门验证两个挂载点同时存在互不干扰的用例，也在真实
  Postgres 上跑过。

  **2026-09 更新：真实起了服务、真人走完了完整流程，确认可用。**
  真实注册了 Resend 账号并配了 `OAUTH_ISSUER_URL`/`RESEND_API_KEY` 部署上去，
  过程中又发现并修了两个真实 bug：登录邮件里的链接原来是相对路径，邮件
  客户端没有"当前页面"可解析，点开变成把"oauth"当裸主机名；`/oauth/verify`
  拼最终跳转 URL 用的是暴力字符串拼接，客户端自己的 callback URL 如果本来
  就带查询参数（MCP Inspector 确实如此）会拼出畸形 URL。都已修复，见
  `运维.md`的完整记录。修完之后遇到的第四个问题不是我们的代码：MCP
  Inspector 用 `sessionStorage`（不跨标签页共享）追踪 OAuth 流程，邮件
  链接默认新开标签页导致追踪信息丢失——这是 Inspector 自身的架构限制
  （真实 Claude Desktop 走系统级深链接，不会有这个问题），绕过方法是把
  链接粘贴回原来的标签页而不是直接点开。用这个方法真实连上后，
  `add_memory`/`search_memory` 都调用成功，写入的数据在生产 Postgres 里
  核实过确实落在了正确的 `user_id` 下，验证完清理了测试数据。

  **2026-09-06 追加：Origin 请求头校验 + RFC 8707 audience 校验也补上并
  部署验证过了。** 详见上面"Origin 请求头校验 + RFC 8707 资源（audience）
  校验"一节；生产环境额外做了一次 SQLite schema 迁移（`oauth_access_tokens`/
  `oauth_refresh_tokens` 表补 `resource` 列，迁移前备份了原文件），迁移和
  部署后用 `test_oauth_store.py`/`test_oauth_login_flow.py`/
  `test_oauth_mount_routing.py`/`test_remote_oauth_context.py`/
  `test_remote_mcp_server.py` 一起对着生产 Postgres 重新跑通过（27 个用例
  全过），本地全量测试（116 passed, 17 skipped）和 `ruff check` 也全过。
  **还没做**：实际去 Anthropic 开发者后台提交 Connector 审核。
