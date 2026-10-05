# UU ZeroTier Bypass for macOS

让 UU 远程避开本机 ZeroTier 虚拟网卡，保留 SSH、ping 等其他程序的 ZeroTier 通信。

**实验性工具。** 已在 macOS 15.3.1、UU 远程 4.39.1 的一个环境中验证。它阻止 UU 使用 ZeroTier 路径，后续连接可能是 UU 自己的 P2P 或中继，不能保证 P2P。

## 为什么需要它

UU 远程可能把 ZeroTier 虚拟地址当作局域网候选。如果 ZeroTier 对端实际上通过中继通信，UU 的“LAN”连接仍可能受到中继带宽、延迟和丢包影响。关闭 ZeroTier 会影响 SSH 等应用，因此这个工具只针对 UU 在虚拟网卡上使用的端口。

仅拦出站连接可能不够：对端能够通过 ZeroTier 反向连接 UU 的监听端口。本工具同时处理进站和出站。

## 原理

1. 根据配置中的**本机 ZeroTier IPv4**，自动寻找对应的 `feth` 网卡。
2. 使用 `lsof` 查询 UU 的 TCP/UDP 本地端口，再用 `proc_pidpath` 确认进程位于配置的应用包中。
3. 根据网卡的 IPv4 地址和掩码识别 ZeroTier 网段，在 PF 的独立 anchor 中拦截 UU 与该网段的双向流量。
4. 对经 Surge 等 VIF 代理转发的连接，额外追踪 UU 正在连接的 ZeroTier 对端 IP/端口，覆盖代理改写本地端口后的路径。规则不只依赖数据包经过 `feth` 接口。
5. 周期性更新规则，适应 UU 每次连接时变化的端口。
6. 使用 `launchd` 在开机时运行；正常停用时移除本工具的规则，释放自己的 PF 启用引用。

这里使用的是“进程 → 端口 → PF 规则”的映射，PF 本身并不是按应用身份过滤。规则涵盖自动识别的 ZeroTier IPv4 网段，不需要填对方设备的 IP。无需修改 Surge 配置。

## 环境要求

- macOS，已安装 ZeroTier 与 UU 远程。
- 管理员权限，用于操作 PF 与安装启动项。
- 可工作的 `/usr/bin/python3`，仅使用 Python 标准库。部分 Mac 需要先安装 Apple Command Line Tools 才能使用这个解释器。
- 当前实现发现 `feth` 接口，并以一个本机 IPv4 定位它。IPv6 专用接口、多个 ZeroTier 网络与其他远控软件尚未验证。

## 配置

仓库直接提供 `config.json`，下载后编辑它即可：

```json
{
  "local_zerotier_ipv4": "192.0.2.10",
  "uu_app_path": "/Applications/UURemote.app",
  "poll_interval_seconds": 0.5,
  "process_name_prefix": "UURemote"
}
```

| 参数                      | 填什么                                                      |
| ----------------------- | -------------------------------------------------------- |
| `local_zerotier_ipv4`   | **这台 Mac 自己的** ZeroTier IPv4。`192.0.2.10` 是文档示例，安装前必须替换。 |
| `uu_app_path`           | UU 的应用包路径，通常保留默认值。                                       |
| `poll_interval_seconds` | 查询间隔，默认 0.5 秒，允许 0.2–10 秒。间隔增大会降低查询频率，也会延长新端口的发现时间。      |
| `process_name_prefix`   | 用于寻找 UU 进程的名称前缀，通常保留 `UURemote`。                         |

公开仓库的 `config.json` 使用通用文档 IP，不包含作者的本机地址。只需填写使用者自己的 ZeroTier IPv4；无需提供 Planet 地址、Network ID、身份密钥或对端 IP。准备提交改动时，请将私人配置恢复为通用值。

如果希望另存一份不被 Git 跟踪的个人配置，可使用 `config.local.json`，安装时运行 `sudo ./scripts/install.sh ./config.local.json`。

## 安装与开关

```sh
sudo ./scripts/install.sh
sudo ./scripts/control.sh status
```

安装程序会将代码、配置复制为管理员拥有的系统文件，并启用开机启动。它使用固定服务名称；重复安装也会升级同名的旧版本。

```sh
sudo ./scripts/control.sh stop     # 停止服务，关闭开机启动
sudo ./scripts/control.sh start    # 启动服务，恢复开机启动
sudo ./scripts/control.sh restart  # 重新启动已加载的服务
sudo ./scripts/uninstall.sh        # 停止并卸载，保留诊断日志
```

修改仓库的 `config.json` 后重新执行安装命令，更新安装的配置。修改配置文件不会自动生效。

## 验证

1. 用 UU 建立一个新的远程会话，观察其 P2P/中继/LAN 状态。
2. 运行 `control.sh status`，确认端口规则存在且包匹配计数增长。
3. 同时通过 ZeroTier 地址使用 SSH，并检查少量 ping，确认其他应用仍正常。
4. 停用服务后对比连接行为；再启用并重新连接 UU。

UU 没有选择 LAN 并不能单独证明完全没有 ZeroTier 流量，应结合 PF 计数与必要的抓包判断。当前环境在隔离后观察到 UU 自身的 UDP 中继，SSH 与 ping 保持可用。用户另行确认方案有效。

## 日志与安装位置

```sh
sudo tail -n 30 /Library/Logs/UUZeroTierIsolation/events.log
```

- 程序与配置：`/Library/Application Support/UUZeroTierIsolation/`
- 启动项：`/Library/LaunchDaemons/local.uu-zerotier-isolation.plist`
- PF anchor：`local.uu-zerotier-isolation`
- 运行状态：`/var/run/uu-zerotier-isolation/`

日志包含接口和端口信息；提交 issue 前请自行脱敏。

## 已知限制

- 这是轮询方案，新端口在下次查询前可能发送少量数据，不能作为严格的应用安全隔离。
- 其他应用复用相同本地端口并与该网段通信，或访问 UU 当前连接的同一对端 IP/端口时，可能受到影响。
- 规则按 IPv4 网段与端口匹配。如果其他物理网络使用同一网段，也可能匹配这些规则。
- 不能改善校园网 NAT、修复 ZeroTier 打洞，或保证 UU 使用 P2P。
- PF 是全系统组件。程序会在当前主过滤规则前挂载自己的 anchor，使用 `pfctl -R` 更新主过滤规则，并保留读取到的其他过滤规则；它不是完全不触碰主规则的方案。其他 VPN/防火墙同时修改 PF 时可能存在冲突或竞争，应在自己的环境验证。
- 如果其他服务替换了主规则，辅助程序会退出清理，随后由 launchd 重启。多个 PF 管理程序持续互相覆盖时应停用本工具。
- 异常强制终止可能留下规则或引用；正常停止有清理流程，下一次启动也会尝试清理同名的残留。卸载脚本会检查 anchor 是否已移除。

## License

MIT。详见 [LICENSE](LICENSE)。

## 开发检查

在 macOS 上运行 `python3 -m unittest discover -s tests -v`。回归用例覆盖应用通过 VIF 地址连接 ZeroTier 对端的场景，以及公共网络连接、非 UU 进程不会被收集的情况。
