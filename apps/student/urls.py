from django.urls import path
from .views import (
    ExamListView, ExamDetailView, SubmitAnswerView,
    WrongQuestionListView, WrongQuestionAddView, WrongQuestionMasterView, WrongQuestionDeleteView,
    AIQuestionGenerateView, AIQuestionAskView, StartExamView, SaveProgressView, ReportTabSwitchView,
    PracticeModeView, PracticeKnowledgePointsView, StudyActivityView,
    PracticeRecordView, RecordDetailView, ProfileView,
    PracticeIncompleteView, PracticeRecordQuestionsView, PracticeRecordCompleteView,
    PracticeRecordDeleteView,
    StudySessionStartView, StudySessionEndView,
    ChangePasswordView, ForgotPasswordView, DailyStatsView,
    KnowledgeStatsView, StudyDurationStatsView
)

urlpatterns = [
    path('exams/', ExamListView.as_view(), name='exam-list'),
    path('exams/<int:exam_id>/', ExamDetailView.as_view(), name='exam-detail'),
    path('exams/<int:exam_id>/submit/', SubmitAnswerView.as_view(), name='exam-submit'),
    path('exams/<int:exam_id>/start/', StartExamView.as_view(), name='exam-start'),
    path('exams/<int:exam_id>/progress/', SaveProgressView.as_view(), name='exam-progress'),
    path('wrongbook/', WrongQuestionListView.as_view(), name='wrongbook-list'),
    path('wrongbook/add/', WrongQuestionAddView.as_view(), name='wrongbook-add'),
    path('wrongbook/<int:wrong_id>/master/', WrongQuestionMasterView.as_view(), name='wrongbook-master'),
    path('wrongbook/<int:wrong_id>/', WrongQuestionDeleteView.as_view(), name='wrongbook-delete'),
    path('ai/generate_question/', AIQuestionGenerateView.as_view(), name='ai-generate-question'),
    path('ai/generate/', AIQuestionGenerateView.as_view(), name='ai-generate'),
    path('ai/ask/', AIQuestionAskView.as_view(), name='ai-ask'),
    path('api/report_tab_switch/', ReportTabSwitchView.as_view(), name='report_tab_switch'),
    # 练习模式
    path('practice/', PracticeModeView.as_view(), name='practice-mode'),
    path('practice/knowledge_points/', PracticeKnowledgePointsView.as_view(), name='practice-knowledge-points'),
    path('practice/incomplete/', PracticeIncompleteView.as_view(), name='practice-incomplete'),
    # 做题记录
    path('practice/records/', PracticeRecordView.as_view(), name='practice-records'),
    path('practice/records/<int:record_id>/detail/', RecordDetailView.as_view(), name='record-detail'),
    path('practice/records/<int:record_id>/questions/', PracticeRecordQuestionsView.as_view(), name='practice-record-questions'),
    path('practice/records/<int:record_id>/complete/', PracticeRecordCompleteView.as_view(), name='practice-record-complete'),
    path('practice/records/<int:record_id>/', PracticeRecordDeleteView.as_view(), name='practice-record-delete'),
    # 学习活跃度
    path('activity/', StudyActivityView.as_view(), name='study-activity'),
    # 学生个人信息
    path('profile/', ProfileView.as_view(), name='student-profile'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    # 学习时段
    path('start_session/', StudySessionStartView.as_view(), name='start-session'),
    path('end_session/', StudySessionEndView.as_view(), name='end-session'),
    # 今日做题统计
    path('daily_stats/', DailyStatsView.as_view(), name='daily-stats'),
    # 知识点掌握分布
    path('knowledge_stats/', KnowledgeStatsView.as_view(), name='knowledge-stats'),
    # 学习时长统计
    path('duration_stats/', StudyDurationStatsView.as_view(), name='duration-stats'),
]
