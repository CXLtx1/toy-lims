# 标准仪器客户端

面向 ICP-OES、ICP-MS、AAS、离子电极和 pH 等数值型仪器的快速录入客户端。

## 功能

- 按 LIMS 仪器下载当前开放录入的样品和待测元素。
- 主窗口完整展示样品、溶样、已有平行读数和新读数。
- 置顶小浮窗提供相同的紧凑输入能力，草稿与主窗口实时同步。
- 主窗口默认隐藏已有读数的项目，可按需查看；浮窗始终只显示尚无读数且可录入的项目。
- 已制样 / 未测量样品可在主窗口由当前用户确认开始测量。
- 输入后自动勾选，`Enter` 跳到下一项，`Ctrl+Enter` 直接提交当前已勾选读数。
- 一次提交中的全部读数由服务端在同一事务中保存。
- 每批提交带唯一编号，网络重试不会重复创建读数。
- 用户使用 LIMS 密码登录，连续 10 分钟没有录入操作后需重新登录。
- 每 3 秒检查一次待测任务变化；仅数据发生变化时重绘列表，避免打断正在输入的读数。终端在线状态每 10 秒上报一次。
- LIMS 地址、设备令牌和绑定仪器由程序目录中的配置文件固定，操作人员不能在界面修改。

公式滴定任务暂不进入单值录入客户端，仍在网页数据页使用对应变量表单。

## 运行

```powershell
dotnet run --project "client/standard/ToyLims.StandardClient.csproj"
```

在可执行文件同目录创建或修改 `standard-client.json`：

```json
{
  "ServerUrl": "http://127.0.0.1:5000",
  "Token": "",
  "InstrumentId": 2
}
```

`InstrumentId` 必须对应 LIMS 中的 `ppm`、`ppb`、`percent` 或 `ph` 仪器。远程访问时，服务端设置 `LIMS_STANDARD_CLIENT_TOKEN`，配置中的 `Token` 填写相同内容；本机 `127.0.0.1` 联调可留空。

登录用户必须处于启用状态并具备“检测数据录入”权限。程序不会保存用户密码或用户会话到配置文件。

## 发布

```powershell
dotnet publish "client/standard/ToyLims.StandardClient.csproj" -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -o "client/standard/publish/win-x64-single"
```

目标电脑需要安装 .NET 10 Desktop Runtime。
