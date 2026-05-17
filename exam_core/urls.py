from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ExamPaperViewSet, ExamRecordViewSet, WrongQuestionViewSet

router = DefaultRouter()
router.register(r'papers', ExamPaperViewSet, basename='papers')
router.register(r'records', ExamRecordViewSet, basename='records')
router.register(r'wrong-questions', WrongQuestionViewSet, basename='wrong-questions')

urlpatterns = [
    path('', include(router.urls)),
]
