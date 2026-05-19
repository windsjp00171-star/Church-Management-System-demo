from db import supabase

_DEFAULTS = {
    'max_storage_gb': '10',
}


def get(key):
    res = supabase.table('settings').select('value').eq('key', key).execute()
    if res.data:
        return res.data[0]['value']
    return _DEFAULTS.get(key)


def set(key, value):
    supabase.table('settings').upsert({'key': key, 'value': str(value)}).execute()


def get_max_storage_bytes():
    gb = int(get('max_storage_gb') or 10)
    return gb * 1024 * 1024 * 1024
