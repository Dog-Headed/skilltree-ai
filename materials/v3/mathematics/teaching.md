# 一元一次方程：解、等价变形与检验

版本：3.0.0-day10-1。原创说明与例题；核对 OpenStax Prealgebra 2e，待用户复核。
限定实数范围的简单一元一次方程；不提供一般符号证明或任意表达式执行能力。

## math-foundation 有理数与等号

等号表示左右两边的值相同，不是“接下来写答案”的符号。
负数的减法、乘法和除法要区分：例如 `-3 - 2 = -5`，`(-3) × (-2) = 6`。
解方程前可用具体数检查运算基础；过去完成过基础单元不能排除现在出现薄弱点。

## math-add 两边同加减

为保持等式成立，两边同时加上或减去同一个数。
例：`x + 7 = 12`，两边减 7 得 `x = 5`；代回后 `5 + 7 = 12`。
“移项变号”是上述等价操作的简写，不能只改变一侧而不说明对应操作。
例：`x - 6 = -2`，两边加 6 得 `x = 4`。

## math-multiply 两边同乘除

等式两边同乘同一个数，仍有相等关系；用于求唯一解的除法必须除以非零数。
例：`3x = 18`，两边除以 3 得 `x = 6`。
例：`x/4 = 3`，两边乘 4 得 `x = 12`。
不能除以 0，也不能把 `3x` 错当作 `x + 3`。

## math-multistep 多步求解

先正确展开括号、合并同类项，再把变量项和常数项分开，最后令变量系数为 1。
例：`2(x + 3) = 14`，两边除以 2 得 `x + 3 = 7`，再两边减 3 得 `x = 4`。
也可先展开成 `2x + 6 = 14`；两条等价路径都可以，只要每步有依据。
例：`4x + 1 = 2x + 11`，两边减 2x、再减 1，可得 `2x = 10`，所以 `x = 5`。

## math-check 代回原式与答案形式

求出的数要代回原方程，分别计算左右两边，而不是仅代入已经写错的中间式。
对 `2x + 3 = 11`，取 x=4，左边为 11、右边为 11，原式成立。
若题目还要求解释步骤，只写“4”不足以提供等价变形的证据。
本单元使用无单位的数值；整数与相等的有限小数可表示同一答案，例如 5 与 5.0。
有限数值校验不等同于验证整个推导；不接受 NaN、Infinity 或可执行表达式来冒充数值。

## math-uncertainty 范围与资料问题

题面缺少条件或两份材料给出互相矛盾的规则时，先定位矛盾，不能静默选一份评分。
无唯一解、非一次方程和复杂证明不在这份小单元的自动评价范围内。

## math-references 原始参考

- OpenStax，Prealgebra 2e §8.1，两边同加减与代回检验：<https://openstax.org/books/prealgebra-2e/pages/8-1-solve-equations-using-the-subtraction-and-addition-properties-of-equality>。
- OpenStax，Prealgebra 2e §8.2，两边同乘除：<https://openstax.org/books/prealgebra-2e/pages/8-2-solve-equations-using-the-division-and-multiplication-properties-of-equality>。
- OpenStax，Prealgebra 2e §8.3，多步方程：<https://openstax.org/books/prealgebra-2e/pages/8-3-solve-equations-with-variables-and-constants-on-both-sides>。
本页使用自行编写的例题和中文说明，不复制教材的成套练习。
