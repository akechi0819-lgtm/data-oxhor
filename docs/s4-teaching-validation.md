# S4 历史教务验证

本文件只记录已完成的 S3.5 教务跨端口验证背景。`customers/s4_teaching_validation/` 是本机历史临时工作区，由 `.gitignore` 忽略，不是正式客户系统，也不进入版本控制。当前 S4 只使用主线 `company_bridge.v1_2_0` 对应的现金明细与工单数据；不得向该工作区或主线冻结分析增加教务数据。

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

历史工作区曾使用 `company_id=s4_teaching_validation` 和 `snapshot_id=snapshot_s4_teaching_20260816_01` 执行向导与 Data Foundation 验证。其输入文件只读复制，原始桌面文件不移动、不覆盖。该记录不授权新建、更新或交付教务 Bridge。

初始验证还使用 `tests/fixtures/s4_teaching_fixture.py` 生成的脱敏 XLSX。fixture 和 Snapshot 只在测试临时目录中生成，不能替代真实教务数据，也不能作为客户事实。

当前 PPT 交付路由、Quick 冻结身份清单与双宿主验收要求以 [接入指南](./integration-guide.md)、[运维手册](./operator-runbook.md) 和 [S4 Quick PPT 宿主提示词](./s4-ppt-quick-prompt.md) 为准。本历史工作区不生成新 PPT，不导入现金/工单以外的数据，也不构成当前交付证据。
