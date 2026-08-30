# interception Specification

## ADDED Requirements

### Requirement: 插桩模块开关

系统 SHALL 支持在启用时按插桩模块开关:仅被启用的模块被包装;未指定时全部启用(与既有行为一致);被停用的模块对宿主零改动。

#### Scenario: 指定仅启用其一

- **WHEN** 启用时声明只启用某个插桩模块
- **THEN** 该模块照常插桩,另一模块的包装入口保持原样(其调用不被记录、行为与无本系统一致)

#### Scenario: 默认全启用

- **WHEN** 启用时未声明 instrument 配置
- **THEN** 所有可用模块照常插桩,行为与既有版本一致

#### Scenario: 混合配置互不影响

- **WHEN** 同时声明多模块的开关组合
- **THEN** 各模块按声明独立启停,互不影响
