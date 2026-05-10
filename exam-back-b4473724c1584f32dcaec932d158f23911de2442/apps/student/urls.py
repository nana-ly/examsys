from django.urls import path
from .views import (
    ExamListView, ExamDetailView, SubmitAnswerView,
    WrongQuestionListView, WrongQuestionAddView, WrongQuestionMasterView,
    AIQuestionGenerateView, AIQuestionAskView
)

urlpatterns = [
    path('exams/', ExamListView.as_view(), name='exam-list'),
    path('exams/<int:exam_id>/', ExamDetailView.as_view(), name='exam-detail'),
    path('exams/<int:exam_id>/submit/', SubmitAnswerView.as_view(), name='exam-submit'),
    path('wrongbook/', WrongQuestionListView.as_view(), name='wrongbook-list'),
    path('wrongbook/add/', WrongQuestionAddView.as_view(), name='wrongbook-add'),
    path('wrongbook/<int:wrong_id>/master/', WrongQuestionMasterView.as_view(), name='wrongbook-master'),
    path('ai/generate_question/', AIQuestionGenerateView.as_view(), name='ai-generate-question'),
    path('ai/ask/', AIQuestionAskView.as_view(), name='ai-ask'),
]
