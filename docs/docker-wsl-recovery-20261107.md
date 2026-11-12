# Docker / WSL 本机恢复记录（2026-11-07）

**结果：未重启 Windows，Docker 已恢复，Langfuse 历史记录可读；本次模型调用为 0。**

Docker 的 `docker-desktop` 发行版此前处于 `Uninstalling`，终止操作返回 `WSL_E_DISTRO_NOT_FOUND`。WSL 服务恢复后，该注册状态仍未解除。本记录只描述此次已核对路径的本机操作，不是可直接套用的通用修复步骤。

## 授权与数据边界

用户明确同意仅注销并恢复 `docker-desktop` **运行发行版**；未授权重置 Docker、注销其他发行版或删除数据盘。

- 运行盘：`D:\Users\admin\AppData\Local\Docker\wsl\DockerDesktopWSL\main\ext4.vhdx`，118,489,088 字节（约 118 MB）。
- 独立数据盘：`D:\Users\admin\AppData\Local\Docker\wsl\DockerDesktopWSL\disk\docker_data.vhdx`，113,322,754,048 字节（约 113 GB）。该盘未被注销或删除，也未完整备份。
- 注销前核对注册项仅指向 `main`，检查路径祖先无目录重解析点，并验证运行盘备份 SHA256：`E1AE35914228821EE3F9F070173714CDE34BF3FB0318915D5A914DFDACD17DD6`。
- 注销、导入两个阶段前后的数据盘长度及修改时间一致；这不是数据盘内容完整性证明，也不代表后续正常启动不会写入数据。

## 实际恢复

1. 保持 Docker 停止，完成小运行盘、发行版注册信息和 Docker 配置备份。
2. 执行 WSL 关闭，仅注销已核对的 `docker-desktop`，确认旧注册项与运行盘移除。
3. 从备份恢复运行盘，重新校验 SHA256，再通过 `wsl --import-in-place` 注册。
4. 确认注册项仍指向原 `main`：`Version=2`、`State=1`、`Flags=15`、`DefaultUid=0`，随后启动 Docker。

两个变更阶段分别留证。先前一次因 PowerShell 自动转换 JSON 日期类型，导致字符串时间比较误判，脚本在变更前停止；核对 UTC 时间刻度一致后改用刻度比较。该次失败记录保留，没有覆盖为成功记录。

## 恢复验收

| 检查 | 结果 |
| --- | --- |
| WSL / Docker | `docker-desktop` 为 Running；Docker 服务端版本 28.1.1 |
| 原沙箱镜像 | `corecoder-test-sandbox:v1` 的 ID 与原记录一致：`sha256:b26ab495fcf2ae0473cd4a9a7430700697e9041cdbe3fd4c6d2238274319b219` |
| 现有清单 | 可见 13 个容器、9 个卷；Langfuse 所需 5 个卷均存在 |
| Langfuse | 6 个服务运行检查通过；Web、数据库依赖、项目认证和 Worker 健康探针通过 |
| 历史数据 | Trace `d7c51ad49dc9f0586d36fceac5897d2e` 回读成功，共 7 个节点 |

这些结果支持 Docker 重新识别既有镜像、卷和部分历史业务数据；不等同于所有数据完成完整性校验。历史 Trace 回读也不能证明新事件入库。本次没有执行 35 份保存补丁的容器回放，不据此宣称沙箱代码变更已通过真实容器验收。

## 证据与备份

以下路径均位于 `D:\project_other\CoreCoder`，保留本地原件；配置和注册信息备份不作为可公开证据包。

- 备份目录：`.tmp/sandbox-transport-20261107/runtime-backup-20261107-154556/`；含 `manifest.json`、运行盘、注册信息、配置备份及路径检查。
- 成功注销记录：上述目录的 `recovery-unregister-20261107-085630-680.json`。
- 成功导入记录：上述目录的 `recovery-import-20261107-085650-890.json`。
- 运行检查：`.tmp/sandbox-transport-20261107/recovery-health-first.json`。
- 镜像、容器及卷清单：`.tmp/sandbox-transport-20261107/docker-restored-inventory.json`。
- Langfuse 探针与历史回读：`.tmp/sandbox-transport-20261107/langfuse-after-recovery.json`。
