# Dashboard Product 开发交接文档

## 项目背景

Dashboard Product 是从原有的 `dashboard/` 模块重构而来，主要改进包括：
- 引入绩效月概念（26日至次月25日）用于个人业绩统计
- 分离业务组（自然月）和个人（绩效月）的聚合逻辑
- 改用日级数据进行灵活聚合，支持更准确的同比计算
- 重构 HTML 渲染逻辑，提升可维护性

## 项目结构

```
dashboard_product/
├── README.md                               # 项目说明
├── DASHBOARD_DEVELOPMENT_PREREQUISITES.md  # 开发前置条件
├── refresh.py                              # 核心数据处理脚本
├── render_template.py                      # HTML 模板渲染
├── config/
│   ├── people.json                         # 人员配置
│   ├── project_targets.json                # 目标配置
│   └── saved_queries.json                  # 查询配置
├── docs/
│   ├── CURRENT_STATUS.md                   # 当前开发状态
│   └── PENDING_ISSUES.md                   # 待解决问题
└── tests/
    └── test_render.py                      # 渲染测试
```

## 核心概念

### 绩效月 (Performance Month)

**定义**: 每月26日到次月25日为一个绩效月

**计算逻辑** (`refresh.py:date_to_perf_month()`):
```python
def date_to_perf_month(dt):
    """
    将日期转换为绩效月字符串
    绩效月: 当月26日 ~ 次月25日
    例: 2024-01-26 到 2024-02-25 → "2024-02"
    """
    if dt.day >= 26:
        # 26日及以后算下个月的绩效月
        next_month = dt + timedelta(days=32)
        return next_month.strftime('%Y-%m')
    else:
        # 25日及之前算当月绩效月
        return dt.strftime('%Y-%m')
```

**适用范围**: 
- ✅ **仅用于个人业绩统计**
- ❌ **不用于业务组、团队层级**

### 自然月聚合

**定义**: 按日历月份聚合（1月就是1月1日至31日）

**适用范围**:
- ✅ **业务组 (Business Group)**
- ✅ **团队 (Team)**
- ❌ **不用于个人层级**

**实现位置**: `refresh.py:project()` 函数
```python
# 业务组使用自然月
bus_monthly[bus][str(dt)[:7]] += ...

# 个人使用绩效月
per_monthly[person][date_to_perf_month(dt)] += ...
```

## 数据聚合逻辑

### 时间维度
- **日 (Daily)**: SQL 查询返回日级数据
- **月 (Monthly)**: 
  - 业务组: 自然月 `YYYY-MM`
  - 个人: 绩效月 `YYYY-MM`
- **季度 (Quarterly)**: `Q1/Q2/Q3/Q4`
- **年度 (Yearly)**: `YYYY`

### 聚合流程

1. **SQL 层**: 返回日级明细数据
   - 位置: `customers/bi_operations/Work/SavedQueries/dashboard_actuals/v6/query.sql`
   - 字段: `dt`, `business_group`, `person`, `cash_revenue`, `work_orders` 等

2. **Python 层**: 按不同维度聚合
   - 业务组 → 自然月 → 季度 → 年度
   - 个人 → 绩效月 → 季度 → 年度

3. **渲染层**: 生成 HTML 表格和图表
   - 位置: `render_template.py`
   - 输出: `index.html` + `artifact.json`

## 关键问题记录

### 已解决

#### 1. JavaScript 语法错误
**现象**: 页面空白，控制台报错 `Uncaught SyntaxError: Unexpected token ')'`

**原因**: `render_template.py:renderPeopleDetail()` 函数第539-544行代码重复

**解决**: 删除重复代码行

#### 2. 业务组数据不匹配
**现象**: 业务组 Q1 显示 91.8万，实际应该是 220万+

**原因**: 错误地对业务组应用了绩效月逻辑

**解决**: 
```python
# 修改前（错误）
bus_monthly[bus][date_to_perf_month(dt)] += ...

# 修改后（正确）
bus_monthly[bus][str(dt)[:7]] += ...
```

**用户原话**: "绩效月这个约束只在个人的那个范围里有用。我他妈的6~8月那就是自然月6~8月。"

### 待解决

#### 1. 历史同比数据差异 ⚠️

**现象**: 
- 看板显示去年 Q1: 132.1万
- 用户反馈数据不准确

**待验证**:
- 使用现金表原始查询对比
- 检查同比日期范围计算
- 验证新老生、被动收入等过滤条件

**相关代码**: `refresh.py:project()` 同比计算部分

## 开发环境配置

### 依赖
```bash
pip install duckdb jinja2 pandas
```

### 数据仓库位置
```
/Users/akechi/Desktop/manager -CowH/customers/bi_operations/
├── Work/
│   └── SavedQueries/
│       └── dashboard_actuals/v6/
│           ├── query.sql
│           └── manifest.json
└── Output/
    └── Dashboard/
        └── run_dashboard_product_YYYYMMDD_*/
```

### 运行脚本
```bash
cd /Users/akechi/Desktop/manager\ -CowH/dashboard_product
python refresh.py
```

### 输出文件
- `artifact.json`: 元数据（生成时间、版本等）
- `index.html`: 可视化看板页面

## 配置文件说明

### people.json
```json
{
  "人员姓名": {
    "business_group": "业务组名称",
    "team": "团队名称",
    "targets": {
      "2024": 1000000,  // 年度目标（元）
      "2024-Q1": 250000  // 季度目标（元）
    }
  }
}
```

### project_targets.json
```json
{
  "业务组名称": {
    "2024": 5000000,
    "2024-Q1": 1250000
  }
}
```

### saved_queries.json
```json
{
  "dashboard_actuals": {
    "version": "v6",
    "path": "customers/bi_operations/Work/SavedQueries/dashboard_actuals/v6",
    "description": "日级业绩数据查询"
  }
}
```

## 测试验证

### 手动测试清单
1. ✅ 生成看板无错误
2. ✅ 页面正常渲染
3. ✅ JavaScript 无报错
4. ✅ 业务组数据使用自然月聚合
5. ✅ 个人数据使用绩效月聚合
6. ⚠️ 历史同比数据准确性（待验证）

### 回归测试要点
- 绩效月边界日期（25日/26日）处理正确
- 跨年绩效月计算正确（例：2023-12-26 → 2024-01）
- 季度聚合正确（Q1: 1-3月，Q2: 4-6月等）
- 同比计算考虑闰年和实际天数

## 代码审查要点

### refresh.py
- `date_to_perf_month()`: 绩效月计算逻辑
- `project()`: 核心聚合函数
  - `bus_monthly`: 业务组自然月数据
  - `per_monthly`: 个人绩效月数据
  - 季度、年度聚合逻辑

### render_template.py
- `renderPeopleDetail()`: 个人明细表
- `renderBusinessGroupSummary()`: 业务组汇总表
- JavaScript 代码无语法错误
- HTML 模板变量替换正确

## 常见问题 (FAQ)

**Q: 为什么业务组不用绩效月？**  
A: 绩效月是为了统计个人业绩而设计的。业务组和团队的汇报通常按自然月进行，使用绩效月会导致数据与财务报表不一致。

**Q: 如何验证数据准确性？**  
A: 对比 SQL 原始查询结果和看板显示数据，特别注意日期边界和过滤条件。可以使用现金表 (cash table) 进行交叉验证。

**Q: 如何添加新的人员？**  
A: 编辑 `config/people.json`，添加人员信息和目标配置，然后重新运行 `refresh.py`。

**Q: 调试产物如何清理？**  
A: 删除 `Output/Dashboard/run_dashboard_product_*` 目录中的临时输出。保留最终版本即可。

**Q: SQL 查询修改后如何更新？**  
A: 修改 SQL 后需要更新 `manifest.json` 中的 `sha256` 和 `sql_sha256` 哈希值，确保版本一致性。

## 移交清单

- [x] 代码提交到 Git
- [x] 编写开发状态文档
- [x] 编写交接文档
- [x] 清理调试产物
- [x] 记录待解决问题
- [ ] 解决历史数据差异（需进一步调查）
- [ ] 完整的数据验证测试
- [ ] 单元测试编写

## 联系与支持

如需了解更多信息：
- 查看 `CURRENT_STATUS.md` 了解最新开发状态
- 查看 `PENDING_ISSUES.md` 了解待解决问题
- 查看 `README.md` 了解基本使用方法
- 查看 Git 提交历史了解变更记录

---

**交接日期**: 2026-09-04  
**交接人**: Claude Opus 5  
**项目状态**: 功能开发完成，待数据验证
