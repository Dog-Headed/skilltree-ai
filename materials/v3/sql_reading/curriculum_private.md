# SQL 小课程：逐目标普通评分量规

版本：day13-sql-curriculum-2。assessment_private，仅用于本次两个节点的出题及评分。
这是首次实际出题审查后补充的课程量规；没有改写旧卷或六类固定参考答案。

## 普通目标与关键误解的区别
普通目标均为required，使用项目冻结的0.8达标线；required并不等于critical。
以下普通分项的RubricCriterion.critical为false。部分满足按已满足子项给分，不要求全满分。
学生没有解释或只说不知道：相应项0分、证据不足，不能仅据此称作关键误解。
明确声称SELECT/WHERE会永久删除或改写原表，才属于已定义的关键误解；须引用实际作答。
若一道题同时考普通理解与关键误解，不把整个普通评分项设成必须满分；按实际陈述标注severity。

## SELECT节点：三个普通分项
select_rows_name_set：满分4，critical=false。姓名集合Yan、Lin、Mei完整3分；无ORDER BY不保证顺序1分。等价排列接受。
select_columns_only_name：满分4，critical=false。仅name列2分；明确id/age不在输出各1分。
select_readonly_original：满分4，critical=false。查询不改原表2分；保留id/name/age三列1分；保留三行原值1分。

## WHERE节点：四个普通分项
where_result_set：满分4，critical=false。Lin与Mei各1分；排除Yan1分；结果不多不少1分。顺序不限。
where_boundary_equivalent：满分4，critical=false。18包含1分，17排除1分，正确解释>=1分，18<=age等价1分。
where_readonly_original：满分4，critical=false。只筛选结果不删改原表2分，原表三列三行及原值保留2分。
select_vs_where：满分4，critical=false。SELECT控制输出列2分，WHERE控制哪些行满足条件2分。

上述满分可随出题的明确分项同比缩放，但不得扩大为本主题未涉及的执行、JOIN、NULL或写操作能力。
