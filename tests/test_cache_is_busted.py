"""行程內快取：**每一個 key 都要有人 `bust()` 它**

## 為什麼這一條是現在才補的

TTL 從 60 秒調成 10 分鐘（使用者回報「PWA 讀取都很慢」）。原因是量出來的
流量密度：七天只有 37 筆寫入動作、**平均間隔 3.5 小時** —— 60 秒的快取
在正式站上**幾乎沒有生效過**，每個人打開首頁都付 17 趟而不是 11 趟。

★★ 而「後台改完、前台還是舊的」從來不是靠 TTL 擋的，是靠 `bust()`。
   TTL 只在「有人漏了 `bust()`」那一天才有意義 —— 而那天的代價
   從 60 秒變成 10 分鐘。

**提高一個風險就要同時把守衛架上去**，不然那一改就是在賭。所以這一份。

## 這裡守的是「有沒有人清」，不是「清得對不對」

`bust()` 叫對 key 但叫錯時機（例如寫入失敗也清）不在這一份的範圍 ——
那只會多一次查詢，不會讓畫面說假話。真正會讓畫面說假話的只有一種：
**有一個 key 從頭到尾沒有任何人清它**。
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ROUTES = sorted((ROOT / 'routes').glob('*.py')) + [ROOT / 'settings_store.py']   # settings_store 在根目錄


def _code(path):
    """去掉註解和 docstring。

    ★★ 這份底下每一條要掃的字（`bust(`、key 的名字）在 `cache.py`
      的說明註解裡都出現過 —— 不去掉的話，「有人清」這件事會被
      一段**在解釋為什麼要清**的註解滿足，而實際上沒有人清。
      （這個專案記過的坑，這是第六次。）
    """
    src = path.read_text(encoding='utf-8')
    src = re.sub(r'"""[\s\S]*?"""', '', src)
    src = re.sub(r"'''[\s\S]*?'''", '', src)
    return re.sub(r'(?m)#.*$', '', src)


def cached_keys():
    """程式裡真的被快取的那些 key（掃 `cache.get('X', …)`）。"""
    keys = {}
    for p in ROUTES:
        if p.name == 'cache.py':
            continue
        for m in re.finditer(r"_?cache\.get\(\s*'([^']+)'", _code(p)):
            keys.setdefault(m.group(1), []).append(p.name)
    return keys


def busted_keys():
    """被 `bust()` 清過的 key，以及是誰清的。"""
    out = {}
    for p in ROUTES:
        if p.name == 'cache.py':
            continue
        for m in re.finditer(r"_?cache\.bust\(([^)]*)\)", _code(p)):
            for k in re.findall(r"'([^']+)'", m.group(1)):
                out.setdefault(k, set()).add(p.name)
    return out


# ══ 一、前提：真的掃得到東西 ═════════════════════════

def test_there_is_something_to_guard():
    """★ 掃不到任何 key 的話，底下每一條都會變成永遠綠的。"""
    keys = cached_keys()
    assert len(keys) >= 5, f'只掃到 {sorted(keys)} —— 比對方式可能過期了'


def test_the_scan_ignores_comments():
    """★ 前提的前提：`_code()` 真的有把註解拿掉。

    拿不掉的話，`cache.py` 裡那段「寫入端一定要 bust()」的說明
    會讓底下那條「有人清」自己通過。
    """
    from routes import cache
    assert 'bust()' in (ROOT / 'routes' / 'cache.py').read_text(encoding='utf-8')
    assert 'bust()' not in _code(ROOT / 'routes' / 'cache.py'), \
        '註解沒被拿掉 —— 底下的斷言會被說明文字滿足'
    assert hasattr(cache, 'bust')


# ══ 二、★★ 主線：每一個 key 都要有人清 ═══════════════

@pytest.mark.parametrize('key', sorted(cached_keys()))
def test_every_cached_key_is_busted_by_some_write_path(key):
    """★★ 沒有人清的 key ＝ 後台改完，前台**最多舊 10 分鐘**。

    而使用者看到的是「我剛剛那一下沒有存到」，他會再存一次、
    再重整一次，然後來問。**畫面上完全正常** —— 那一頁確實在，
    只是說的是十分鐘前的事。
    """
    who = busted_keys().get(key)
    assert who, (
        f"`{key}` 有被快取，但**沒有任何寫入端 `cache.bust('{key}')`**。\n"
        f"  → 改完之後前台最多會舊 10 分鐘（TTL），而畫面上看不出來。\n"
        f"  → 在那張表的新增／修改／刪除端點加上 bust。")


def test_nobody_busts_a_key_that_is_not_cached():
    """★ 反過來：清一個沒有人快取的 key 是**打錯字**的症狀。

    真正該清的那個還留在快取裡，而程式看起來有在清。
    """
    extra = set(busted_keys()) - set(cached_keys())
    assert not extra, (
        f'這幾個 key 有人清、卻沒有人快取，多半是打錯字：{sorted(extra)}')


# ══ 三、TTL 只有一份 ═════════════════════════════════

def test_the_ttl_has_exactly_one_source():
    """★★ 原本 `DEFAULT_TTL` 是 60，而**四個呼叫端也各自寫了 60**。

    以後要調整只會改到其中一邊，另一邊安靜地維持舊值 ——
    而那看起來就是「快取有時候有效有時候沒效」。
    """
    for p in ROUTES:
        if p.name == 'cache.py':
            continue
        for m in re.finditer(r"_?cache\.get\([^)]*", _code(p)):
            call = m.group(0)
            assert not re.search(r",\s*\d+\s*,", call), (
                f'{p.name} 的呼叫端自己寫死了 TTL：{call[:60]}…\n'
                '  → 拿掉那個數字，讓它用 cache.DEFAULT_TTL')


def test_the_ttl_is_long_enough_to_actually_help():
    """★★ 這一條記的是**為什麼**改長，不是改成多少。

    量出來的流量：七天 37 筆寫入動作、平均間隔 3.5 小時。
    TTL 比「兩個人來訪的間隔」短的話，快取幾乎永遠是冷的 ——
    程式在、測試綠，而它在正式站上從來沒有生效過。
    """
    from routes.cache import DEFAULT_TTL
    assert DEFAULT_TTL >= 300, (
        f'TTL 只有 {DEFAULT_TTL} 秒。這間教會的來訪間隔是以小時計的，'
        '這麼短的快取等於沒有快取（但看起來有）。')


# ══ 四、只快取「整張表的小清單」 ═══════════════════════

#  ★★ 這條比快不快重要得多。快取一份「跟這個使用者有關」的東西，
#    代價是**他看到別人的資料** —— 那不是效能問題，那是事故。
#
#  ★ 判準是 key 的名字：它是一張表／一份設定，不是一個人的東西。
PER_USER_SMELLS = ('my_', '_me', 'user_', '_user', 'session', 'reg_', 'answers')


@pytest.mark.parametrize('key', sorted(cached_keys()))
def test_no_cached_key_looks_like_it_belongs_to_one_person(key):
    bad = [s for s in PER_USER_SMELLS if s in key]
    assert not bad, (
        f'`{key}` 看起來是「某一個人的東西」（{bad}）。\n'
        '  ★ 行程內快取是**全站共用**的 —— 快取到跟使用者有關的資料，\n'
        '    下一個人就會看到上一個人的東西。只快取整張表的小清單。')




# ══ 六、★ 每一個寫入端點自己都要清（不只是「某個地方有人清」）═════════════

#  上面那條只問「這個 key 有沒有任何人清」—— 兩個端點寫同一張表、只有一個有 bust 的話它照樣綠，
#  而漏掉的那個端點改完之後前台就是舊的。所以這裡逐個函式驗：函式裡寫了被快取的表，
#  就要在**同一個函式**裡 bust 對應的 key。
#  （對照表是寫死的：新增一個被快取的 key 卻沒補這裡，最後一條會紅。）
TABLE_KEYS = {
    'portal_links': {'portal_links_active', 'portal_links_all'},
    'portal_card_settings': {'portal_card_settings'},
    'portal_cards': {'portal_cards'},
    'verse_custom_themes': {'verse_custom_themes_active'},
}
SETTINGS_KEY = 'settings_all'          # 由 settings_store.set() 負責（唯一合法的寫入口）


def _writers():
    """[(檔名, 函式名, 表, 函式原始碼)]：寫了被快取的表的每一個函式。"""
    import ast
    out = []
    for p in ROUTES:
        if p.name == 'cache.py':
            continue
        src = p.read_text(encoding='utf-8')
        lines = src.split('\n')
        for fn in ast.walk(ast.parse(src)):
            if not isinstance(fn, ast.FunctionDef):
                continue
            body = '\n'.join(lines[fn.lineno - 1:fn.end_lineno])
            for table in TABLE_KEYS:
                if re.search(rf"table\('{table}'\)[\s\S]{{0,200}}?\.(insert|update|delete|upsert)\(", body):
                    out.append((p.name, fn.name, table, body))
    return out


def test_there_are_writers_to_check():
    assert len(_writers()) >= 8, '掃不到寫入端點 —— 比對方式可能過期了'


@pytest.mark.parametrize('who', _writers(), ids=lambda w: f'{w[0]}::{w[1]}::{w[2]}')
def test_every_endpoint_that_writes_a_cached_table_busts_it_itself(who):
    name, fn, table, body = who
    code = re.sub(r'(?m)#.*$', '', body)
    for key in TABLE_KEYS[table]:
        assert re.search(rf"bust\([^)]*'{key}'", code), \
            f"{name}::{fn} 寫了 {table}，卻沒有在同一個函式裡 bust('{key}') —— 改完前台最多舊 10 分鐘"


def test_the_table_key_map_covers_every_cached_key():
    mapped = {k for ks in TABLE_KEYS.values() for k in ks} | {SETTINGS_KEY}
    assert set(cached_keys()) <= mapped, f'有被快取的 key 沒登記在 TABLE_KEYS：{sorted(set(cached_keys()) - mapped)}'


def test_settings_are_only_written_through_settings_store_set():
    """settings 的快取只有 `settings_store.set()` 會清。別的地方直接寫 settings 表，而且是被 settings_store.get
    讀的 key，就會讀到舊的（目前直接寫的只有小組回報那幾個 meeting.／module. key，它們不是這支讀的）。"""
    for p in ROUTES:
        code = _code(p)
        for m in re.finditer(r"table\('settings'\)[\s\S]{0,200}?\.(upsert|insert|update|delete)\(", code):
            seg = code[m.start():m.start() + 400]
            assert p.name == 'cell_report.py' or p.name == 'settings_store.py', \
                f"{p.name} 直接寫 settings 表 —— 改用 settings_store.set()（它會 bust 快取）"
