"""看檔頭判斷圖片格式（png／jpeg／gif／webp），認不出來回 None。

取代標準函式庫的 imghdr：那個模組在 Python 3.13 已被移除，部署平台一升級，
上傳經文底圖／樣式會直接 500。不依賴資料庫或 Flask，可直接單元測試。
"""


def image_kind(data: bytes):
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if data[:3] == b'\xff\xd8\xff':
        return 'jpeg'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    return None
