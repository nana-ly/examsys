from django.urls import path
from .views import (
    ExamListView, ExamDetailView, SubmitAnswerView,
    WrongQuestionListView, WrongQuestionAddView, WrongQuestionMasterView,
    AIQuestionGenerateView, AIQuestionAskView, StartExamView, ReportTabSwitchView,
    PracticeModeView, PracticeKnowledgePointsView
)

urlpatterns = [
    path('exams/', ExamListView.as_view(), name='exam-list'),
    path('exams/<int:exam_id>/', ExamDetailView.as_view(), name='exam-detail'),
    path('exams/<int:exam_id>/submit/', SubmitAnswerView.as_view(), name='exam-submit'),
    path('exams/<int:exam_id>/start/', StartExamView.as_view(), name='exam-start'),
    path('wrongbook/', WrongQuestionListView.as_view(), name='wrongbook-list'),
    path('wrongbook/add/', WrongQuestionAddView.as_view(), name='wrongbook-add'),
    path('wrongbook/<int:wrong_id>/master/', WrongQuestionMasterView.as_view(), name='wrongbook-master'),
    path('ai/generate_question/', AIQuestionGenerateView.as_view(), name='ai-generate-question'),
    path('ai/ask/', AIQuestionAskView.as_view(), name='ai-ask'),
    path('api/report_tab_switch/', ReportTabSwitchView.as_view(), name='report_tab_switch'),
    # 练习模式
    path('practice/', PracticeModeView.as_view(), name='practice-mode'),
    path('practice/knowledge_points/', PracticeKnowledgePointsView.as_view(), name='practice-knowledge-points'),
]
