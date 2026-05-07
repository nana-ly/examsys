from django.contrib import admin
from .models import ExamPaper, ExamPaperQuestion, ExamRecord, AnswerDetail, WrongQuestion

@admin.register(ExamPaper)
class ExamPaperAdmin(admin.ModelAdmin):
    list_display = ['name', 'target_class', 'creator', 'published_at']
    list_filter = ['target_class']

@admin.register(ExamPaperQuestion)
class ExamPaperQuestionAdmin(admin.ModelAdmin):
    list_display = ['paper', 'question', 'score', 'order']

@admin.register(ExamRecord)
class ExamRecordAdmin(admin.ModelAdmin):
    list_display = ['student', 'paper', 'score', 'status']

@admin.register(AnswerDetail)
class AnswerDetailAdmin(admin.ModelAdmin):
    list_display = ['record', 'question', 'is_correct', 'score']

@admin.register(WrongQuestion)
class WrongQuestionAdmin(admin.ModelAdmin):
    list_display = ['student', 'question', 'is_mastered']