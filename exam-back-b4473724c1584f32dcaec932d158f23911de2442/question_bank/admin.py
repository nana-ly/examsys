from django.contrib import admin
from .models import Question

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ['content', 'question_type', 'difficulty', 'knowledge_point', 'creator']
    list_filter = ['question_type', 'difficulty']
    search_fields = ['content', 'knowledge_point']