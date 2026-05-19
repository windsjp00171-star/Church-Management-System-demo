from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Rate limiter（供 files blueprint 使用）
limiter = Limiter(key_func=get_remote_address, default_limits=[])
