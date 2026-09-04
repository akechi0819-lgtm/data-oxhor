# Dashboard Product - 当前开发状态

**更新日期**: 2026-09-04  
**当前版本**: v0.1.0  
**状态**: 功能开发完成，待数据验证

## 概述

Dashboard Product 是用于生成业绩看板的 Python 工具，支持团队和个人的业绩数据展示，包含现金收入、工单量等核心指标，支持同比分析和目标完成率跟踪。

## 核心功能

### 1. 绩效月逻辑
- **绩效月定义**: 每月26日至次月25日为一个绩效月
- **适用范围**: 仅用于个人业绩统计
- **实现位置**: `refresh.py:date_to_perf_month()`

### 2. 自然月聚合
- **适用范围**: 业务组（business group）和团队层级数据
- **聚合逻辑**: 按日历月份进行聚合（6-8月就是自然月6-8月）
- **实现位置**: `refresh.py:project()` 函数中的 `bus_monthly` 字典

### 3. 数据聚合层级
- **业务组层级**: 使用自然月聚合 (`str(dt)[:7]`)
- **个人层级**: 使用绩效月聚合 (`date_to_perf_month(dt)`)
- **季度/年度**: 基于天级数据聚合，无月度中间层

### 4. 同比计算
- **逻辑**: 基于实际天数计算同比，考虑闰年和日期差异
- **实现**: SQL 查询返回日级数据，Python 层进行灵活聚合

## 已完成工作

### 代码实现
- ✅ 实现绩效月计算函数 `date_to_perf_month()`
- ✅ 分离业务组和个人的聚合逻辑
- ✅ 实现 HTML 仪表板渲染 (`render_template.py`)
- ✅ 修复 JavaScript 语法错误（重复代码行539-544）
- ✅ SQL 查询返回日级数据支持灵活聚合

### 配置文件
- ✅ `config/people.json` - 人员配置
- ✅ `config/project_targets.json` - 目标配置
- ✅ `config/saved_queries.json` - 保存的查询配置

### 测试验证
- ✅ 前端渲染正常显示
- ✅ 业务组自然月数据正确（Q1: 220万+）
- ✅ JavaScript 无语法错误
- ✅ 页面交互功能正常

## 待解决问题

### 1. 历史同比数据差异
**问题描述**: 
- 去年 Q1 数据显示为 132.1万
- 用户反馈该数据不准确
- 需要使用现金表（cash table）查询验证

**排查方向**:
- 对比现金表原始流水数据
- 检查同比计算的日期范围是否正确
- 验证数据过滤条件（新老生、被动收入等）

**相关文件**:
- `customers/bi_operations/Work/SavedQueries/dashboard_actuals/v6/query.sql`
- `refresh.py:project()` 函数的同比逻辑

### 2. SQL 查询优化
**当前状态**: SQL 返回日级数据，在 Python 层聚合
**优化空间**: 评估是否需要在 SQL 层预聚合以提升性能

## 技术架构

### 数据流
```
SQL Query (DuckDB)
    ↓ 返回日级数据
Python refresh.py
    ↓ 聚合计算
    ├─ 业务组: 自然月
    └─ 个人: 绩效月
render_template.py
    ↓ 生成 HTML
Output/Dashboard/
```

### 关键函数
- `date_to_perf_month(dt)`: 日期转绩效月字符串
- `project(query_result, targets, people)`: 核心聚合逻辑
- `renderPeopleDetail(person, data)`: 个人明细表渲染

### 依赖
- DuckDB: 数据查询
- Python 3.x: 数据处理
- Jinja2-like 模板: HTML 生成

## 开发环境

### 运行方式
```bash
cd /Users/akechi/Desktop/manager\ -CowH/dashboard_product
python refresh.py
```

### 输出位置
```
/Users/akechi/Desktop/manager -CowH/customers/bi_operations/Output/Dashboard/
└── run_dashboard_product_YYYYMMDD_**/
    ├── artifact.json
    └── index.html
```

### 调试模式
- 生成带 `_final` 后缀的输出目录表示最终版本
- 中间调试产物应及时清理

## 数据验证清单

- [ ] 验证去年 Q1 历史数据准确性
- [ ] 确认同比计算逻辑与线上看板一致
- [ ] 检查新老生、被动收入筛选条件
- [ ] 验证绩效月边界日期（25/26日）处理正确性
- [ ] 对比多个业务组数据确保自然月聚合正确

## 已知限制

1. **绩效月适用范围**: 仅个人层级使用绩效月，业务组和团队必须使用自然月
2. **月度聚合**: 当前系统只保留绩效月这一个月度维度，无自然月的月度聚合
3. **历史数据**: 依赖 SQL 查询返回的历史数据准确性

## 下一步建议

1. **优先**: 解决去年 Q1 数据差异问题
2. 完成全面的数据验证测试
3. 编写单元测试覆盖绩效月计算逻辑
4. 添加数据质量检查脚本
5. 性能优化评估（如需要）

## 联系人

如有问题，请参考：
- 代码仓库: `/Users/akechi/Desktop/manager -CowH/dashboard_product/`
- 前置条件文档: `DASHBOARD_DEVELOPMENT_PREREQUISITES.md`
- 待解决问题: `docs/PENDING_ISSUES.md`
