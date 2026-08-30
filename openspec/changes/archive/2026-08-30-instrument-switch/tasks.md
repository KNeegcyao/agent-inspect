# instrument-switch Tasks

## 1. OpenSpec 文档

- [x] 1.1 `proposal.md` / `design.md`:开关的 why / 语义 / 范围
- [x] 1.2 `specs/interception/spec.md` delta:「插桩模块开关」1 requirement 共 3 场景

## 2. 实现

- [x] 2.1 `session.py`:`instrument` 参数,按声明构造/安装 patcher;默认全启用
- [x] 2.2 单测:默认全启用 / 仅其一(另一模块零改动)/ 混合与未知键 / stop 卸载

## 3. 验证与发布

- [x] 3.1 全量 pytest 零回归;`openspec validate --all` 通过
- [x] 3.2 README 启用示例补一句;`openspec archive instrument-switch`;commit + push
