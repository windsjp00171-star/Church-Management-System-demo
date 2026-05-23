# /release — 發佈系統更新日誌

發佈一筆新的 changelog 並推送到遠端分支。

## 步驟

1. **讀取現有的 `changelogs.json`**，確認目前最新版本號。

2. **詢問用戶以下資訊**（若用戶在指令後帶參數則優先使用）：
   - 版本號（例如 v1.2，應比目前最新版大）
   - 更新標題（一句話，20 字以內）
   - 更新內容（Markdown 格式，可包含 `##` 小標題與 `- ` 條列）

3. **更新 `changelogs.json`**：
   - 將新條目插入陣列**最前面**（index 0）
   - `published_at` 使用今天日期（YYYY-MM-DD 格式）
   - 保留所有舊條目

4. **Git 操作**：
   ```
   git add changelogs.json
   git commit -m "chore: publish <版本號> changelog - <標題>"
   git push
   ```

5. **完成後告知用戶**：版本號、標題、發佈日期，以及「所有教會下次登入時將看到更新橫幅」。

## 注意事項
- 只更新 `changelogs.json`，不要動其他檔案
- 版本號格式統一為 `v數字.數字`（如 v1.2、v2.0）
- 若用戶沒給內容，根據最近的 git diff 或 commit log 自動摘要生成
