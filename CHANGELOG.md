# 更新日誌

## [Unreleased]

### 修正
- 檔案分享模組改用共用的 `login_required`：未登入時會記住原始頁面，API 路徑回 401 JSON，行為與其他模組一致。

### 新增
- `tests/test_decorators.py`：涵蓋 `login_required`、`admin_required` 的未登入、一般會員、管理員、超級管理員情境。
