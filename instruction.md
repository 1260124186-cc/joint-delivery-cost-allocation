# 联合配送费用分摊复核

区域冷链园区的结算组会把同一天的零担订单并成一辆车配送，再按合作博弈的 Shapley 值向商户分摊这趟车的费用。旧台账程序只按门店编号依次取最近一站，金额又用浮点四舍五入，月底总会出现分摊合计差几分钱、同一组订单换顺序就换价的情况。请改好 `/workspace/route_share`，保留现有四段命令，并把每一段的数学口径落实。

## 输入

`example.json` 是按固定种子生成的演示实例，不是现场采集记录。输入对象包含：

- `instance_id`：非空字符串；
- `depot`：配送中心，含唯一 `id` 和整数坐标 `x_m`、`y_m`，单位为米；
- `stops`：1 到 10 个订单门店，每项含唯一 `id`、整数坐标 `x_m`、`y_m` 和非负整数结算上限 `max_settlement_cents`；门店编号不能与配送中心重复；
- `road_factor`：正数，表示实际道路里程相对直线距离的放大系数；
- `rate_cents_per_km`：正整数，每公里运费，单位为分；
- `dispatch_fee_cents`：非负整数，每趟固定调度费，单位为分。

任意两个不同节点的道路里程为二者欧氏距离乘以 `road_factor`。对非空门店集合 `S`，`v(S)` 是从配送中心出发、每家门店铺到一次并返回中心的最短闭合巡回所对应的整数费用：

```text
v(S) = dispatch_fee_cents
       + round_half_up(road_factor * shortest_distance_m(S) / 1000 * rate_cents_per_km)
```

每次求平方根使用至少 50 位十进制精度；把整条巡回的里程求和后，统一量化到 `1e-18` 米再参与比较，取最短的一条。若量化后的里程相同，则比较门店编号序列的字典序，取较小者。费用使用同一个量化后的总里程，最后才对整趟巡回做一次半入取整，不能每段分别取整。

## 四段命令

工作目录固定为 `/workspace`，程序入口及参数顺序不能改：

```bash
python -m route_share coalitions example.json coalitions.json
python -m route_share shapley example.json coalitions.json shares.json
python -m route_share settle example.json shares.json settlement.json
python -m route_share run example.json result.json
```

### `coalitions`

输出对象含 `instance_id` 和 `coalitions`。`coalitions` 必须覆盖全部非空门店子集，每项含：

- `members`：按字典序排列的门店编号；
- `cost_cents`：按上式算出的整数费用；
- `tour`：从配送中心编号开始、依次经过该集合所有门店、最后回到配送中心编号的完整顺序。

列表先按 `members` 数量升序，再按 `members` 数组字典序升序。`run` 也必须包含这部分结果。

### `shapley`

第二段读取实例和第一段的结果，输出对象含 `shares`、`total_cost_cents` 和 `efficiency_holds`。设订单全集为 `N`，门店 `i` 的 Shapley 值为：

```text
phi_i = sum over S subset of N minus {i} of
        |S|! * (|N|-|S|-1)! / |N|! * (v(S union {i}) - v(S))
```

全程使用 `fractions.Fraction` 或等价的有理数运算，不许先转成 `float`。`shares` 按 `order_id` 字典序排列，每项以约分后的 `numerator`、`denominator` 给出，分母为正；`total_cost_cents` 取全部门店集合的费用，`efficiency_holds` 为 `true`。第一段结果缺子集、重复子集、包含未知门店或费用不是非负整数时，应非零退出。

### `settle`

第三段读取实例和精确份额，把费用换成整数分。设门店集合为 `N`，每项结算 `x_i` 必须是整数，并满足：

```text
0 <= x_i <= max_settlement_cents
sum(x_i) = total_cost_cents
```

在这些约束下，选择使

```text
sum((x_i - phi_i)^2)
```

最小的整数向量；目标值相同时，把按 `order_id` 字典序排列的整数金额向量作为比较对象，取字典序最小的一组。输出对象含：

- `settlement_cents`：对象，键为门店编号，值为整数分；
- `allocated_total_cents`：所有整数分摊之和；
- `rounding_remainder_cents`：结算后剩余差额，必须为 0。

`shares` 中分母非正、分子为负、分数未约分、重复门店、未知字段组合或精确份额之和与 `total_cost_cents` 不一致时，应非零退出；上限总和不足以容纳总额时也必须非零退出。输入有问题时不能新建输出，也不能覆盖已经存在的输出文件。

### `run`

一次完成前三段，输出对象同时包含 `instance_id`、`coalitions`、`shares`、`settlement_cents`、`total_cost_cents` 和 `rounding_remainder_cents`，各字段与分段结果一致。所有金额只保留整数分，不得写出 `NaN` 或无限值。

## 通用约束

- 只使用 Python 标准库；不要改变包名、命令名、参数顺序和 JSON 字段名。
- `v(S)` 要看所有可能巡回，不能把门店编号顺序、最近邻顺序或输入顺序当成最优顺序。
- 十家门店的实例也要在单次命令的常规运行时限内完成，不能依赖生成并穷举全部排列。
- 整数分结算必须在门店上限内最小化平方偏差，不能逐项四舍五入，也不能忽略上限。
- 任一阶段发生参数错误、计算错误或写出失败时，都应以非零状态退出；已有输出保持不变。
