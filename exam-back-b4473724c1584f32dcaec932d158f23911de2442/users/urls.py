from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse
from django.middleware.csrf import get_token
from .views import AuthViewSet
from .class_views import UserViewSet, ClassViewSet, StudentClassViewSet

def csrf_token_view(request):
    return JsonResponse({'csrfToken': get_token(request)})

router = DefaultRouter()
router.register(r'auth', AuthViewSet, basename='auth')
router.register(r'users', UserViewSet, basename='users')
router.register(r'classes', ClassViewSet, basename='classes')
router.register(r'student-classes', StudentClassViewSet, basename='student-classes')

urlpatterns = [
    path('csrf/', ensure_csrf_cookie(csrf_token_view), name='csrf'),
    path('', include(router.urls)),
]
