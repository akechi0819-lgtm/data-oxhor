# S4 教务临时工作区

S4 的教务验收使用项目内的临时工作区 `customers/s4_teaching_validation/`。该目录由 `.gitignore` 忽略，只能保存本机运行副本，不是正式客户系统，也不进入版本控制。

```text
customers/s4_teaching_validation/
├── Input/
│   ├── Data/
│   │   ├── schedule_main/          # 2026.9-2027.3配课表.xlsx
│   │   ├── schedule_study_abroad/  # 20260715-20270331留学预备配课表.xlsx
│   │   └── teacher_priority/       # 教师优先级.xlsx
│   └── Reference/
├── Work/
└── Output/
```

工作区初始化时使用 `company_id=s4_teaching_validation`，并用固定的 `snapshot_id=snapshot_s4_teaching_20260816_01` 执行向导的 `init`、`sync-data`、`start`；随后使用 Data Foundation CLI 对当前 warehouse 执行 `describe` 和 `quality`。输入文件只读复制到对应来源槽位，原始桌面文件不移动、不覆盖。正式教务 Bridge 只能在候选经过人工确认后生成，未确认映射不得用于交付。

初始验证还使用 `tests/fixtures/s4_teaching_fixture.py` 生成的脱敏 XLSX。fixture 和 Snapshot 只在测试临时目录中生成，不能替代真实教务数据，也不能作为客户事实。

PPT 交付遵循通用会话合同：宿主根据自然语言需求选择直接回答、表格/查询结果或 PPTX，不使用固定教务月报结构或页序。缺少工作时间、请假和通勤事实时，当前未占用时段只能称“候选空档”，不能称“真实可用时间”。首轮验收关闭自动更新、外部研究、生图、TTS、旁白和本地 Web 辅助界面，只验证本地数据、可编辑 PPTX 和可回查数字。首轮只能通过 `tools/run_s4_local.sh` 启动受限命令；它以白名单环境运行并不继承宿主凭据，随后由 `tools/s4_ppt_preflight.py` 检查依赖。任务仍必须明确禁止网络、外部素材、旁白和本地 Web UI。直接运行预检时，只要发现非空的图像、模型、语音或网页服务凭据就失败。
