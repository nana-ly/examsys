from django.db import models
from django.conf import settings
from question_bank.models import Question
from users.models import Class


class ExamPaper(models.Model):
    """试卷表"""
    name = models.CharField('试卷名称', max_length=200)
    target_class = models.ForeignKey(
        Class,
        on_delete=models.CASCADE,
        related_name='exam_papers',
        verbose_name='目标班级'
    )
    total_score = models.DecimalField('总分', max_digits=5, decimal_places=1, default=100)
    pass_score = models.DecimalField('及格分', max_digits=5, decimal_places=1, default=60)
    duration = models.IntegerField('时长(分钟)', default=120)
    end_time = models.DateTimeField('结束时间', blank=True, null=True)
    published_at = models.DateTimeField('发布时间', blank=True, null=True)
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_papers',
        limit_choices_to={'role': 'teacher'},
        verbose_name='创建者'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'exam_papers'
        verbose_name = '试卷'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def question_count(self):
        return self.paper_questions.count()


class ExamPaperQuestion(models.Model):
    """试卷题目关联表"""
    paper = models.ForeignKey(
        ExamPaper,
        on_delete=models.CASCADE,
        related_name='paper_questions',
        verbose_name='试卷'
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='question_papers',
        verbose_name='题目'
    )
    score = models.DecimalField('分值', max_digits=5, decimal_places=1, default=10)
    order = models.IntegerField('顺序', default=0)
    
    class Meta:
        db_table = 'exam_paper_questions'
        verbose_name = '试卷题目'
        verbose_name_plural = verbose_name
        unique_together = ['paper', 'question']
        ordering = ['order']
    
    def __str__(self):
        return f"{self.paper.name} - {self.question.content[:30]}"


class ExamRecord(models.Model):
    """考试记录表"""
    STATUS_CHOICES = [
        ('ongoing', '进行中'),
        ('submitted', '已提交'),
        ('graded', '已评分'),
    ]
    
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='exam_records',
        limit_choices_to={'role': 'student'},
        verbose_name='学生'
    )
    paper = models.ForeignKey(
        ExamPaper,
        on_delete=models.CASCADE,
        related_name='exam_records',
        verbose_name='试卷'
    )
    score = models.DecimalField('得分', max_digits=5, decimal_places=1, null=True, blank=True)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='ongoing')
    started_at = models.DateTimeField('开始时间', auto_now_add=True)
    submitted_at = models.DateTimeField('提交时间', null=True, blank=True)
    tab_switch_count = models.IntegerField('切屏次数', default=0)
    
    class Meta:
        db_table = 'exam_records'
        verbose_name = '考试记录'
        verbose_name_plural = verbose_name
        unique_together = ['student', 'paper']
        ordering = ['-started_at']
    
    def __str__(self):
        return f"{self.student.username} - {self.paper.name}"


class AnswerDetail(models.Model):
    """答题详情表"""
    record = models.ForeignKey(
        ExamRecord,
        on_delete=models.CASCADE,
        related_name='answer_details',
        verbose_name='考试记录'
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='answer_details',
        verbose_name='题目'
    )
    student_answer = models.TextField('学生答案')
    is_correct = models.BooleanField('是否正确', default=False)
    score = models.DecimalField('得分', max_digits=5, decimal_places=1, null=True, blank=True)
    
    class Meta:
        db_table = 'answer_details'
        verbose_name = '答题详情'
        verbose_name_plural = verbose_name
        unique_together = ['record', 'question']
    
    def __str__(self):
        return f"{self.record.student.username} - {self.question.content[:30]}"


class WrongQuestion(models.Model):
    """错题本表"""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wrong_questions',
        limit_choices_to={'role': 'student'},
        verbose_name='学生'
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='wrong_by_students',
        verbose_name='题目'
    )
    wrong_answer = models.TextField('错误答案')
    is_mastered = models.BooleanField('是否掌握', default=False)
    created_at = models.DateTimeField('记录时间', auto_now_add=True)
    mastered_at = models.DateTimeField('掌握时间', null=True, blank=True)
    
    class Meta:
        db_table = 'wrong_questions'
        verbose_name = '错题本'
        verbose_name_plural = verbose_name
        unique_together = ['student', 'question']
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.student.username} - {self.question.content[:30]}"
