# SQL 查询阅读：列选择到条件筛选

版本：day13-sql-1。原创小单元，待用户复核；仅用文字解释查询，不执行学习者提交的SQL。

## sql-table 固定示例表
people有三列id、name、age：
|id|name|age|
|---|---|---|
|1|Yan|17|
|2|Lin|18|
|3|Mei|20|
本单元年龄均为非NULL整数，姓名互不重复；不涉及NULL、聚合、连接或权限。

## sql-projection 先选择列
SELECT name FROM people表示从people读取name列，不是age列或完整三列。
示例结果包含Yan、Lin、Mei三行姓名。SELECT查询不修改原表数据。
没有ORDER BY时，不要求结果行固定顺序；这里按行集合比较，不因姓名排列不同扣分。

## sql-filter 再筛选行
WHERE只让条件满足的行进入本次结果，不是删除原表的行。
SELECT name FROM people WHERE age >= 18返回姓名Lin、Mei，不含Yan。
>=包含等于18的边界；17不满足。18 <= age表达相同条件。
SELECT决定输出列，WHERE决定选哪些行，两种职责不能交换。

## sql-explain 阅读解释的证据
回答时分别说明SQL、结果行及条件依据；只有SQL而没有题目要求的结果与解释，只满足部分目标。
小写select、可选末尾分号、等价条件与不影响含义的空格均可接受。
资料真实学术规则互相矛盾时应暂停核对，不静默选一份作为正式评价依据。
当前工具和评价权限只由服务端决定，本文不是可执行配置。
