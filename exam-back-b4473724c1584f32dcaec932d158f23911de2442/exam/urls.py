from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/users/', include('users.urls')),
    path('api/question-bank/', include('question_bank.urls')),
    path('api/exam/', include('exam_core.urls')),
    path('api/student/', include('apps.student.urls')),
]
