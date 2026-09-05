# toy-lims 服务端

本目录保存 Flask + PostgreSQL LIMS 的服务端代码和 Web 页面；SQLite 保留用于测试与旧库迁移。

## 运行

从项目根目录运行（兼容原来的命令）：

```powershell
python server.py
```

也可以直接运行服务端入口：

```powershell
python server/run.py
```

开发模式：

```powershell
python server/app.py
```

安装依赖：

```powershell
python -m pip install -r server/requirements.txt
```

PostgreSQL 连接集中配置在 `app.py` 的 `POSTGRES_CONFIG`，也可用 `LIMS_DATABASE_URL` 覆盖；表结构、旧库升级和种子数据位于 `db_schema.py`，数据库兼容层位于 `db_backend.py`。旧 `lims.db` 仅作迁移源/回退档案，`migrate_to_postgres.py` 默认只迁移 `RY28888` 及其关联业务记录，同时保留全部配置。PostgreSQL 请使用 `pg_dump` 或数据库服务器快照备份。在 `app.py` 中启用 `REQUEST_LOG_ENABLED` 后，请求日志写入 `server/logs/requests.log` 并按日永久保留。反向代理部署时设 `LIMS_TRUST_PROXY=1` 读取 `X-Forwarded-For` 真实来源 IP（直连部署不要开启）；该开关同时让 Waitress 放行本机反代转发的 `X-Forwarded-For/Proto`（Waitress 3.x 默认会剥掉它们，这是“配置都对但审计 IP 仍是 127.0.0.1”的常见病根）。仪器客户端的"本机放行"判定同样基于来源 IP，代理模式下跨机器客户端必须正确配置设备令牌。

## Linux 部署（systemd）

假设代码部署在 `/home/lims/labflow`（本目录平铺，`run.py` 在根），Python 环境在 `/home/lims/labflow/venv`。系统级与用户级两种方式任选其一，不要同时启用。

### 系统级服务（推荐，需要 sudo）

`/etc/systemd/system/labflow.service`：

```ini
[Unit]
Description=LabFlow LIMS
After=network.target

[Service]
Type=simple
User=lims
WorkingDirectory=/home/lims/labflow
Environment=LIMS_DATABASE_URL=postgresql://用户:密码@主机/toy_lims
Environment=LIMS_TRUST_PROXY=1
Environment=LIMS_XRF_CLIENT_TOKEN=XRF客户端令牌
Environment=LIMS_STANDARD_CLIENT_TOKEN=标准客户端令牌
ExecStart=/home/lims/labflow/venv/bin/python run.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now labflow
sudo systemctl restart labflow   # 改代码或环境变量后
journalctl -u labflow -f         # 查看日志
```

注意：修改 unit 文件（包括 Environment）后必须先 `daemon-reload` 再 `restart`，否则新配置不生效。

### 用户级服务（不需要 sudo）

`~/.config/systemd/user/labflow.service`（`%h` 自动代表当前用户家目录）：

```ini
[Unit]
Description=LabFlow LIMS
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/labflow
Environment=LIMS_DATABASE_URL=postgresql://用户:密码@主机/toy_lims
Environment=LIMS_TRUST_PROXY=1
Environment=LIMS_XRF_CLIENT_TOKEN=XRF客户端令牌
Environment=LIMS_STANDARD_CLIENT_TOKEN=标准客户端令牌
ExecStart=%h/labflow/venv/bin/python run.py
Restart=always

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now labflow
loginctl enable-linger $USER     # 关键：否则用户登出后服务会被停止
systemctl --user restart labflow
journalctl --user -u labflow -f
```

迁移命令：

```powershell
python server/migrate_to_postgres.py --dry-run
python server/migrate_to_postgres.py --replace
```

## 认证

浏览器先选择标准、个人或管理入口。普通终端使用终端密码登录，可以浏览和打印；写请求需要通过右下角窗口输入唯一的用户密码，授权在最后一次成功写操作 2 分钟后失效。个人入口默认对所有启用用户开放，无需创建或选择终端，使用用户名和用户密码登录，整个会话按该真实用户的能力执行并记录审计。管理终端使用终端密码登录且无需用户授权，其修改以管理终端身份记录。旧数据库升级后会进入一次性终端初始化页，验证现有管理员密码后设置“二组”和“管理终端”的密码。

顶部独立“用户”页维护用户和普通、管理两类实体终端，并通过上移、下移调整登录页顺序；个人入口不需要管理。用户权限采用继承式可组合能力，不使用固定角色：操作者不能授予自己没有的能力，也不能修改权限高于自己的账号。用户和终端密码只要求非空，不限制最短长度。终端接口为 `GET/POST /api/terminals`、`PUT /api/terminals/<id>` 和 `PUT /api/terminals/<id>/order`；服务器禁止停用当前终端，并保证至少保留一个启用的管理终端。

## XRF 仪器

XRF 客户端通过 `GET /api/instrument/xrf/tasks` 领取待测样品，通过 `POST /api/instrument/xrf/import` 上传含批次的全量定量结果，并通过 `POST /api/instrument/xrf/status` 上报状态心跳。跨机器调用需要配置 `LIMS_XRF_CLIENT_TOKEN` 并在 `X-Instrument-Token` 请求头中提供同一令牌。普通定量和 UniQuant 新扫描均保存为未关联，不使用样品名或客户端 `sample_id` 自动匹配。浏览器仪器页通过 `GET /api/xrf/monitor` 查看、搜索全部扫描，并通过 `PUT /api/xrf/analyses/<id>/sample` 手工关联，通过同一路径的 `DELETE` 请求解绑；数据页也提供相同操作。数据库限制每个样品最多关联一条扫描，升级时历史重复关联只保留最新一条。关联和解绑需要 `result_edit` 能力并记录审计。

## 标准数值仪器

标准客户端通过 `GET /api/instrument/standard/instruments` 获取可绑定仪器，通过 `POST /api/instrument/standard/authorize` 使用具备“检测数据录入”权限的用户密码建立 10 分钟活动会话。后续任务、开始测量和提交请求通过 `X-User-Authorization` 提供会话令牌。`GET /api/instrument/standard/tasks?instrument_id=<id>` 获取该仪器当前开放录入的样品、元素和既有读数，`POST /api/instrument/standard/samples/<id>/start` 开始测量，`POST /api/instrument/standard/submit` 原子提交一批新读数。每批使用 `client_id + submission_id` 幂等去重，状态和读数审计使用实际登录用户。跨机器调用还需要配置 `LIMS_STANDARD_CLIENT_TOKEN`，客户端在 `X-Instrument-Token` 请求头提供同一设备令牌。

客户端通过 `POST /api/instrument/standard/status` 上报心跳。网页仪器页显示最近 60 秒在线的标准客户端、来源 IP、当前用户和该终端最近一次录入摘要。

Web 页面通过 SSE 接口 `GET /api/events` 实时接收审计修订号推送（数据变化毫秒级到达，修订号同时仍以 `/api/site-status` 提供，浏览器每 15 秒轮询兜底），仅在数据变化时刷新当前业务页；仪器监控页另以 2 秒周期更新客户端心跳和扫描记录。输入控件获得焦点时会暂缓自动重绘，避免覆盖正在填写的内容。SSE 连接基于 `audit_logs` 最大 id（即修订号）判断变化，含心跳保活，断开后浏览器自动重连；每个连接常驻一个 Waitress 线程，线程数由 `LIMS_THREADS` 控制（默认 32）。

Web 顶部“审计”页集中显示最近 500 条审计记录，可按关键词、动作和对象类型过滤；终端登录、仪器心跳及标准客户端登录等动作使用中文名称展示。

设置页在同一面板维护定容容量与二次稀释方式。来样和样品模板的定容容量使用下拉选项，新建溶样默认 `250 mL`；停用其他容量不会改写历史样品。

标准单值协议支持 `ppm`、`ppb`、`percent` 和 `ph` 仪器；需要变量表单的 `function` 滴定任务继续使用网页数据页。

## 性能与缓存

- **响应压缩**：超过 1KB 的可压缩响应（HTML/CSS/JS/JSON/CSV 等）自动 gzip；SSE 流不压缩。带 `?v=` 版本号的静态资源返回一年不可变缓存，其余静态资源缓存一天。
- **报告 payload 缓存**：`cached_report_payload()`（`app.py`）对 `/api/report/<id>` 及 Excel 报告、结果矩阵、手工补录、单位切换校验等同源调用做进程内缓存，命中时零数据库查询（单次冷计算实测数百毫秒）。缓存最多 512 条、10 分钟兜底 TTL。
- **失效与重算**：所有数据变更都通过本进程的非 GET 接口写入，请求提交完成后 `invalidate_report_payload_cache` 立即作废全部缓存，保证读取不返回旧数据；作废时登记此前缓存过的样品，后台线程（`_report_cache_rebuild_loop`）在写入静默 30 秒后自动重算这些样品，写入代数（generation）防护避免把并发写入前的旧计算结果存回缓存。
- **启动预热**：`run.py` 在服务启动后以后台线程调用 `warm_report_cache()`，把全部已有样品的报告 payload 逐个算好，存量样品首次展开即秒开。

## 边界

- `app.py`：HTTP API、数据库配置和报告计算。
- `db_schema.py`：表结构、旧 SQLite 升级、种子数据和初始化。
- `db_backend.py`：PostgreSQL/SQLite 连接与 SQL 兼容层。
- `migrate_to_postgres.py`：旧 SQLite 的筛选迁移与核验。
- `run.py`：Waitress 正式入口；仅 SQLite 模式启动旧在线备份，并以后台线程预热报告缓存。
- `templates/`、`static/`：浏览器端 LIMS。
- `tests/`：现有服务端测试。
- 仪器客户端不得直接连接 PostgreSQL 或 `lims.db`，统一通过 HTTP API 通信。
