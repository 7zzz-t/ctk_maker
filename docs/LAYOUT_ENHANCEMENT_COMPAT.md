# 02 布局增强 · 原版兼容与双向映射规范

> 状态：**已定稿**（决策 `dec-2a1e1e272d3a092a`：兼容口径 = 语义/行为一致）
> 适用范围：02 相对原版 00 的**一切布局增强**（主轴百分比/剩余分配、磁盘烘焙
> 快照；auto 高度曾实现、已按 `dec-c38f4c7beb71fa68` 回退），以及导出 .py 的内容约束
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
| 主轴 fixed/percent/remain | 私有键（见下）+ **磁盘烘焙**：派生 px 写入子控件自身 `height`/`width`（见 §11.8） | 烘焙快照 |
| 交叉轴 fixed/percent | 同上：派生 px 写入子控件自身 `width`/`height`；**不写 `stretch`** | 烘焙快照 |
| grid 子 "贴边/铺满" | `grid_sticky` 原值（00 原生） | 直落 |
| auto-height（height=0） | 已回退删除（`dec-c38f4c7beb71fa68`）；00 legacy `<=0` 保留 | — |

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

## 八、导出无残留约束（状态：上游依赖阻塞）

> **2026-09-09 阻塞确认**：`_ctkmaker_min / _ctkmaker_fixed / _ctkmaker_image`
> 是运行时 **ctkmaker-core `ctk.balance_pack` 的执行契约**（跳过固定子、内容下限、
> image resize）。02 仓库只有 exporter——删掉属性行后 core 拿不到 min/fixed，
> flex 收缩立即退化（文本被压扁）。core 理论可改自测（`pack_info().expand` 判
> grow、`winfo_reqheight` 作内容下限、`getattr(c, "_image")` 判 image），但属于
> **ctkmaker-core 上游（含本机 site-packages 5.5.1）** 改动，02 单方面无法交付。

- [ ] 移除逐子 `_ctkmaker_min = N` / `_ctkmaker_fixed = True` 属性行
      （`app/io/code_exporter/__init__.py` flex-shrink 发射段）—— **依赖 core 改造**；
- [ ] 容器 `<Configure> → ctk.balance_pack` 的绑定收敛为"需要才一行框架调用"，
      或由框架内部自行绑定（CTkScrollableFrame 已确认不绑定）；
- [ ] 复核 auto-height / 其它 helper 相关行，保持零 `_ctkmaker_*` 文本残留。
- [ ] （未定）若决定清理：需在 ctkmaker-core 建"自测式 balance_pack"分支并同步
      本机 site-packages 验证，再回改 exporter 去属性。

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
| `CTkFrame height=0`（auto 语义，e231ab8 放行） | **已回退删除**（`dec-c38f4c7beb71fa68`） | 历史：曾实施 200+marker 磁盘映射（`dec-0f67cc2227ac0d14`/`7783611`），00 侧实测通过；经需求实测（子内容受父约束、无法扩出父容器）后于 2026-09-09 **整体删除**该功能（含 marker 序列化、导出省略 height、H 联动）。现状：`height` clamp 恢复 ≥1，旧 marker/0 文件按普通固定高加载；00 基线 legacy `height<=0` 行为未动。 |
| 受管 vbox/grid 子 x/y 缺失（cc19a26 删除） | 无风险 | 00 对 pack/grid 子不读 x/y；缺省即默认，渲染由父布局决定。 |
| grid 容器 `grid_rows/cols` 增长值 | 无风险 | 00 原生键、int、同 schema（min1 max50 两边一致）。 |
| `stretch` / `grid_sticky` 等 | 无风险 | 00 原生三值/组合，两版同源。 |
| `_pending_parent_dim_changes` | 无风险 | 仅内存临时 attr，从不落盘。 |

### 9.3 后续待办

- [x] 值层：00 画布 height=0 表现已人工复核（不可见 → 已走 ③ 映射，见 9.2）；
- [ ] 导出无残留收尾（第八节清单）；
- [x] 新参数类别机制设计 → 见第十一节（决策 `dec-aa6eedbd648307d7` 一步到位全做）。

### 9.4 已知原版缺陷（00 自身，非 02 引入）

> 决策更新：`dec-b7fb7bfe6c875652`（不改原版 00，仅 02 侧处理）+
> `dec-e1e9ce0c4e939463`（**保存时静默自动修复**）。

**现象**：工程若含「父容器 `layout_type=place`（或未设）+ 子控件为多部件
（composite，`anchor_widget is not widget`，目前仅 **`CTkScrollableFrame`**）」结构，
**原版 00 打开即崩**：

```
00 widget_lifecycle._place_nested → anchor_widget.place(width=…, height=…)
→ ValueError: 'width'/'height' must go to the constructor, not the place method
（ctkmaker-core 5.5.x place() 拒绝 width/height）
```

**性质**：
- 00 的 `_place_nested` 对 composite 唯一地调用 `place(width,height)`；该组合无论
  由 00 还是 02 生成，原版 00 都崩（00 自己甚至无法现场创建该结构——放置即崩）；
- 02 已修复同一缺陷（`ac2177e`：先 `configure(w/h)` 再 `place(x,y)`），02 打开正常；
- **00 的导出器不受影响**：其 place 分支只生成 `place(x=…, y=…)`，不含 width/height
  （`app/io/code_exporter/__init__.py`），导出的 .py 可正常运行；
- 与增强参数、`_ctkmaker_meta`、percent 等**无任何因果**——换 sidecar 存参数同样崩。

**处置（02 侧自动，不改原版 00）**：`app/io/stock_compat.py` 在**每次保存前**扫描
文档树，把「place/未设布局的父容器（含窗口）+ 其子控件含 composite」的父容器
`layout_type` **静默改写为 `vbox`**（受管布局 → 00 走 pack 分支，不再 `place(w/h)`）。
改写幂等、只作用于确有 composite 子控件的 place 类父容器；命中的一级复合关系包括
窗口（`window_properties`）与任意节点（`properties`）。已实现于 `save_project`，
新增测试 `tests/test_stock_compat.py`。

**残留代价**：被改写的容器由 place 变为 vbox（子控件改按 pack 堆叠）——这是"向 00
靠齐"不可避免的语义变化，已在保存时自动完成，用户无需手工调整。

---

### 9.5 待办：02 允许创建 00 打不开的结构

- 现状：02 画布已修复 composite-on-place，故 02 内可以放置/保存该结构；保存时由
  §9.4 的 stock 兼容层自动改写父容器，避免产出 00 打不开的工程文件。
- [ ] 编辑期提示：把 composite 拖入 place 容器时给出提示（说明保存时会自动改为
  vbox），避免用户对"保存后布局变了"感到意外。

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

### 11.3 参数清单（现行 · 2026-09-10 两轴参数化）

> **修订（两轴参数化，不再依托 `stretch`）**：两轴参数与「拉伸」本质相同 ——
> 都只是决定子控件的**尺寸数值**，两轴只是把数值**参数化算出来**（免手算）。
> 派生结果写入子控件自身的 `height` / `width`，等同于手填；`stretch` 永不被
> 派生逻辑改写，保持用户选择（默认 `fixed`），故 00 打开同一文档行为一致。

| 参数 | 适用 | 取值 | 语义 | 原版快照/磁盘 |
|---|---|---|---|---|
| `main_axis.mode` | vbox/hbox 子 | `fixed`(默认) / `percent` / `remain` | fixed=用自身 H/W；percent=父主轴 N%；remain=均分（扣固定+百分比后）剩余 | 派生 px 写入子控件自身 `height`/`width`（§11.8） |
| `main_axis.percent` | 同上 | 1–100 | 仅 mode=percent 生效 | 见上 |
| `cross_axis.mode` | vbox/hbox 子 | `fixed`(默认) / `percent` | fixed=用自身 W/H；percent=父交叉轴 N%（100%=铺满） | 派生 px 写入自身 `width`/`height` |
| `cross_axis.percent` | 同上 | 1–100 | 仅 mode=percent 生效 | 见上 |

> 兼容：旧文件中的 `main_axis.mode="content"` 读取时归一化为 `fixed`。

> **已回退**（`dec-c38f4c7beb71fa68`，2026-09-09）：原 v1 曾含 `height_mode`
> （auto 高度）参数与 `height=0`/200+marker 磁盘映射，经实测确认后**全部删除**。
> 00 基线自身的 legacy `height<=0` 行为保持不变。

### 11.4 UI（仅 02 显示，00 面板天然无这些行）

- vbox/hbox 子的 Layout 组尾部：「主轴：固定(数值) | 百分比 | 剩余」与
  「交叉轴：固定(数值) | 百分比」；各自在选中 percent 时出现数值行（1–100）；
  固定(数值) 无额外输入框，直接用该控件自身的 H/W 行。批量同值/异值汇总、
  undo 见实施记录。

### 11.5 导出（不残留，静态化）

- percent（该轴父尺寸固定）→ 导出时静态算 px `round(parent_axis_px × N%)`
  → 写构造参数 `height=` / `width=`（两轴同理）；
- remain → 同样导出**精确 px**（扣固定与百分比后均分），不再用
  `stretch:"grow"` + `expand=True`；
- 自由轴父（scroll 内容 / 该轴尺寸 ≤0）→ 降级 `fixed`，用子控件自身尺寸
  （与编辑器、落盘一致）；
- `stretch` 保持用户值：仅当派生尺寸遇到残留 `grow` 时降级为 `fixed`，
  避免被重新拉伸。

### 11.6 迁移

- 旧文件若残留顶层 `_ctkmaker_auto_height` / `height=0`（auto 时代产物）→ 现在
  **按普通固定高加载**（marker 忽略、0 由 clamp 不再产生）；如需自动语义请回退到
  auto 时代的 02 版本——当前版本已无该功能。

### 11.7 实施阶段（对应任务清单）

1. `WidgetNode.extra` + `_ctkmaker_meta` 序列化与迁移 —— **完成**（`65410bd`）；
2. 面板 extra 行（主轴 enum + percent 数值）、批量扇出/汇总/undo —— **完成**
   （`81e3ef1`/`8cec00f`/`e818ce1`/`5b0773c`/`3e33205`）；禁用/灰显细节列 v2；
3. auto-height（height_mode）—— **已按 `dec-c38f4c7beb71fa68` 回退删除**
   （含磁盘 200+marker 映射、导出省略 height、H 联动、相关测试；提交 `8e6af5c` 撤销）；
4. `main_axis` percent/remain 计算与导出静态化 —— **完成**
   （`5a93805` 内存快照 grow → `3c322c6` 画布预算 → `f79c1cd` 导出 px）；
5. 磁盘烘焙（fill+px，替代 grow 近似）—— **完成**（`2301a75`）；
6. 兼容回归 + 全量测试 + 文档收口 —— 代码侧完成（§8 阻塞标注、§9.4 缺陷记录、
   本节收口）；00 人工回归待做。

### 11.8 percent / remain 最终语义（一页速查）

**快照 = 磁盘烘焙（decision 延续 §11.5）**：保存时 percent/remain 在定高父上
被算成 00 的确定参数 —— `stretch="fill"` + 精确主轴 px（percent =
`round(父px×pct%)`；remain 与 grow/remain 同池均分剩余）。内存与导出仍走响应式
（02 画布按 px/grow 重算、导出 remain=expand grow）；00 打开看到的是烘焙后的
静态、逐像素一致布局（remain 在 00 里不随窗口再伸缩）。

| 场景 | percent | remain |
|---|---|---|
| 定高父（CTkFrame vbox/hbox） | 画布/导出按 px 固定；**磁盘烘焙 stretch=fill + px** | 内存/画布 grow 池均分；**磁盘烘焙 fill + 均分后 px** |
| 自由轴父（scroll 内容 / 高度 0） | 不烘焙（磁盘保留自身 stretch/尺寸）；02 侧降级 content | 同左 |
| 00 打开文件 | 静态 fill + 精确 px（与 02 画布逐像素一致） | 同左（非响应式） |
| 00 编辑另存 | 顶层 extra 被丢弃 → 节点降级为烘焙后的固定形态（预期） | 同左 |

---

## 十二、变更记录

- 2026-09-08：定稿（四层规则 + 双向映射 + 私有键约定 + 导出无残留 + 存量盘点待办）。
- 2026-09-08：私有键位置修订（node 顶层，禁入 properties —— 00 全量传参崩溃实测）；
  auto-height 磁盘映射实施（`dec-0f67cc2227ac0d14`）与修订（`7783611`）。
- 2026-09-08：新增第十一节「增强参数机制」设计（`dec-aa6eedbd648307d7`，一步到位全做）。
- 2026-09-08：§11 实施完成 —— extra 存储、面板行（enum+percent 数值）、auto-height
  first-class（画布/导出/快照）、percent/remain 画布预算与导出精确 px（提交链
  `65410bd → 81e3ef1 → 5bc5aaf → 5a93805 → 3c322c6 → f79c1cd → 8cec00f`）。
- 2026-09-09：收口补链 —— 批量 x.（`e818ce1`）、§8 core 阻塞标注与选项汉化
  （`5b0773c`）、extra 行并入 Layout 组（`3e33205`）、auto 态钉 H 退出 auto（`8e6af5c`）；
  §9.4 记录 00 的 place+composite 缺陷（`4ea7c16`）。
- 2026-09-09：磁盘烘焙快照（`2301a75`：percent/remain → fill+精确 px，替代 grow 近似）。
- 2026-09-09：**auto-height（height_mode）整体回退删除**（`dec-c38f4c7beb71fa68`：
  需求实测确认子内容受父约束无法扩出父容器，功能无效）——撤 extra 参数/磁盘
  200+marker/导出省略 height/H 联动/clamp 放行及相关测试；percent/remain 与烘焙保留。
