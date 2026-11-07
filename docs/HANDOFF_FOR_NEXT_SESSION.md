# 交接清單（給下一個對話）

> 更新：2026-11-06　狀態：程式能做的都已合併進 `main`，等待實際部署。
> 讀完這份再讀 `CLAUDE.md`（技術規則）與 `HANDOVER.md`（給教會同工的交接手冊）。

## 1. 程式碼在哪個 REPO

| 角色 | REPO | 怎麼處理 |
|---|---|---|
| **主 repo（所有程式碼都改這裡）** | `windsjp00171-star/Church-Management-System-demo` | 開發分支 `claude/happy-knuth-jgrms4`，已與 `main` 同步；工作完成後 PR 合併進 `main` |
| 參考（成熟版，唯讀） | `windsjp00171-star/event-registration-` | 安南靈糧堂正在用的最新、最穩定版本。權限矩陣、帳號合併是從這裡移植。**不要改它** |
| 參考（唯讀） | `windsjp00171-star/tianfu-diary` | 天父日記原專案 |
| 參考（唯讀） | `windsjp00171-star/cell_reporter` | 小組回報原專案（Django） |
| 來源（沒複製過） | `church-data-hub` | 檔案分享（R2）的原專案，程式已併入主 repo，不需要再看 |

**新對話要串連哪些 REPO**
1. 一定要：`Church-Management-System-demo`。
2. 只有在要「對照成熟版寫法」時才加：`event-registration-`。其他兩個參考 repo 通常不需要。
3. 加入方式：用 `add_repo`（owner=`windsjp00171-star`），讀取即可，不要對參考 repo 推送。
4. 先前對話的本機複製（`/home/user/event-registration-` 等）在新容器裡**不存在**，需要的話重新 clone。

## 2. 這個專案是什麼

整合型教會行政系統，**展示用 DEMO**，要能一間一間部署給新教會，各教會自己選要用哪些功能。
Flask + Supabase（PostgreSQL）+ LINE Login + Render。整合自四個子系統（見 `CLAUDE.md`）。
就地重構，**不另開新 repo**。

## 3. 已完成（皆已合併進 main，測試 464 條通過）

- 結構守衛（棘輪）、schema 完整性守衛（程式寫的每個欄位 schema 都要有）、migration 012～017
- 聚會點名（與使用者帳號脫鉤；`/roll-call` 是紙本樣式的點名單，自動建立主日與每週日的欄）、名冊匯入（先預覽、疑似重複須確認）
- 全職同工差勤（由 attendance 改名）
- 後台權限矩陣＋權限撤銷 5 分鐘生效
- 帳號合併（失敗全部還原）、手動建立會員前檢查疑似重複
- 功能模組登記表 `/admin/modules`（關掉＝整塊消失、不刪資料）；手冊／導覽／教學跟著隱藏
- 備份登記制（超管匯出／匯入、還原演練測試）；天父日記個人可匯出自己的，超管匯出不含日記
- 小組回報三項退步修復；聚會人數回報四頁改為需要同工以上登入
- 安全修正：牧者儀表板權限裝飾器順序錯誤（未登入也能看）、檔案分享密碼四個漏洞、匿名代禱留言外洩作者 ID、綠界回呼沒設金鑰仍可通過
- `imghdr`（Python 3.13 已移除）改為 `image_kind.py`
- 整個應用的啟動煙霧測試（`tests/test_app_boot.py`）＋授權探針

## 4. 下一步：實際部署（使用者會提供新帳號）

需要使用者提供：**新 Supabase 專案**、**Render 帳號**、**LINE Login channel**、自己的 LINE ID（當第一位超管）。

順序：
1. 新 Supabase 專案執行整份 `schema.sql`（已含 012～017），確認所有表開了 RLS
2. Render 建服務（連 `main`），填環境變數（見 `CLAUDE.md`「環境變數」）；Python 版本以 `PYTHON_VERSION` 為準，**不要只信 runtime.txt**
3. LINE Login 的 callback 填 Render 網址 `/auth/callback`
4. 用使用者的 LINE 登入，確認成為超管
5. 逐個模塊走主要操作；完整還原演練一次（匯出 → 空專案匯入 → 比對筆數）
6. 部署發現的問題逐一記錄、修正、合併

**金鑰不要貼在對話裡。** 用 Render／Supabase 連接器或安全表單設定。

## 5. 還沒做／等使用者決定

| 項目 | 狀態 |
|---|---|
| 出席率判定 | 使用者會再確認細節。方向：**越簡單越好**（日期區間內主日幾次、這個人到幾次）。現有的規則版本／請假／遲到選項過度複雜，確認後簡化 |
| `PRODUCT.md`、`SPEC.md` | 使用者最初附的規格檔，**repo 裡沒有**，等使用者放進來。不要自己編 |
| 小組回報舊欄位（`link_member_ajax`、`cell_members.user_id`、`is_confirmed`） | 使用者說可以晚點再決定；牽涉「會友自選小組＋管理員核准」功能。我的建議：只刪手動連結 |
| 聚會人數回報（四頁） | 與點名重複，先留著；之後若要「用點名人數取代手填」再談 |
| 8 個沿用舊模塊的功能邏輯測試（代禱、福音、行事曆、週報、禱讀本、留名單、通知、更新日誌） | 目前只有「不會 500」與授權探針；部署後實際使用再補 |

## 6. 使用者決定過、不要再提的事

- **不做**會員「標記離開」：離開的人帳號放著即可，有危害才用既有的「封鎖」；回來不需要解標記。
- **不做**「貼 LINE ID 直接綁定」：綁定唯一入口是「整合 LINE」（對方須自己登入過）。
- 天父日記：超管匯出不含內容（隱私），個人可匯出自己的。
- 不接觸教會用戶資料（開發者原則，見 `CLAUDE.md` 最後一節）。

## 7. 使用者的工作偏好（很重要）

- **一律用繁體中文**回覆。
- **先直接回答問題**，再說其他事；不要寫太長、不要自言自語、不要過度設計（使用者明確抱怨過）。
- **合併規則**：這個專案只有使用者一人作業，**測試通過就直接合併進 main，不要再問**。流程：commit → push → 開 draft PR → `unsubscribe_pr_activity` → 改 ready → squash merge → 用 `git merge -s ours origin/main` 讓分支對齊。
- **每次 commit 前更新 `CHANGELOG.md`**（繁體中文，插最上面）。
- **資料庫結構變更先說明完整 SQL、影響、怎麼還原**，使用者同意後再做；migration 一律可重複執行。
- 每個新守衛要做 **mutation 驗證**（故意弄壞，確認測試會紅）。
- 「長者友善」要看使用場景，不是所有頁面都要。
- 功能是否多餘由使用者判斷；不確定的事用一個簡短問題問清楚，不要一次丟很多選項。

## 8. 環境小提醒

- 跑測試：`python3 -m pytest tests -q`（目前 464 passed）；pandas 在新版 Python 要用未釘版本安裝。
- `tests/test_roll_call_db.py`、schema 的真實 Postgres 測試需要 root＋Postgres 16，沒有就略過。
- 動 `tests/structure_baseline.json` 要手動確認差異；`python tests/structure_scan.py` 會**直接覆寫基準**，會把增加也吃進去，不要盲目執行。
- 啟動煙霧測試在子行程執行，不汙染其他測試；新增需要權限的頁面，到 `tests/smoke_boot.py` 的 `PROBES` 加一行。

## 9. ★ 與成熟版 `event-registration-`（安南正式在用）的功能落差：**進度表**

成熟版比這個 demo 多約 75 個模組（對照 `routes/` 檔案清單，2026-11-07 查證）。成熟版 `CLAUDE.md` 是最完整的功能說明，要搬哪一項先讀那一節。
使用者選的做法：**A，逐批搬進這個 repo**（不改以成熟版為底；先前「就地重構」的決定不變）。

**表上列的 17 項功能，目前完成 6 項（約 3.5 成）**（更新：2026-11-07；做完一項就改這張表）

| 狀態 | 功能 | 成熟版檔案（`routes/`） | 這個 repo 的狀況 |
|---|---|---|---|
| ✅ | 引導式開活動 | `guided.py`、`setting_deps.py`、`templates/admin/event_guided.html` | #91、#92：頁面、草稿、設定依賴即時提示（`setting_deps` 少 2 條沒對應設定的規則） |
| ✅ | 報名表單強化（分級收費、生日、身分證、監護人、依生日判身分別、跳題、必填由伺服器驗證） | `field_types.py`、`event_fields.py`、`auto_tier.py`、`guardian.py`、`conditions.py`、`roc.py`、`tw_id.py`… | #81～#90（見第 10 節）。**還欠**：報名名單編輯彈窗／匯出認得新型別、報名確認頁摘要 |
| ✅ | 365 天聖經速讀計畫 | `bible_plan.py`、`data/bible_reading_plan_365.json` | #95。**沒搬**：每日推播、換計畫後台、首頁卡片快速「讀完了」 |
| ✅ | 經文內嵌與朗讀 | `bible_text.py`、`static/js/speech-queue.js` | #95 |
| ✅ | 公開端點防護（速率限制、蜜罐、身分證字號重複檢查） | `guard.py` | 本批：`compute-tier`／`compute-age`／外部報名。**沒搬**：沒有身分證欄位時退回姓名＋電話的重複比對（這邊外部報名沒有電話欄位）、`find` 查詢端點限流（沒有 `find`） |
| ⬜ | 手機推播 | `push.py`、`reading_nudge.py`、`reminders.py`、`quiet_hours.py`、`tasks.py` | 未做；讀經推播依賴它 |
| ⬜ | PWA 續登（裝完被要求輸入 LINE 帳密的問題） | `pwa_session.py`、`pwa_apps.py` | 未做 |
| ⬜ | 小舟 AI 助手 | `ai_help.py`、`help_*.py`、`assistant_identity.py` | 未做 |
| ⬜ | 主日信息（YouTube 按週分組） | `sermons.py`、`admin_sermons.py` | 未做 |
| ⬜ | 行事曆訂閱（.ics） | `calendar_feed.py` | 未做 |
| ⬜ | 門訓結業證書 | `certificate.py` | 未做 |
| ⬜ | 門訓平板簽到 | `courses_kiosk.py` | 未做 |
| ⬜ | 門訓教材 | `courses_materials.py` | 未做 |
| ⬜ | 首頁個人化待辦 | `my_todos.py`、`todos.py` | 未做（成熟版刻意**不做催繳**，見其 CLAUDE.md） |
| ⬜ | 生日祝賀 | `birthday.py` | 未做 |
| ⬜ | 使用數據 | `usage_stats.py`、`module_views.py` | 未做 |
| ✅ | 效能快取 | `cache.py` | 本批：`routes/cache.py` ＋ `settings_store` 與首頁的小表（快捷連結、磁磚設定、經文底圖）；首頁往返 16→10 趟。`Procfile` 的 `--threads 8` 本來就有。**沒搬**：`warm()`（要排程）、`reading_plans.forget_missing`、其他頁的查詢預算 |

**反過來**，這個 demo 有而成熟版沒有的：聚會點名、功能模組登記表、備份登記制、天父日記／檔案分享／小組回報（來自另外三個 repo）、`person.py`、啟動煙霧測試與授權探針。

**搬一批的流程**（照第 10 節那批的做法）：先讀成熟版 `CLAUDE.md` 對應段落 → 動資料庫先給使用者看完整 SQL 並等同意 → 用成熟版的測試當驗收（需要完整 app 的測試改用 `tests/editor_server.py` 子行程或簡化 app）→ mutation 驗證 → CHANGELOG → 合併。

## 10. 搬成熟版報名表單＋引導式開活動：**已完成**（使用者選 A：逐批搬進這個 repo）

| PR | 內容 |
|---|---|
| #81 | migration 018：`event_fields` 允許 birthday／id_number／fee／guardian、新增 `auto_tier`（**已部署的資料庫要執行 018**，可重複執行） |
| #84 | 純邏輯模組（`field_types`、`guardian`、`conditions`、`roc`、`tw_id`、`tw_phone`、`tw_time`、`auto_tier`、`event_fields`） |
| #86 | 共用 `static/js/form-fields.js`（三個報名入口不再各寫一套收值／必填／跳題）、`asset()` |
| #87 | 伺服器端驗證：必填、身分證檢查碼、監護人正規化（會員、外部、後台編輯三個寫入點） |
| #88 | 報名頁渲染四種新型別、`fee-total.js`、`compute-tier`／`compute-age`、`_enforce_auto_tiers`、`fee_display` |
| #89、#90 | 後台活動表單編輯器：型別下拉、價格逐列、依生日自動判定面板、年齡跳題、監護人「每個人都要填」、預覽跑同一份 JS（`/admin/events/preview-tier`） |
| #91 | 引導式開活動「✨ 我陪你開一場」（`routes/guided.py`、`/admin/events/guided`、`/guided/draft`） |
| #92 | 設定依賴即時提示（`routes/setting_deps.py`、`dep-hints.js`、`/admin/events/check-deps`） |
| #93 | 活動管理的聚焦式教學（`data-tour`）與手冊 |

**這一批刻意沒搬／還欠的（有需要再做）**
- ~~`compute-tier`／`compute-age` 沒有速率限制~~：已補（`routes/guard.py`，見第 9 節）。
- 報名名單編輯彈窗、Excel 匯出、名冊顯示對新型別（生日轉民國等）的支援；成熟版對應測試（`test_roc`、`test_event_fields` 的名單／匯出部分）還沒放回。
- 報名確認頁（`form-confirm.js`）與預覽「試按送出」的答案摘要；`test_auto_tier` 裡確認對話框那十條。
- `setting_deps` 兩條沒搬（外部報名姓名／電話欄位、會友保留名額）：這個 repo 沒有對應設定，檔案裡有 `shortcut:` 註解。課程表單的依賴提示也還沒接。
- 成熟版需要完整 app 假資料庫的路由測試，這個 repo 的架構不能這樣做，改由 `tests/editor_server.py`（子行程跑真的 app）＋ `test_guided_endpoints`／`test_check_deps_endpoint`／`test_event_editor_browser` 涵蓋；陌生人／一般會友的授權探針在 `tests/smoke_boot.py`。

**回到第 9 節的落差表挑下一批**（讀經計畫、推播、小舟…）。讀經計畫需要新表（`bible_reading_progress`、`bible_chapters`），動手前先把完整 SQL 給使用者看。
