"""
自定义中间件：安全刷新 Session 过期时间。

只对已认证用户刷新 Session 过期时间，避免 SESSION_SAVE_EVERY_REQUEST=True
在 DB 读 Session 失败时把空 Session 写回数据库导致永久 401。
"""
from django.conf import settings


class RefreshSessionMiddleware:
    """每次请求刷新已认证用户的 Session 过期时间（滑动窗口）"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # 仅当用户已认证且 Session 有效时才延长过期时间
        # 匿名用户或 Session 损坏时不操作，避免空覆盖
        if request.user.is_authenticated and request.session.session_key:
            request.session.set_expiry(settings.SESSION_COOKIE_AGE)
        return response
