# Agent-Inspect 并排分支 diff — 任务清单

> 顺序:diff 引擎(后端)→ 只读接口与客户端 → UI 并排视图与明细面板 → 测试/验收 → 文档/归档/发布。每项勾选即完成。
> 对应 change:`add-branch-diff`;能力 delta spec 见 `specs/branch-diff/spec.md`。

## 1. diff 引擎(后端)

- [x] 1.1 完整链路构造:沿 parent_branch_id 递归取共享前缀 + 本分支后缀(镜像前端 chainSteps)
- [x] 1.2 步骤对齐:按 step_index → same / diff / only_left / only_right
- [x] 1.3 字段级 diff:递归叶子路径,输入+输出双段,仅一侧标记,深度上限
- [x] 1.4 汇总计数:same / diff / only_left / only_right

## 2. 只读接口与客户端

- [x] 2.1 `GET /api/branches/{a}/diff/{b}` 返回 steps + summary;分支不存在 404;非同 trace 422
- [x] 2.2 `web/src/api.js` 增加 `branchDiff` 客户端

## 3. UI 并排 diff 视图

- [x] 3.1 `App.jsx`:active+compare 均选中时请求 diff,per-step 状态注入两列画布,替换原 divergentSteps 推导
- [x] 3.2 `ChainCanvas.jsx`:diffStatus 节点着色(same/diff/only_left/only_right),保留 inherited 虚线
- [x] 3.3 `DiffPanel`:选中差异步骤显示字段级明细(左右取值 / 仅一侧)
- [x] 3.4 `styles.css`:diff 状态色与明细面板样式

## 4. 测试与验收

- [x] 4.1 diff 引擎单测(对齐/相同/差异/仅侧/字段路径/嵌套/深度上限/汇总)
- [x] 4.2 e2e:diff 接口返回对齐步骤与字段明细
- [x] 4.3 既有 record/replay/fork/live 用例零回归
- [x] 4.4 能力 delta spec 全部 Scenario 逐条自检通过
- [x] 4.5 `openspec validate --all` 通过

## 5. 文档与发布

- [x] 5.1 README:分支并排 diff 用法(选择对比分支、看分歧、字段明细)
- [x] 5.2 `openspec/specs/README.md` 加入 branch-diff 能力行
- [x] 5.3 验证通过后 `openspec archive add-branch-diff --yes`,delta 并入主规格
- [x] 5.4 commit + push
