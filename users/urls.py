from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AuthViewSet
from .class_views import UserViewSet, ClassViewSet, StudentClassViewSet

router = DefaultRouter()
router.register(r'auth', AuthViewSet, basename='auth')
router.register(r'users', UserViewSet, basename='users')
router.register(r'classes', ClassViewSet, basename='classes')
router.register(r'student-classes', StudentClassViewSet, basename='student-classes')

urlpatterns = [
    path('', include(router.urls)),
]
