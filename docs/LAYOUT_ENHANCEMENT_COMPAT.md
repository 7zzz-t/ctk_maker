# 02 布局增强 · 原版兼容与双向映射规范

> 状态：**已定稿**（决策 `dec-2a1e1e272d3a092a`：兼容口径 = 语义/行为一致）
> 适用范围：02 相对原版 00 的**一切布局增强**（容器默认拉伸、百分比/剩余分配、
> auto 高度、flex 收缩等），以及导出 .py 的内容约束
> 日期：2026-09-08

---

## 一、目标与硬约束

1. **工程文件可被原版 00 打开**，且 00 打开后所有功能 / 编辑 / 导出行为与
   纯原版文件**完全一致**（语义/行为一致，见第二节）。
2. 导出 .py 是用户代码的干净载体：不残留我们私有的属性行 / bind / helper 调用。
3. 布局增强属于"计算 / 补丁层"：只在编辑器与运行时框架层生效，默认 / 派生 /
   继承状态不随工程文件走；需要跨会话保留的只有**用户显式设置**。

---

## 二、兼容口径（决策记录）

- **选项**：字节级纯净（.ctkproj 与纯原版逐字节一致） vs 语义/行为一致。
- **已选**：`dec-2a1e1e272d3a092a` → **语义/行为一致（可容忍私有键）**。
- 推论：`.ctkproj` 允许出现 00 看不见的 builder-only 私有键；00 另存时会
  原样保留这些键，不剔除、不报错、不影响任何 00 行为。

---

## 三、事实依据（原版 00 行为，已核实）

| 事实 | 依据 |
|---|---|
| 00 的 `WidgetNode` 是通用 dict 存储，加载 `properties` 照单全收，无 schema 白名单过滤 | 00 `app/core/widget_node.py`：`properties=data.get("properties", {})`；`to_dict()` 全量回写 |
| 00 加载 `WidgetNode` 挑已知键读，未知**顶层**字段被忽略、不报错 | 00 `app/core/widget_node.py::from_dict`（挑键读取） |
| 00 另存按白名单输出 → 顶层未知字段会**丢失** | 00 `to_dict` 白名单 |
| 00 渲染 `create_widget` 把**全部 `properties` 键**当 CTk 构造参数 | **实测崩溃**：`ValueError: ['_ctkmaker_auto_height'] are not supported arguments`（`ctk_base_class.check_kwargs_empty`） |

**危险点（实测修正）**：
- 给 00 **已存在**的键写入 00 不认识的**新值**（如 `stretch="-"`）→ 00 枚举面板无该选项、显示异常并回退默认。
- 给 `properties` 塞任何 00 不认识的新键 → 00 **实例化即崩溃**（全量传 CTk 构造器）。
- 因此 builder-only 数据**只能放 node dict 顶层字段**，绝不放 `properties`。

---

## 四、四层规则总表

| 层 | 规则 | 落盘 |
|---|---|---|
| ① 默认 / 继承 / 派生 | 只在 02 会话内存（加载时对 00 文件叠加补丁） | **永不写文件** |
| ② 显式设置 · 00 可表达 | 保存时翻译成 00 键值（`stretch` 三值 / `grid_*` …） | 写 00 原版键值 |
| ③ 显式设置 · 00 无法表达 | 私有键持久化（见第六节）+ 同时落最近似 00 参数作**降级快照** | `properties` 内私有键 |
| ④ 导出 .py | 私有键与 `_ctkmaker_min` / `_ctkmaker_fixed` 类残留一律不出现 | 由框架层运行时计算 |

---

## 五、双向映射规则（02 表达 ↔ 00 落盘参数）

| 02 内部表达 | 落盘（00 参数） | 备注 |
|---|---|---|
| stretch="-"（跟随容器默认） | **不写**（省略，00 按自身默认） | 继承是会话补丁，无需落盘 |
| stretch="fixed" | `stretch="fixed"` | 直落 |
| stretch="fill" | `stretch="fill"` | 直落 |
| stretch="grow" | `stretch="grow"` | 直落 |
| 主轴 40% / 剩余 ×N | 私有键（见下）+ 最近似 00 参数（`grow`/`fill`） | 降级快照 |
| grid 子 "贴边/铺满" | `grid_sticky` 原值（00 原生） | 直落 |
| auto-height（height=0） | 见"存量盘点"待办，需确认 00 对 height=0 的读取/面板行为 | 待专项核实 |

**降级原则**：00 打开 02 文件时永远看到"最近似的原版语义"；02 再次打开时若
发现私有键，用私有键恢复精确表达；私有键丢失/被清理 → 自动降级为快照值，
不报错、不丢结构。

---

## 六、私有键约定（builder-only）

- **位置**：挂在对应 widget 的 **node dict 顶层字段**（与 `visible` / `locked` /
  `group_id` 并列），**禁止放入 `properties`** —— 00 会把 `properties` 全量传给
  CTk 构造器，未知属性键会当场崩溃（实测 `not supported arguments`）；顶层
  未知字段 00 忽略、不报错（00 另存按白名单会丢弃 → 节点降级为快照值）。
- **命名**：统一前缀 `_ctkmaker_`（如 `_ctkmaker_auto_height`）。
- **载荷**：单个 JSON 可序列化对象；**版本字段**随附（`{"v": 1, ...}`），便于
  未来迁移。
- **约束**：
  - 只写"00 无法表达且用户显式设置"的状态，绝不写默认/派生值；
  - 每个含私有键的节点必须同时带降级快照（原版参数），保证剥离私有键后
    文件仍语义完整；
  - 导出器 / 画布 / 面板一律经"私有键解析层"读写，禁止散落直读。

---

## 七、补丁生命周期

```
.ctkproj（00 兼容：原版键值 + 可选私有键）
   │ 加载
   ▼
文档树 = 用户显式数据 + 会话补丁（默认拉伸/继承/百分比基准）
   │ 编辑 / 画布 / 预览
   ▼
保存 ──▶ ① 剥离会话补丁
       ② ②类表达映射为 00 键值
       ③ ③类表达写私有键 + 降级快照
   ▼
.ctkproj（写盘，00 可开）
   │ 导出
   ▼
纯 CTk 代码 + 框架 API（无私有残留）
```

---

## 八、导出无残留约束（待收尾清单）

- [ ] 移除逐子 `_ctkmaker_min = N` / `_ctkmaker_fixed = True` 属性行
      （`app/io/code_exporter/__init__.py` flex-shrink 发射段）；
- [ ] 容器 `<Configure> → ctk.balance_pack` 的绑定收敛为"需要才一行框架调用"，
      或由框架内部自行绑定（CTkScrollableFrame 已确认不绑定）；
- [ ] 复核 auto-height / 其它 helper 相关行，保持零 `_ctkmaker_*` 文本残留。

---

## 九、存量盘点记录（本次设计完工后执行）

> 用户提示：**我们此前相对 00 的修改，可能已引入 00 未知的键或值**。
> 盘点已启动，结论逐步回填本节。

### 9.1 键层盘点（已完成，结论：干净）

- 方法：分别收集 00 / 02 全部 descriptor 的 `default_properties` 键 +
  `property_schema` 行名 + 布局全局键（`LAYOUT_DEFAULTS` /
  `LAYOUT_CONTAINER_DEFAULTS`），做集合差。
- **结论：零新增、零删除**。02 写进 .ctkproj 的键全部落在 00 白名单内。

### 9.2 值层盘点（进行中）

| 候选值 | 判定 | 说明 |
|---|---|---|
| `CTkFrame height=0`（auto 语义，e231ab8 放行） | **已实施 ③ 映射**（决策 `dec-0f67cc2227ac0d14`，第一版实测崩后修订） | 00 实测一：加载无报错、H 格 0、画布不可见；实测二：marker 放 `properties` 会崩（`not supported arguments`）→ 最终形态：`to_dict` 把 `height=0` 写为 `height=200`（properties，保持 CTk 可构造）+ **顶层** `_ctkmaker_auto_height:true`；`from_dict` 还原 0。00 打开 = 可见固定高 frame；00 另存会丢顶层键 → 节点降级为 200 固定高（预期）；02 重开（未另存）恢复 auto。旧裸 0 文件加载即 auto、保存自动升级。见 `app/core/widget_node.py`。 |
| 受管 vbox/grid 子 x/y 缺失（cc19a26 删除） | 无风险 | 00 对 pack/grid 子不读 x/y；缺省即默认，渲染由父布局决定。 |
| grid 容器 `grid_rows/cols` 增长值 | 无风险 | 00 原生键、int、同 schema（min1 max50 两边一致）。 |
| `stretch` / `grid_sticky` 等 | 无风险 | 00 原生三值/组合，两版同源。 |
| `_pending_parent_dim_changes` | 无风险 | 仅内存临时 attr，从不落盘。 |

### 9.3 后续待办

- [x] 值层：00 画布 height=0 表现已人工复核（不可见 → 已走 ③ 映射，见 9.2）；
- [ ] 导出无残留收尾（第八节清单）；
- [x] 新参数类别机制设计 → 见第十一节（决策 `dec-aa6eedbd648307d7` 一步到位全做）。

---

## 十一、增强参数机制（新参数类别，v1 设计定稿）

> 决策 `dec-aa6eedbd648307d7`：新语义（auto-height、主轴百分比/剩余平分）不再
> 复用原版字段当暗号，而是做成**正式的一等参数**：UI 有专属新行、存储独立、
> 原版字段退化为"自动维护的兼容快照"。

### 11.1 为什么不再"复用"

- 旧做法用 `height=0` 表达 auto：H 行显示"假值"、保存要换算快照，语义藏在 0 里；
- 百分比/剩余若塞进 `stretch` 三档会与 00 枚举冲突。
- 结论：用户语义与原版字段解耦 —— 新参数存 `WidgetNode.extra`，原版字段由系统
  按快照规则自动同步，00 永远只看到"合理原版形态"。

### 11.2 存储

- `WidgetNode.extra: dict` —— builder-only 增强参数（内存态即用户语义）。
- 磁盘序列化为 node 顶层单键 `_ctkmaker_meta`（JSON 对象）；**禁止进入
  `properties`**（00 全量传 CTk 构造器会崩，见第三节）。
- 00 另存按白名单丢弃顶层键 → 节点降级为快照值（预期，见第六节）。

### 11.3 参数清单 v1

| 参数 | 适用 | 取值 | 语义 | 原版快照 |
|---|---|---|---|---|
| `height_mode` | CTkFrame | `fixed`(默认) / `auto` | auto=内容决定高 | auto → `height=快照(200)`；fixed → `height` 正常 |
| `main_axis.mode` | vbox/hbox 子 | `content`(默认) / `percent` / `remain` | content=自然；percent=父主轴 N%；remain=吃剩余 | `stretch`：percent/remain 定高父→`grow`，自由轴父→`fixed` |
| `main_axis.percent` | 同上 | 1–100 | 仅 mode=percent 生效 | 见上 |

### 11.4 UI（仅 02 显示，00 面板天然无这些行）

- 容器 Layout 组新增：「高度模式：固定 | 自动」（CTkFrame）；
- vbox/hbox 子的「拉伸」行改造为「主轴：内容 | 百分比 | 剩余」，percent 时出现
  数值行（1–100，步进 5）；受管/多选/禁用规则沿用 `managed_geometry_disabled` 同源；
- **退役**：CTkFrame 不再用 H=0 表达 auto（H 行恢复 clamp ≥1），「高度模式：自动」
  是新入口。

### 11.5 导出（不残留，静态化）

- auto（height_mode=auto）→ 省略 `height` configure（现状）；
- percent（定高父）→ 导出时按父主轴固定尺寸**静态算 px**：
  `h_px = round(parent_main_px × percent/100)` → 写 `configure(height=h_px)`；
- remain → `stretch="grow"`（运行时框架均分剩余，零残留）；
- percent 在 auto/滚动/内容父 → 降级 content（与编辑器一致）。

### 11.6 迁移

- 旧顶层 `_ctkmaker_auto_height`（marker 形态）→ 加载转 `extra.height_mode="auto"`；
- 旧裸 `height=0` 文件 → 加载即视为 auto（与既有行为一致）；
- 存量文件下次保存自动升级为新参数形态。

### 11.7 实施阶段（对应任务清单）

1. `WidgetNode.extra` + `_ctkmaker_meta` 序列化与迁移；
2. 面板 extra 行注入/编辑（含多选批量）；
3. auto-height 重构为 `height_mode`（画布/导出/commit 读 extra）；
4. `main_axis` percent/remain 计算与导出静态化；
5. 兼容回归 + 全量测试 + 文档收口。

---

## 十二、变更记录

- 2026-09-08：定稿（四层规则 + 双向映射 + 私有键约定 + 导出无残留 + 存量盘点待办）。
- 2026-09-08：私有键位置修订（node 顶层，禁入 properties —— 00 全量传参崩溃实测）；
  auto-height 磁盘映射实施（`dec-0f67cc2227ac0d14`）与修订（`7783611`）。
- 2026-09-08：新增第十一节「增强参数机制」设计（`dec-aa6eedbd648307d7`，一步到位全做）。
