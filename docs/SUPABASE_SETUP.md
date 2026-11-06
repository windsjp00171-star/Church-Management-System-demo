# 新 Supabase 專案：金鑰與 RLS 建議（給新教會部署）

> 結論先講：**伺服器用「服務端金鑰」，每張表開 RLS 且不設政策，公開金鑰完全不放進系統。**
> 這份建議是依本 repo 的實際用法寫的；金鑰種類以你在 Supabase 後台看到的名稱為準（名稱近年有改，見下）。

## 這個系統怎麼用 Supabase（已查證）
- 只有**伺服器**（Flask，跑在 Render）連 Supabase，用 `db.py` 的 `create_client(SUPABASE_URL, SUPABASE_KEY)`；**只有一個金鑰變數 `SUPABASE_KEY`**。
- **瀏覽器端沒有 Supabase 連線**（`templates/`、`static/` 沒有 supabase-js 或 `createClient`）。所以前端根本不需要任何金鑰。
- 檔案：`visitor-forms` 是私有 bucket，用伺服器簽發的暫時網址讀；`event-posters` 是刻意公開的海報圖。

## 建議
| 項目 | 做法 | 為什麼 |
|---|---|---|
| `SUPABASE_KEY`（Render 環境變數） | 填 **服務端金鑰**：後台 Project Settings → API Keys 裡的 `service_role`（舊名）／`secret` key（`sb_secret_…`，新名） | 它**繞過 RLS**，網站才讀得到資料；只放在 Render，**不進 repo、不進 LINE、不貼對話** |
| 公開金鑰（`anon`／`publishable`） | **不用、不放**進系統 | 沒有瀏覽器直連的需求；沒放就不會外洩 |
| 資料表 RLS | **全部開、一條政策都不設**（`schema.sql` 結尾已包含） | 就算有人拿到公開金鑰，也讀不到、寫不進任何一列 |
| 資料庫函式 | 不開放給公開角色，只給服務端（`schema.sql` 結尾已包含） | 避免有人用公開金鑰直接呼叫 `rc_save_record` 等函式 |
| 新增資料表之後 | 再執行一次 `migrations/013_security_hardening.sql` | 它會把所有 public 表補開 RLS |
| 金鑰遺失／外洩 | 後台輪替（rotate）金鑰，更新 Render 環境變數後重新部署 | 交接文件要寫明；金鑰由教會兩位同工保管 |

## 部署順序
1. 在空的 Supabase 專案（Singapore）SQL Editor 執行**整份 `schema.sql`**（已含聚會點名與安全強化，可重複執行）。
2. Render 環境變數填 `SUPABASE_URL` 與**服務端金鑰**。
3. 首次登入、確認各頁讀得到資料。**若各頁都讀不到資料，先檢查是不是填成公開金鑰。**

## 已驗證／未驗證
- 已驗證（本機 Postgres 16）：`schema.sql` 在空資料庫可完整執行、可重複執行；68 張表全部開 RLS；`anon` 對函式沒有執行權、`service_role` 有。
- **未驗證：真實 Supabase。** 本機用同名角色（anon／authenticated／service_role）模擬，沒有連到真正的 Supabase；第一次在新專案執行後請照上面第 3 步確認。
- **未驗證：** 現有展示站／安南正式站目前用哪一種金鑰（不要在不確定時對既有專案執行 `013`，若它用的是公開金鑰，執行後網站會讀不到資料）。
