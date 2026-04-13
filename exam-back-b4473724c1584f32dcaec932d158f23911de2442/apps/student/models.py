from django.db import models
from django.conf import settings
from exam_core.models import ExamPaper
from question_bank.models import Question


class ExamRecord(models.Model):
    """考试记录表"""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name='学生'
    )
    exam_paper = models.ForeignKey(
        ExamPaper,
        on_delete=models.CASCADE,
        verbose_name='试卷'
    )
    score = models.DecimalField('得分', max_digits=5, decimal_places=1, null=True, blank=True)
    start_time = models.DateTimeField('开始时间', auto_now_add=True)
    end_time = models.DateTimeField('结束时间', null=True, blank=True)
    status = models.CharField('状态', max_length=20, default='ongoing')

    class Meta:
        db_table = 'student_exam_records'
        verbose_name = '考试记录'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.student} - {self.exam_paper.name}"


class AnswerDetail(models.Model):
    """答题详情表"""
    exam_record = models.ForeignKey(
        ExamRecord,
        on_delete=models.CASCADE,
        related_name='answer_details',
        verbose_name='考试记录'
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        verbose_name='题目'
    )
    student_answer = models.TextField('学生答案', blank=True)
    is_correct = models.BooleanField('是否正确', default=False)

    class Meta:
        db_table = 'student_answer_details'
        verbose_name = '答题详情'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.exam_record.student} - {self.question.content[:30]}"


class WrongQuestion(models.Model):
    """错题本表"""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name='学生'
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        verbose_name='题目'
    )
    is_mastered = models.BooleanField('是否掌握', default=False)
    added_at = models.DateTimeField('添加时间', auto_now_add=True)

    class Meta:
        db_table = 'student_wrong_questions'
        verbose_name = '错题本'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.student} - {self.question.content[:30]}"
