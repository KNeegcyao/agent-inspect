# trace-ui Specification

## ADDED Requirements

### Requirement: 面板主题切换

系统 SHALL 支持在深色与浅色两套面板主题间切换:切换即时生效(含链路画布重绘),偏好持久化,默认深色。

#### Scenario: 切换即时生效

- **WHEN** 点击主题切换入口
- **THEN** 面板配色立即在深色/浅色间切换,决策链画布同步重绘,全部功能行为不受影响

#### Scenario: 偏好持久化

- **WHEN** 切换主题后重新打开面板
- **THEN** 面板保持上次选择的主题

#### Scenario: 默认深色

- **WHEN** 从未切换过主题时打开面板
- **THEN** 面板呈现深色主题
