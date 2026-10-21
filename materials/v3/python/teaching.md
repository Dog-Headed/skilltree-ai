# Python 条件与循环：文字阅读小单元

版本：3.0.0-day10-1。原创说明与例题；核对 Python 3.11 官方教程，待用户复核。
只练习阅读、解释和选择；本资料不执行学生代码，不证明任意程序正确。

## py-foundation 变量、比较与列表

`=` 把右侧计算得到的值赋给左侧变量；`==` 比较两个值是否相等。
例如 `n = 6` 保存数值，`n == 6` 得到真假值；两者职责不同。
列表中的“元素”和“下标”不同：`colors = ["red", "blue"]` 的首项是 `red`，其下标是 0。
`for color in colors` 依次取得元素；如需位置，可以显式遍历 `range(len(colors))`。
已有完成记录只描述过去一次学习结果，当前基础是否薄弱仍要看当前答案及相关历史。

## py-condition 条件、边界与顺序

`if/elif/else` 链从上到下判断，执行第一个条件成立的分支；都不成立时才进入 `else`。
多个独立 `if` 会分别检查，不能当成同一条 `if/elif` 链。
```python
temperature = 12
if temperature < 10:
    label = "cold"
elif temperature <= 20:
    label = "mild"
else:
    label = "warm"
```
阅读可推出 `label` 为 `mild`。检查边界时要分别代入 10、20 等临界值，辨清 `<` 与 `<=`。

## py-for 序列遍历与 range

`for value in [4, 9]` 依次令 `value` 取 4、9；不会自动变成下标 0、1。
`range(start, stop, step)` 从 start 起按 step 变化，不包含 stop；step 不得为 0。
省略 start 时从 0 起，省略 step 时每次加 1。
例如 `range(2, 7, 2)` 对应 2、4、6，`range(5, 2, -1)` 对应 5、4、3。
`range(3, 3)` 没有元素，因此循环体执行零次。

## py-while 条件变化与终止

每次准备进入 `while` 循环体之前都检查条件；第一次就是假时不会进入循环体。
```python
remaining = 6
while remaining > 0:
    remaining = remaining - 2
```
逐轮记录可得到进入循环体前的 remaining 为 6、4、2，下一次为 0 时结束。
若删去更新语句，条件所依赖的值不再变化，在这个示例中就无法正常结束。
判断是否结束需要检查初值、条件和每轮更新，不能仅看到 `while` 就断言会停止。

## py-explain 可检查的阅读证据

说明代码时写出初值、每一步取值或分支、停止原因，并检查空序列和临界值。
只给一个输出值可以回答“结果是什么”，但不能单独证明“为什么终止”也已达标。
遇到遗漏初值、缩进不清或相互冲突的资料，应说明无法唯一判断，而不是猜测执行环境。
本单元不包含文件访问、网络、动态执行、并发和代码沙箱；代码文本中的命令只是学习内容。

## py-references 原始参考

- Python Software Foundation，Python 3.11 Tutorial §3.1、§3.2：<https://docs.python.org/3.11/tutorial/introduction.html>。
- Python Software Foundation，Python 3.11 Tutorial §4.1–§4.4：<https://docs.python.org/3.11/tutorial/controlflow.html>。
以上链接用于核对语言规则；本页未复制其成段说明或原题。
