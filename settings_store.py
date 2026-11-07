from db import supabase
from routes import cache

_DEFAULTS = {
    'max_storage_gb': '10',
}


def _all():
    """整張 settings 表（很小）快取起來：首頁一次載入會問好幾個 key，各查一趟很浪費。

    ★ 寫入一定要走 `set()`（它會 bust）。直接寫 settings 表的地方（目前只有小組回報那幾個
      `meeting.*`／`module.*` key，而且不是用這支讀的）改完不會讓這份快取失效，最多舊 TTL 秒。
    """
    def build():
        rows = supabase.table('settings').select('key, value').execute().data or []
        return {r['key']: r['value'] for r in rows}
    return cache.get('settings_all', build)


def get(key):
    # 資料庫連不上時 build() 會丟例外、往上傳（不快取失敗），跟原本逐 key 查的行為一樣
    value = _all().get(key)
    return value if value is not None else _DEFAULTS.get(key)


def set(key, value):
    supabase.table('settings').upsert({'key': key, 'value': str(value)}).execute()
    cache.bust('settings_all')


def get_max_storage_bytes():
    gb = int(get('max_storage_gb') or 10)
    return gb * 1024 * 1024 * 1024
