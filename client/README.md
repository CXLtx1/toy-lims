# toy-lims Windows 仪器客户端

本目录包含两个独立发布的 Windows 仪器客户端：XRF 自动同步客户端和标准数值仪器快速录入客户端。

```text
client/
├── docs/
│   ├── CLIENT_ARCHITECTURE.md   # 总体架构、接口和实施阶段
│   └── OXSAS数据库说明.md       # 已验证的 OXSAS 数据库资料
├── xrf/                         # .NET 10 WPF XRF 自动同步客户端
└── standard/                    # .NET 10 WPF 标准仪器快速录入客户端
```

两种客户端分别打包，标准客户端不携带 OXSAS 或 SQL Server 依赖。两者均提供主窗口和置顶小浮窗。
