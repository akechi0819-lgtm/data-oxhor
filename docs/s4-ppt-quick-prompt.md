# S4 Quick PPT 宿主提示词

适用于 Codex 和 DeepSeek Harness 的同一份提示词。将尖括号路径替换为当前运行路径。

```text
分析已经冻结。你现在只负责在 Quick Generate 项目中编写 SVG 页面，不重新查询、不重新分析、不启动 Default Generate。

输入：
- 冻结分析 JSON：<analysis_frozen.json>
- 冻结分析 Markdown：<analysis_frozen.md>
- Quick 项目：<project_path>

Quick 项目必须先由宿主运行。命令 JSON 输出的 `project` 是上游实际创建的项目路径；后续只使用该路径，不要猜测或手工创建目录：

tools/run_s4_local.sh quick-ppt prepare <project_path> --analysis <analysis_frozen.json> --markdown <analysis_frozen.md> --evidence-root <evidence_dir>

硬约束：
- 只使用冻结分析及其 evidence 清单中的证据。
- 不使用 FY27 前台日报、教务数据或教务 Bridge；当前主线只使用现金明细与工单证据。
- 不启动 Confirm UI、Stage 1/2、Live Preview、Design Spec、Spec Lock、first-page checker 或 finalize_svg。
- 不使用网络、图片、音频、旁白、Web UI；Quick `finalize` 会拒绝 SVG 中的图片、远程或内嵌资源、事件和动画元素。任务需要这些能力时改走 Default。
- 普通数据汇报默认不生成 Speaker Notes、动画和外部资源。
- 只在确实生成数据驱动图表时，按 ppt-master 的 verify-charts 规则完成一次图表验证。

请在 svg_output/ 中按页面顺序直接写完所有 SVG。完成后调用项目入口：

tools/run_s4_local.sh quick-ppt finalize <prepare 返回的 project 路径>

入口会运行最终 SVG checker 和 Quick PPTX exporter。只在 checker 报 blocking error 时集中修复后再调用一次；advisory warning 不触发重复检查。不要自行重复运行 checker，也不要混入 Default 产物或确认状态。
```

复杂任务才走 Default：用户要求模板或人工确认，使用图片/旁白/讲稿/复杂动画，或明确要求 Live Preview/视觉标注时，按 ppt-master Default 路线完整执行。不要先启动 Default 再中途切换 Quick。
