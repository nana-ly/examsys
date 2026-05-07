from django.contrib import admin
from .models import User, Class, StudentClass

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['username', 'role', 'real_name', 'phone']
    list_filter = ['role']
    search_fields = ['username', 'real_name']

@admin.register(Class)
class ClassAdmin(admin.ModelAdmin):
    list_display = ['name', 'teacher', 'class_code', 'created_at']
    list_filter = ['teacher']
    search_fields = ['name', 'class_code']

@admin.register(StudentClass)
class StudentClassAdmin(admin.ModelAdmin):
    list_display = ['student', 'class_obj', 'joined_at']
    list_filter = ['class_obj']

# Register your models here.
