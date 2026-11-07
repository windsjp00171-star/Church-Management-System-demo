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

## 9. ★ 與成熟版 `event-registration-`（安南正式在用）的功能落差

**這個 demo repo 缺少成熟版大約 75 個模組**（對照 `routes/` 檔案清單，2026-11-07 查證）。使用者發現的第一個是「引導式開活動」。
成熟版 `CLAUDE.md` 是最完整的功能說明，要搬哪一項先讀那一節。

| 缺的功能 | 成熟版檔案（`routes/`） | 備註 |
|---|---|---|
| **引導式開活動**（「我陪你開一場」） | `guided.py`、`setting_deps.py`、`templates/admin/event_guided.html`，路由在 `admin_events.py` | 使用者明確要求。它產生的欄位需要下面「報名表單強化」才跑得動 |
| 報名表單強化：分級收費、生日、身分證（檢查碼）、監護人、依生日自動判身分別、跳題條件、必填由伺服器驗證 | `field_types.py`、`event_fields.py`、`auto_tier.py`、`guardian.py`、`conditions.py`、`roc.py`、`tw_id.py`、`tw_phone.py`、`tw_time.py`、`option_caps.py`、`static/js/form-fields.js`、`admin_events.py` | **目前 demo 只支援 7 種基本欄位型別**（文字、長文字、單選、多選、下拉、數字、日期），成熟版有 11 種 |
| 推播、PWA 續登 | `push.py`、`pwa_session.py`、`pwa_apps.py`、`reminders.py`、`quiet_hours.py`、`tasks.py` | |
| 小舟 AI 助手 | `ai_help.py`、`help_*.py`、`assistant_identity.py` | |
| 365 讀經計畫、經文朗讀、主日信息（YouTube） | `bible_plan.py`、`bible_text.py`、`reading_*.py`、`sermons.py`、`admin_sermons.py` | |
| 行事曆訂閱、結業證書、門訓平板簽到、教材 | `calendar_feed.py`、`certificate.py`、`courses_kiosk.py`、`courses_materials.py` | |
| 首頁個人化待辦、生日祝賀、使用數據 | `my_todos.py`、`todos.py`、`birthday.py`、`usage_stats.py`、`module_views.py` | |
| 效能快取、公開端點防護 | `cache.py`、`guard.py` | |

**反過來**，這個 demo 有而成熟版沒有的：聚會點名、功能模組登記表、備份登記制、天父日記／檔案分享／小組回報（來自另外三個 repo）、`person.py`、啟動煙霧測試與授權探針。

**待使用者決定的做法**（尚未決定，先不要動手）：
- A. 逐批把成熟版功能搬進這個 repo（建議第一批：報名表單強化＋引導式開活動）；
- B. 改以成熟版為底，把 demo 獨有的搬過去（與先前「就地重構」的決定不同，要使用者重新同意）。
