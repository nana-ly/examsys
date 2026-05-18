from django.db import models
from django.conf import settings


class Question(models.Model):
    """题库表"""
    QUESTION_TYPE_CHOICES = [
        ('choice', '选择题'),
        ('multiple_choice', '多选题'),
        ('true_false', '判断题'),
        ('fill_blank', '填空题'),
        ('essay', '简答题'),
    ]
    
    DIFFICULTY_CHOICES = [
        (1, '简单'),
        (2, '较简单'),
        (3, '中等'),
        (4, '较难'),
        (5, '困难'),
    ]
    
    question_type = models.CharField('题型', max_length=20, choices=QUESTION_TYPE_CHOICES)
    content = models.TextField('题目内容')
    options = models.TextField('选项', blank=True, default='{}', help_text='JSON格式，如：{"A": "选项1", "B": "选项2"}')
    answer = models.TextField('答案')
    analysis = models.TextField('解析', blank=True, null=True)
    knowledge_point = models.CharField('知识点', max_length=200, blank=True, null=True)
    difficulty = models.IntegerField('难度', choices=DIFFICULTY_CHOICES, default=3)
    score = models.IntegerField('分值', default=0)
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_questions',
        limit_choices_to={'role': 'teacher'},
        verbose_name='创建者'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'questions'
        verbose_name = '题目'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.get_question_type_display()}: {self.content[:50]}"
