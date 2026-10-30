# 来源与实验范围

live/ 中的请求、回答、补丁及测试记录来自一次本地 Qwen3.5 27B 无思考开发运行。
其中 Click 源码摘录来自 pallets/click，固定 commit 为
`934813e4d421071a1b3db3973c02fe2721359a6e`，保留 [BSD-3-Clause 许可证](LICENSE-click.txt)。
任务来源为 [Click #3887](https://github.com/pallets/click/issues/3887)；公开检查依据报告者预期，不代表上游已认可的完整规范。

offline/ 是对前一轮已冻结请求的离线重建，没有新增模型调用；Token 为请求估算。
validation/ 中的 Docker 用例使用脚本响应，真实模型调用为零。
本次通过仅限约定的 1 项目标与 3 项正常行为检查，无独立隐藏评分或上游完整套件验收。

implementation.patch 相对于运行计划中记录的 Git HEAD，包含运行时未提交的模块绑定读取及请求视图改动。
文件哈希用于一致性核对，不是第三方认证。
