from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import QuestionViewSet

router = DefaultRouter()
router.register(r'', QuestionViewSet, basename='questions')

urlpatterns = [
    path('', include(router.urls)),
]
