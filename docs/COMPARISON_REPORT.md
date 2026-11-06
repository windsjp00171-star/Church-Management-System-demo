# 整合比對報告：四個 repo（event-registration- / tianfu-diary / cell_reporter / 本展示站）

> 日期：2026-11-06　性質：**唯讀比對，未改任何程式。**
> 方法：淺層 clone 三個參考 repo（`event-registration-` @9265c7e、`tianfu-diary` @8fb27b1、`cell_reporter` @d96d823），讀各自 CLAUDE.md、模型、權限／稽核／測試慣例，並與本 repo 逐項對照。數字為實測（grep／檔案計數）；標「未驗證」者沒有親眼確認。
> 已決定（使用者）：**在本 repo 就地重構，不另開新 repo**；以 event-registration- 為成熟度基準；點名與使用者帳號脫鉤。

## 1. 四個 repo 一覽

| | event-registration-（報名系統） | tianfu-diary（天父日記） | cell_reporter（小組回報） | 本 repo（展示站） |
|---|---|---|---|---|
| 框架／資料庫 | Flask＋Supabase | Flask＋Supabase | **Django 6＋SQLite（ORM）** | Flask＋Supabase |
| 規模 | 87 個 route 檔、182 個測試檔 | 單檔 `app.py`（109 個函式）、14 個測試檔 | 約 7,100 行 Python、193 個測試 | 24 個 route 檔、測試僅我新增的 5 個 |
| 「人」的鍵 | `users.id`＋LINE ID | `users.line_user_id`（文字） | `LineAccount.line_user_id`（沒有 Django 使用者） | `users.id`（日記另用 `line_user_id` 文字） |
| 權限 | `permissions.py` 權限矩陣（副標籤×後台模塊）、`guard.py` 公開端點防護、權限撤銷即時生效 | 管理員白名單、牧者白名單 | `is_pastor`／`is_staff` 旗標＋M2M 負責小組；三個裝飾器 | 只有 admin／super_admin 兩級 |
| 稽核 | `audit.py`、取消不是刪除（有測試 `test_deletions_leave_a_trace`） | 無 | 無 | 無（`audit_logs` 無建表語句） |
| 備份 | 備份完整性有測試（`test_backup_is_complete`） | 無 | 數位遺囑 ZIP／HTML 匯出、Drive／Dropbox 備份 | 手寫分類，漏表 |
| 帳號合併 | `user_merge.py`，**失敗還原且不刪帳號**（#460） | — | — | 合併後刪舊列、失敗被吞 |
| PWA／登入接力 | `packages/line-pwa-kit`（可移植）、web-push-kit、photo-upload | `sso.py`、`pwa_session.py`（接收端） | `apps/users/sso.py`、`pwa.py`、token middleware | 無（無 PWA 續登） |
| 教學導覽 | `data-tour`（7 處）＋導覽交接包 | 有 | `static/tour.js` | 無 `data-tour`，另有獨立 tutorial 頁 |
| RLS（schema.sql） | 0 條 `ENABLE ROW LEVEL SECURITY` | 3 條；自述有 15 張表 RLS 關閉 | 不適用（SQLite） | 0 條 |

**結論：成熟度排序為 event-registration- ≫ cell_reporter ≈ tianfu-diary ≫ 本 repo。** 本 repo 的價值是「已經把四個系統放在同一個 Flask 裡跑過」，不是品質。

## 2. cell_reporter：架構差異最大，逐項對照

| 面向 | cell_reporter | 本 repo 的移植版（`routes/cell_report.py`） | 判斷 |
|---|---|---|---|
| 框架 | Django ORM、model 約束 | Flask＋Supabase 手寫查詢，約束靠程式 | 約束少了一層。例如 `Attendance` 的 `unique_together`、`CellReport` 的 `(group, week_date)` 唯一，要確認 schema 有同樣的唯一鍵（`cell_attendance` 與 `cell_reports` 有 `UNIQUE`，其餘待逐一核對） |
| 身分 | `LineAccount` 是唯一身分，沒有「使用者表」；`line_login_required` 還會檢查帳號是否仍存在（帳號被刪、session 活一年會讓整站 500，已修） | 用整合系統 `users`；`is_pastor`／`is_staff` 在**登入當下算一次** | 失去「帳號被刪即退回登入頁」的保護；權限變更不即時（對照 event-registration- 的 `refresh_session_permissions`） |
| **組員（Member）** | **只是姓名**，屬於某小組，沒有任何人的連結；`is_active` 軟刪除 | 加了 `user_id`（可連結系統帳號）、`is_confirmed`、`contact_info`，以及 `link_member_ajax` | **展示站新增的連結與你「點名不要跟 ID 串聯」的決定相反。** cell_reporter 的原始做法反而是脫鉤的，可以當你這次決定的先例 |
| 出席狀態 | `full／late／leave／absent`，**預設 `full`** | 沿用，無預設概念 | 與規格「預設全員未點」衝突，見 §5-3 |
| **空白不當 0** | 有完整測試：空白不存、空白不覆蓋舊值、填 0 要二次確認、無聚會時略過確認；**這個 bug 曾上線兩次**（「長輩小組長最致命的錯誤」） | 12 處 `or 0`／`get(..., 0)`；主日、兒童、禱告會、晨禱人數缺值就寫 0 | **回歸。** 展示站把已修好的 bug 又帶回來了 |
| **GET 不得建資料列** | 刻意設計：開啟舊週報不能 `get_or_create`，否則儀表板會誤報「已開始回報」 | `section1`、`section2`、`step3` 的 GET 路徑都呼叫 `_get_or_create_report`（`cell_report.py` 約 403、434 行） | **回歸**，同上 |
| 小組整體狀況 | 文字**或**照片皆可，後端 `_has_group_status_content()` 與前端 `groupStatusFilled()` 必須一致，有測試 | 未逐行核對 | 待審 |
| 時間 | `TIME_ZONE='Asia/Taipei'`、`USE_TZ=False`（存本地時間，不是 UTC） | 37 處 `date.today()`（伺服器時區） | 兩邊都不符「存 UTC、顯示轉台北」。cell_reporter 的資料若要搬進來，日期欄位（週報日期）是「日期」不是「時間點」，可不轉；`created_at` 等時間點要轉 |
| 開通申請 | `/line/apply/` 組長申請→同工核准，可從申請自動建組；有 12 條測試 | 無（`cell_report.py` 內沒有 apply） | **展示站少了整個流程**，是否需要要問教會 |
| 備份 | SQLite→Google Drive／Dropbox、數位遺囑 ZIP／HTML | 由 `backup`／`data_transfer` 的手寫清單涵蓋 | 資料搬遷路徑要設計（見 §6） |
| PWA／SSO | 有簽章 token middleware、跟教會入口的 SSO 接收端 | 無 | 用 event-registration- 的 `line-pwa-kit` 補 |
| 自評四面向 | `self_eval.py` 單一來源（views 與匯出共用，避免兩份對照表不一致），有舊值翻譯 | 內嵌；`good/normal/bad` 與 `good/mid/bad` 兩種值並存的風險 | 搬資料時要處理舊值 |
| 測試 | 193 個，覆蓋上述全部「刻意的決定」 | 無 | **這 193 個測試的案例是最有價值的資產**，應轉成對展示站的守衛 |

cell_reporter 的 CLAUDE.md 有一節「Things that are deliberately the way they are」，那些全部是踩過的坑。**展示站的移植沒有帶過來。**

## 3. tianfu-diary

- 單檔 `app.py`，資料表 7 張（`users`、`diary_entries`、`pastor_whitelist`、`diary_share_grants`、`diary_plan`、`admin_whitelist`、`future_diary_grants`）。**以 `line_user_id` 文字為鍵**，沒有指向 `users.id`。
- 已有 SSO 接收端（#81）、PWA session、讀經進度表批次匯入（`plan_import.py`）。
- 與報名系統的**讀經重複**：報名系統的 365 速讀＋日記的 `user_reading_progress`（25 人），**同一人可能兩邊都有進度**（event-registration- 已記錄為未決的「內容層」問題）。
- 14 個測試，含 smoke（打每條路由確認沒有 5xx）、CSRF、登入強化。

## 4. event-registration- 可直接沿用的資產（對本 repo 的缺口一一對應）

| 缺口（見 GAP_REPORT） | event-registration- 的對應 | 備註 |
|---|---|---|
| 只有兩級權限、無模塊矩陣 | `routes/permissions.py`：`ADMIN_MODULES`（key、名稱、URL 前綴）；權限存在 `groups.admin_modules`；超管編輯 | 新模塊必須登記前綴，否則不受管控；有測試守著 |
| 手寫登入檢查 55 處 | `decorators.py`＋掃描測試 | |
| 合併刪列、失敗被吞 | `user_merge.py`＋`test_user_merge.py`（共用引用清單、搬移失敗會還原、失敗時不刪帳號） | **已查證：全部搬完後仍會刪除被合併者的 `users` 列（`user_merge.py:263`）。** 規格守衛 22 要求「只標記、不刪列」，要沿用就得改這一行與對應測試 |
| 備份漏表 | `backup.py`＋`test_backup_is_complete.py` | 登記驅動 |
| 稽核缺 | `audit.py` | 僅記一筆；點名的只追加稽核要另建（我已做在 `rc_audit`） |
| 時間 | `tests/test_time_handling.py`（AST 守衛）、`tw_time.py` | 直接沿用 |
| 公開端點防護 | `guard.py`（速率限制＋蜜罐） | 點名不是公開端點，用不到；但開通申請、公開回報表單（主日／兒童／禱告會免登入）用得到 |
| 取消不是刪除 | `participation.cancel_registration` | 同精神，已用在點名（軟離開） |
| 登入／PWA | `packages/line-pwa-kit`（13 條驗收清單） | 可複製整包 |
| 導覽 | 導覽交接包、`data-tour` | 我新增的 `static/tour.js` 要與其對齊（事實：他們的導覽實作我尚未讀） |
| 測試慣例 | `conftest.py`（CSRF 在共用 client 關閉，另有專測；mutation 驗證）、`pytest.ini`、query budget 測試 | 我寫的 `tests/conftest.py` 要改對齊 |

## 5. 需要你決定的衝突（Rule 7：攤開，不折衷）

1. **event-registration- 在 2026-09-12 明確決定「三個系統不合」**（維持現狀，共用程式碼、不共用基礎建設；理由：沒有自己的網域，換 origin 會讓既有 PWA 安裝與推播訂閱作廢，且沒有人會知道要回來重新訂閱）。**你現在要整合，與那個決定相反。**
   - 本 repo 是「同一個網域、同一個 Flask」的整合，所以 origin 問題不成立；但**正式站（安南）若要遷入就會踩到**。
   - 之前的決定是「安南不遷入、新教會用新平台」。若維持這個前提，兩者不衝突：整合版只給新教會用，安南繼續用三個獨立系統。
   - **請確認：整合版是否只給新教會，安南不遷入？**
2. **身分：規格的 `person_id` 單一底層 vs 你「點名脫鉤」。** cell_reporter 的組員本來就是只有姓名（脫鉤），展示站新增的 `user_id` 連結反而是偏離。建議：點名與小組回報的組員都維持名冊式脫鉤；`link_member_ajax`／`user_id`／`is_confirmed` 列為待清理（不立即刪）。
3. **出席預設值：** cell_reporter 預設 `full`（組長加快填寫），規格要「預設全員未點」。兩者針對的場景不同（小組長週報 vs 執事個人點名）。建議各自保留，不強行統一，但「未點」必須在畫面與資料上可區分。
4. **讀經兩套：** 報名系統 365 速讀 vs 日記進度。已確認要合為「一個讀經計畫模塊」，計畫由教會匯入（附錄 L-7）。**需要你決定用誰當底**（報名系統的計畫在 repo 內、日記的在資料庫 `diary_plan` 並有批次匯入）。
5. **RLS：** 規格（附錄 J-4）要求每張表開 RLS 且不設政策。event-registration- 與本 repo 的 `schema.sql` 都是 0 條；tianfu-diary 自述 15 張表關閉並寫「**不要自動修**——開 RLS 而沒有 policy 會把表鎖死」。**這只在伺服器用「服務端金鑰」時才安全，我沒有驗證各系統實際用哪把金鑰（附錄 J 也寫了同樣的未驗證）。** 在確認前，我的 `012_roll_call.sql` 開了 RLS：若本系統用的是 anon 金鑰，**點名頁會讀不到資料**。需要你確認金鑰種類。
6. **PR 流程差異：** event-registration- 規定開 PR 後立即退訂、不經確認直接 squash merge；本 session 的規則是建 PR 後訂閱事件。你的偏好（Rule 19）是測試通過就合併。建議本 repo 沿用 Rule 19，不另訂。

## 6. 建議的整合路線（在本 repo 就地重構）

> 與 GAP_REPORT §5 的階段 A–F 對應，但**基準改為 event-registration-**，並加入 cell_reporter 的「回歸修復」。

| 階段 | 內容 | 來源 |
|---|---|---|
| 0 | 修展示站已知回歸：小組回報「空白當 0」、「GET 建資料列」；把 cell_reporter 的 193 個測試案例轉成守衛 | cell_reporter 測試 |
| A | 守衛先行：`tests/conftest.py` 對齊 event-registration-；掃描型守衛（`users` 凍結清單、schema 涵蓋、路由權限掃描、時間 AST 守衛） | event-registration- 的測試 |
| B | 結構補齊：可重複執行的 `schema.sql`、`audit_logs`、RLS（**金鑰確認後**） | GAP_REPORT |
| C | 權限矩陣（`permissions.py` 搬入）、`user_merge`、`backup` 登記驅動、`line-pwa-kit` | event-registration- |
| D | 小組回報重構：組員維持名冊式、補開通申請（若教會需要）、時間統一 | cell_reporter |
| E | 讀經合一、日記對齊 `person_id`（若選配） | tianfu-diary＋報名系統 |
| F | 聚會點名接上權限矩陣與稽核慣例；名冊匯入預覽；出席率規則（待問卷） | 本 repo＋規格 |

## 7. 未驗證／限制

- 三個參考 repo 只讀了 CLAUDE.md、模型、權限與稽核等關鍵檔，**沒有逐行審**；event-registration- 的 CLAUDE.md 約 3,300 行，只讀了與整合直接相關的段落。
- 沒有執行任何參考 repo 的測試，所以「193／182 個測試」是檔案計數與測試名稱，不是「全綠」的證明。
- 沒有連線任何正式資料庫；人數、筆數引自各 CLAUDE.md 的自述。
- cell_reporter 是否有正式環境資料、要不要遷入，尚未討論。

## 8. 已決定事項（2026-11-06，對 §5 的回覆）

1. **安南暫時不遷入**：整合版只給新教會用，因此 2026-09-12「三個系統不合」的 origin／PWA／推播問題不影響本整合。
2. **讀經**：只擷取天父日記「讀經進度表批次匯入」的後台功能模塊（預覽、確認、逐格編輯、範本）作為讀經計畫模塊的匯入流程；**天父日記本身維持原樣**。
3. **Supabase 會重開新專案**：金鑰與 RLS 採 `docs/SUPABASE_SETUP.md` 的建議（服務端金鑰＋全表 RLS 不設政策）。
4. **帳號合併沿用 event-registration- 的 `user_merge.py`**（全部搬完才刪被合併者的 `users` 列、失敗會還原）。規格守衛 22「不得刪除 users 列」因此**對帳號合併放寬**，其餘情況仍適用。
5. 展示站新增的 `link_member_ajax`／`user_id`／`is_confirmed` **列為待清理**（先不刪）；點名與小組回報組員維持名冊式脫鉤。

### 進度
- 階段 0 已完成：修正小組回報三個回歸（空白當 0、GET 建資料列、聚會回報無法儲存）。
- 階段 B 部分完成：`schema.sql` 補齊到「程式用到的每張表都有」、RLS 全開（本機 Postgres 驗證）。
- 下一步：階段 A（`users` 凍結清單、`/admin/` 路由權限掃描、時間 AST 守衛），然後階段 C（權限矩陣、`user_merge`、備份登記制）。

### 階段 A 完成（2026-11-06）
- 結構守衛已上線（`tests/test_structure_guards.py`），基準：直接查 `users` **112 次／17 個檔案**、`date.today()` 類 **43 次**、`or 0` **46 次**（8 個檔案）。
- **盤點出 19 個沒掛 `admin_required` 的 `/admin` 路由**：7 個是同工簽到（掛 `staff_required`，刻意開放給同工）、12 個是函式開頭手寫檢查（金流 3、福音探索 8、個人資料 1）。**沒有發現完全沒設防的路由。** 這 19 個列入基準，之後遷移成統一裝飾器只會減少。
- 帳號合併有兩個入口會刪除 `users` 列（`admin.py` 管理員合併、`profile.py` 自助合併），已記為已知。
- 下一步（階段 C）：搬入 event-registration- 的權限矩陣（`permissions.py`）與 `user_merge`，備份改登記驅動。

### 階段 C（部分）：權限矩陣已移植（2026-11-06）
- 已移植 event-registration- 的後台權限矩陣：`routes/permissions.py`（22 個模塊）、`/admin/permissions` 編輯頁（僅超管）、`groups.admin_modules`（migration 014）、後台首頁卡片依權限顯示。
- 與成熟版的差異：**沒登記的後台路徑對副標籤成員一律拒絕（fail closed）**；金流刻意不交給矩陣；session 的 `'*'` 只有現在仍是管理員才算數。
- 順手把福音探索後台 8 個、會友資料編輯 1 個手寫權限檢查改成統一裝飾器；沒掛 `admin_required` 的 `/admin` 路由基準 19 → 10（7 個同工簽到＋3 個金流）。
- **尚未移植**：`refresh_session_permissions`（定期重算，讓降權／矩陣調整不用重新登入）、`user_merge`、備份登記制。其中 `refresh_session_permissions` 影響「撤銷是否立即生效」，建議下一步優先做。

### 階段 C（續）：權限撤銷立即生效已移植（2026-11-06）
- `refresh_session_permissions()`（成熟版機制，針對本系統調整）：每 5 分鐘重算；登入與重算共用 `_permission_fields()`；失敗維持原狀；不碰 `is_demo`。
- **結構守衛基準刻意上調 1 次**：`routes/auth.py` 直接查 `users` 15 → 16（重算必須讀 users 那一列）。這是唯一一次「增加」，已在 `tests/structure_baseline.json` 的差異裡可見。
- 仍待移植：`user_merge`（帳號合併，沿用成熟版）、備份登記制。

### 階段 C（續）：帳號合併已移植（2026-11-06）
- 沿用成熟版 `user_merge`（兩個入口共用、失敗全部還原、搬完確認才刪）；清單改以本系統 `schema.sql` 為準，並擴充測試（每個欄位真的會搬、任一步失敗都還原、唯一限制衝突的處置、兩個入口的端對端）。
- **查出並修正的舊問題**：舊清單把 `session_attendance` 寫成不存在的 `course_attendance`（門訓出席沒被搬）、漏了 `audit_logs.actor_id`、`material_transactions.created_by` 是不存在的欄位；舊流程失敗時照樣刪帳號。
- **新增欄位層級的 schema 守衛**：程式寫入的每個欄位，`schema.sql` 都要有。第一次掃就抓到 19 個缺口，這次補了 10 個（聚會回報的 `submitted_by`／`updated_at`、`visitor_forms.uploaded_by`，migration 015），**還剩 9 個已登記為已知缺口**（只准減少）：`devotional_registrations.paid_at／paid_quantity`、`diary_plan.date`、`materials.cover_url`、`prayer_comments.is_anonymous`、`prayers.answered_at／archived_at`、`users.provider／provider_user_id`。這些要逐一確認型別與用途後補，建議下一個 PR 處理。
- 結構守衛基準：`users` 直接查詢 113 → 110（admin −4、profile −4、新增 `user_merge` +5）；刪除 `users` 列的路徑收斂為 `user_merge` 一條。
- 仍待處理：備份登記制（階段 C 最後一項）；上述 9 個 schema 缺口。

### 階段 C（續）：schema 欄位缺口已清空（2026-11-06）
- migration 016 補上最後 9 個缺口，「程式寫入的每個欄位 `schema.sql` 都要有」的守衛現在是**零例外**（`KNOWN_MISSING_COLUMNS` 為空集合；之後新增寫入欄位卻沒補 schema 就會紅）。
- `diary_plan` 的日期欄位：程式與 CLAUDE.md 都用 `date`，schema 原本寫成 `plan_date`（新專案的天父日記讀經進度會整個讀不到）；已改成 `date`，並在 migration 內把舊資料庫的 `plan_date` 改名（有測試在真實 Postgres 上驗證改名與可重複執行）。
- 這一批的欄位型別是依程式用法與天父日記原專案的 schema 決定的（`provider`／`provider_user_id` 沿用原專案型別）；**未在真實 Supabase 驗證**。
- 仍待處理：備份登記制（階段 C 最後一項）。

### 功能模組化：登記表已建立（2026-11-06）
- `routes/modules.py`：18 個選配模組＋1 個展示站專用模組的登記表（網址前綴、依賴）；`/admin/modules` 讓超管開關；全站網址攔截、模板 `module_on()`、後台 `can_see()`、權限矩陣都走同一份判定。
- 測試守衛：每條路由必須歸屬某個模組或明確列為核心（`CORE_PREFIXES`，且核心清單不能腐爛）；首頁／同工頁／後台首頁指向選配模組的連結必須有開關守著；關閉後網址 404、依賴連帶關閉、儲存立即生效、僅超管可改、展示功能不靠資料庫開關。
- **分類是我依你的預設自行決定的**（你說「照你建議」）：電子簽到併入「活動報名與簽到」、牧者／同工查閱併入「小組回報」、牧者查閱日記併入「天父日記」；金流獨立並依賴活動報名。若教會需要拆開再調整登記表即可。
- **刻意不做／尚未做**：① 備份與匯出不隨模組隱藏（資料安全優先，與規格的「備份選項一起消失」不同）；② 部署精靈還沒有「選功能」這一步；③ 模組內部的細項（例如小組回報裡的小開關）維持原樣；④ 手冊與教學導覽尚未依模組隱藏；⑤ 目前沒有背景排程，提醒由前端觸發，所以沒有需要處理的排程。
- 預設全部開啟（既有部署不變）；新教會部署時由超管在 `/admin/modules` 關掉不需要的。

### 部署精靈與交接手冊（2026-11-06）
- **更正**：我先前說「27 個功能區塊一律無條件註冊」不完全正確 —— `app.py` 其實已有 6 個模組（門訓、行事曆、週報、代禱、福音、留名單）用 `ENABLE_*` 環境變數在啟動時決定要不要註冊，而且 `guide`／`tutorial` 也讀它。啟動時不註冊會讓模板裡的連結指向不存在的網址。
- **整合（Rule 7：不留兩套互相衝突的做法）**：選登記表（執行時、超管後台、會隱藏連結、有測試）。舊的環境變數降級為「預設值」（`modules.ENV_DEFAULTS`），已經設過的部署升級後行為不變；6 個藍圖一律註冊；`Config.ENABLE_*` 移除；`guide`／`tutorial` 改走登記表。部署精靈裡原本那段「設 ENABLE_XXXXX=false 可停用」的說明改成列出登記表現況。
- 新增 `docs/NEW_CHURCH_SETUP.md`（非技術者交接手冊，規則 14 三項之一）。其中「完整還原演練」標為尚未做過。
- 仍待處理：備份登記制；手冊與教學導覽中屬於其他模組（日記、禱讀本、點名…）的段落尚未依模組隱藏（目前只有 6 個舊模組＋檔案分享會被隱藏）。

### 階段 C（完成）：備份登記制（2026-11-06）
- `backup_registry.py` 成為「備份哪些表」的單一來源；超管匯出／匯入與測試都讀它。測試守：schema 每張表都登記、匯入順序外鍵安全、衝突欄位等於真實主鍵、匯出→空庫匯入→逐表比對筆數（還原演練）、讀取中途失敗要中止、缺表要分得出來、不信任 ZIP 內檔名。全部做過 mutation 驗證。
- **查出並修正的舊問題**：舊匯出把「讀取失敗」當成「沒有資料」（可能產出殘缺備份）；舊匯入以硬寫的衝突欄位 upsert（部分表主鍵不是 `id`）；舊匯出漏掉檔案／資料夾列表、留名單、稽核日誌、禱讀本、點名等；`backup.py` 把資料庫失敗標成「尚未啟用」。
- **需要你決定的事**：① 天父日記內容（`diary_entries`）與分享授權目前**不在超管匯出內**（隱私考量，與「開發者不接觸教會用戶資料」一致），代價是災難還原時日記無法靠本匯出復原，需靠 Supabase 專案層級備份——要不要改成「教會超管可選擇性匯出」？② `material_stock` 是檢視表，不匯出（由 `material_transactions` 重算）。
- **未驗證**：真實 Supabase 上的匯出／匯入；`docs/NEW_CHURCH_SETUP.md` 的「完整還原演練」仍需在真實專案做一次。
- 仍待處理：手冊與教學導覽依模組隱藏；cell_report 的 `link_member_ajax`／`user_id`／`is_confirmed` 待清理；出席率規則預設值（等問卷）；查詢者／匯出授權矩陣（等與教會討論）。
