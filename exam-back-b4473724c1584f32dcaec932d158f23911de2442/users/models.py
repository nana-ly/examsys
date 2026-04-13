from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """自定义用户模型"""
    ROLE_CHOICES = [
        ('student', '学生'),
        ('teacher', '教师'),
        ('admin', '管理员'),
    ]
    
    role = models.CharField('角色', max_length=20, choices=ROLE_CHOICES, default='student')
    phone = models.CharField('手机号', max_length=20, blank=True, null=True)
    real_name = models.CharField('真实姓名', max_length=50, blank=True, null=True)
    
    class Meta:
        db_table = 'users'
        verbose_name = '用户'
        verbose_name_plural = verbose_name


class Class(models.Model):
    """班级表"""
    name = models.CharField('班级名称', max_length=100)
    teacher = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='created_classes',
        limit_choices_to={'role': 'teacher'},
        verbose_name='创建教师'
    )
    class_code = models.CharField('班级码', max_length=20, unique=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        db_table = 'classes'
        verbose_name = '班级'
        verbose_name_plural = verbose_name
    
    def __str__(self):
        return self.name


class StudentClass(models.Model):
    """学生班级关联表"""
    student = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='student_classes',
        limit_choices_to={'role': 'student'},
        verbose_name='学生'
    )
    class_obj = models.ForeignKey(
        Class, 
        on_delete=models.CASCADE, 
        related_name='class_students',
        verbose_name='班级'
    )
    joined_at = models.DateTimeField('加入时间', auto_now_add=True)
    
    class Meta:
        db_table = 'student_classes'
        verbose_name = '学生班级关联'
        verbose_name_plural = verbose_name
        unique_together = ['student', 'class_obj']
    
    def __str__(self):
        return f"{self.student.username} - {self.class_obj.name}"
