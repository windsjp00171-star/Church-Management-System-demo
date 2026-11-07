"""沉默的依賴要在表單上講出來

## 這一步在解什麼

`routes/setting_deps.py` 把 11 條依賴收成一張註冊表 —— 但**註冊表本身
不會講話**。規則寫得再對，管理員在後台開活動時看到的還是同一張空白的紙。

原本的四種待遇裡，七條是「完全不講」、一條是「存好了才 alert」。
這一份守的是「**現在都在他改的那一格旁邊講了**」。

## 三個各自會失敗的地方

1. **註冊表加了一條，模板沒開位置** → 那條規則永遠沒有地方顯示，
   而後端測試全綠。`test_every_dep_has_a_place_on_the_form`
2. **前端自己判一份** → 改了規則畫面不會跟，兩邊都看起來正常。
   `test_the_wording_only_lives_on_the_server`
3. **提示讀的值跟存進去的值不同份** → 「提示說我沒填，可是我明明填了」。
   `test_the_draft_is_collected_once`

## ★ 掃原始碼的斷言擋不住「守衛永遠放行」

所以下面有真的打 HTTP 的那一節（`test_the_endpoint_*`）——
端點回什麼、擋不擋沒登入的人，都是實際跑出來的。
"""
import json
import re
from pathlib import Path

import pytest

from routes.setting_deps import DEPENDENCIES, entries, messages

ROOT = Path(__file__).resolve().parent.parent
TPL = ROOT / 'templates' / 'admin' / 'event_form.html'

#  ★ 模板 ＋ 它 `asset()` 進來的 JS。
#
#    即時提示的行為搬到 `static/js/dep-hints.js`（跟課程表單共用）之後，
#    只讀 .html 就掃不到那幾件事了。`source_bundle` 是為了這個存在的 ——
#    見 conftest 的說明：搬到 static/ 之後只讀模板，測試會**綠得很安靜**。
#    （這一次是紅的，因為斷言剛好夠具體。）
from tests.conftest import source_bundle

SRC = source_bundle('admin/event_form.html')

EVENTS = [d for d in DEPENDENCIES if d.module == 'events']


def _strip_comments(text):
    """★ 這個專案已經被自己的說明文字騙過五次。

    我在註解裡寫的 `data-dep="<key>"`、寫的規則文案，都會讓掃原始碼的
    斷言自己通過 —— 測試綠，功能沒做。所以一律先把註解拿掉再掃。
    """
    text = re.sub(r'\{#.*?#\}', ' ', text, flags=re.S)      # Jinja
    #  ★ JS 區塊註解只認**自成一行**的。整份掃 `/*…*/` 的話，
    #    `accept="image/*"` 裡那個 `/*` 會跟六百行後的某個 `*/` 配成一對，
    #    把整段 HTML（包含所有錨點）一起吃掉 —— 而測試只會說「找不到」。
    text = re.sub(r'^[ \t]*/\*.*?\*/', ' ', text, flags=re.S | re.M)
    text = re.sub(r'^\s*//.*$', ' ', text, flags=re.M)      # JS 行
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.S)     # HTML
    return text


CODE = _strip_comments(SRC)


def _anchors(text):
    return set(re.findall(r'data-dep="([^"]+)"', text))


# ══ 一、每一條都要有地方可以講 ══════════════════════

@pytest.mark.parametrize('dep', EVENTS, ids=lambda d: d.key)
def test_every_dep_has_a_place_on_the_form(dep):
    """★★★ 註冊表登記了，模板就要開一格。

    這一條是整份的重點。少開一格的症狀是**那條規則靜靜地不出現**：
    後端測試全綠（規則確實算對了），畫面上什麼都沒有 ——
    跟這七條當初「完全不講」的狀態一模一樣。
    """
    assert dep.key in _anchors(CODE), (
        f'註冊表有 {dep.key}，但 event_form.html 沒有 data-dep="{dep.key}" 的位置')


def test_no_anchor_points_at_a_rule_that_does_not_exist():
    """反過來：模板上的格子也要對得到規則。

    改 key 的時候只改一邊，那一格會永遠空著 —— 而空的格子看不出來
    （`:empty` 會把它收掉，那是刻意的）。
    """
    keys = {d.key for d in DEPENDENCIES}
    orphans = _anchors(CODE) - keys
    assert not orphans, f'模板上這幾格對不到註冊表：{orphans}'




# ══ 二、字只有一份（在伺服器上）═══════════════════════

@pytest.mark.parametrize('dep', EVENTS, ids=lambda d: d.key)
def test_the_wording_only_lives_on_the_server(dep):
    """★★★ 模板不可以自己抄一份後果文案。

    抄一份的話，改了 `effect` 畫面上不會跟 —— 而兩邊都看起來正常。
    這正是這個專案整章在講的那個形狀。

    ★ 比對用 `effect` 的前 12 個字（去掉 `**` 強調記號）：
      整句比對太容易因為標點就漏掉，而抄的人通常是整段複製。
    """
    head = dep.effect.replace('**', '')[:12]
    assert head not in CODE, (
        f'{dep.key} 的後果文案被抄進模板了（「{head}…」）—— 規則只能有一份')


def test_the_form_asks_the_server_instead_of_judging_by_itself():
    """提示要真的去問伺服器，不是前端自己算。"""
    assert '/admin/events/check-deps' in CODE


# ══ 三、提示讀的值 ＝ 存進去的值 ══════════════════════



#  ★ 下面兩條守的是**共用那一支**（`static/js/dep-hints.js`）的行為。
#    抽出去之後函式名字換了（`syncDepHints` → `schedule`），
#    所以直接讀那個檔案，不要在 bundle 裡撈 —— bundle 裡還有模板的字，
#    切段容易切錯。
SHARED_JS = _strip_comments(
    (ROOT / 'static' / 'js' / 'dep-hints.js').read_text(encoding='utf-8'))


def test_the_hint_cannot_loop_forever():
    """★★ 收草稿的過程本身會觸發 input/change（活動表單的
    `syncOptionRows()` 會改隱藏欄位），而那又會排下一次檢查。

    沒有防護的話就是每 400 毫秒自動送一次，永遠停不下來 ——
    而畫面上完全正常，要打開 Network 面板才看得到。

    ★ 這條是**結構斷言**，不是行為斷言：它證明防護寫在那裡，
      不證明它擋得住。拿掉那個旗標這條會紅，這是它的價值。
    """
    body = SHARED_JS.split('function schedule(')[1].split('\n  }')[0]
    assert 'busy' in body, 'schedule() 沒有檢查「正在收值」'
    collect = SHARED_JS.split('function collect(')[1].split('\n  }')[0]
    assert 'busy = true' in collect and 'finally' in collect, \
        '收值時沒有把旗標立起來（或沒有用 finally 放下來）'


def test_a_network_failure_keeps_what_is_on_screen():
    """★ 連不上時不可以把已經顯示的提示清掉。

    清掉的話，網路抖一下＝問題看起來自己好了。
    """
    #  ★ 一定要先切出 `run()` 的**函式體**再看 —— 只 split 到檔案結尾的話
    #    會連下面 `render()` 的定義一起掃進來，對一個完全正確的實作報錯。
    #    這個專案已經踩過一模一樣的一次。
    body = SHARED_JS.split('function run(')[1].split('\n  function ')[0]
    catch = body.split('.catch(')[1]
    assert 'render(' not in catch, '連線失敗時不該去動畫面'


def test_a_slow_reply_never_overwrites_a_newer_one():
    """★ 慢的那一份後到就要丟掉 —— 不然畫面會倒退回幾個字之前的狀態，
    而使用者看到的是「我改好了它還在唸」。"""
    body = SHARED_JS.split('function run(')[1].split('\n  function ')[0]
    assert 'mine !== seq' in body, '沒有丟掉過期的回應'


# ══ 四、端點真的會回話（不是掃原始碼）═══════════════

URL = '/admin/events/check-deps'
HDR = {'X-CSRF-Token': 'test-csrf-token'}


def _post(client, payload):
    return client.post(URL, json=payload, headers=HDR)
















# ══ 五、entries / messages 是同一份字 ════════════════

def test_entries_and_messages_never_diverge():
    """`messages()` 是 `entries()` 的投影，不是第二份實作。"""
    ctx = {'event': {'waitlist_enabled': True}, 'fields': [],
           'primary_groups': ['活水小組']}
    assert messages('events', ctx) == [e['text'] for e in entries('events', ctx)]


def test_entries_are_json_safe():
    """要能直接 jsonify —— 帶了 Dep 物件進去的話端點會 500。"""
    ctx = {'event': {'waitlist_enabled': True, 'allow_external_reg': True},
           'fields': [], 'primary_groups': []}
    json.dumps(entries('events', ctx))


# ══ 六、提醒只准講一次，而且要**處理得掉** ════════════

"""使用者：「我改報名期限一直跳警告 這個會有問題嗎」

他在改一個完全無關的欄位（報名期限），而每存一次檔就被一個
`alert()` 對話框擋一次，內容是他畫面上那格橘字**已經寫著的同一句話**。

★ 那個 alert 是「提示格還不存在」的年代留下來的，加了即時提示之後
  沒有跟著拿掉。`static/js/dep-hints.js` 自己的說明就寫過：

      ★「講在他改的那一格旁邊」是重點，不是排版偏好。
        存好了才 alert 的話，那一刻他的注意力已經在別的事情上。

★★ 而且他**處理不掉**：那條提醒講的是「候補截止時間」，
   但那一格在候補沒開的時候是 `display:none` —— 要清的東西看不到。
   一個關不掉的警告比沒有警告更糟：久了就沒有人相信任何一條。
"""

from pathlib import Path

FORM = Path(__file__).resolve().parent.parent / 'templates' / 'admin' / 'event_form.html'


def _js(src):
    """去掉註解再掃。

    ★ 這份註解裡就寫著 `alert('⚠️ 外部報名提醒…` 在解釋為什麼拿掉 ——
      不去註解的話，下面那條「不可以用 alert」會被自己的說明打中。
      （這個專案被自己的註解騙過很多次，所以一律先過這一關。）
    """
    src = re.sub(r'\{#[\s\S]*?#\}', '', src)      # Jinja 註解
    src = re.sub(r'/\*[\s\S]*?\*/', '', src)      # 區塊註解
    return re.sub(r'(?m)^\s*//.*$', '', src)      # 整行的 //


def test_saving_does_not_pop_a_dialog_for_the_inline_hints():
    """★ 依賴提醒不可以用 `alert` 再唸一次 —— 表單上已經有即時提示格。"""
    js = _js(FORM.read_text(encoding='utf-8'))
    hit = re.search(r'alert\([^)]*form_hints', js)
    assert not hit, '又用對話框把提示唸第二次了'




def test_every_rule_has_a_live_hint_slot_on_the_form():
    """★ 上面那條（不要 alert）成立的前提：**每一條規則都看得到**。

    哪天加了一條規則卻忘了在表單上開一格，它會變成
    「存檔說有 1 項提醒，而畫面上一個字都沒有」—— 比 alert 更糟。
    """
    from routes.setting_deps import DEPENDENCIES
    src = FORM.read_text(encoding='utf-8')
    slots = set(re.findall(r'data-dep="([a-z_]+)"', src))
    missing = [d.key for d in DEPENDENCIES
               if d.module == 'events' and d.key not in slots]
    assert not missing, f'這幾條規則在表單上沒有提示格：{missing}'




