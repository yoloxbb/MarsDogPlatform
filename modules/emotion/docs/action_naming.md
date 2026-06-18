# 行为命名规范

## 顶层行为

顶层行为统一使用 `ACTION_*`，例如：

- `ACTION_EAT`：进食
- `ACTION_SLEEP`：睡觉
- `ACTION_FLEE`：逃离
- `ACTION_LOAF`：闲逛

## 具体动作

具体动作统一使用 `ACT_*`，例如：

- `ACT_RUN_TO_BOWL`
- `ACT_SNIFF_BOWL_EDGE`
- `ACT_FAST_LICK_AND_SWALLOW`

## 接口命名

- 读取接口：`Get + 数据类型 + Value`
- 设置接口：`Set + 数据类型 + Value`
- 判断接口：`Is + 条件描述`
- 回调接口：`On + 事件名`
- 动作执行接口：`Execute + 动作名`
- App 业务接口：直接使用动词加名词，例如 `Feed()`、`Pet()`、`GiveToy()`
