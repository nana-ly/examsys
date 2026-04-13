from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from .models import User, Class, StudentClass
from .serializers import (
    UserSerializer, UserListSerializer,
    ClassSerializer, ClassCreateSerializer,
    StudentClassSerializer, JoinClassSerializer
)


class UserViewSet(viewsets.ModelViewSet):
    """用户管理视图集"""
    queryset = User.objects.all().order_by('-date_joined')
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['username', 'real_name', 'phone']
    ordering_fields = ['date_joined', 'username']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return UserListSerializer
        return UserSerializer
    
    def get_permissions(self):
        if self.action in ['retrieve', 'update', 'partial_update']:
            return [IsAuthenticated()]
        return super().get_permissions()


class ClassViewSet(viewsets.ModelViewSet):
    """班级管理视图集"""
    queryset = Class.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'class_code']
    ordering_fields = ['created_at', 'name']
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ClassCreateSerializer
        return ClassSerializer
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return []
        return [IsAuthenticated()]
    
    def perform_create(self, serializer):
        if self.request.user.role != 'teacher':
            raise PermissionError('只有教师才能创建班级')
        serializer.save(teacher=self.request.user)
    
    @action(detail=True, methods=['get'])
    def students(self, request, pk=None):
        """获取班级学生列表"""
        class_obj = self.get_object()
        student_classes = StudentClass.objects.filter(class_obj=class_obj)
        serializer = StudentClassSerializer(student_classes, many=True)
        return Response(serializer.data)


class StudentClassViewSet(viewsets.ModelViewSet):
    """学生班级关联视图集"""
    queryset = StudentClass.objects.all()
    serializer_class = StudentClassSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.role == 'teacher':
            # 教师查看自己创建的班级的学生
            return StudentClass.objects.filter(class_obj__teacher=user)
        elif user.role == 'student':
            # 学生查看自己加入的班级
            return StudentClass.objects.filter(student=user)
        return StudentClass.objects.all()
    
    @action(detail=False, methods=['post'])
    def join(self, request):
        """学生加入班级"""
        serializer = JoinClassSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            student_class = serializer.save()
            return Response({
                'message': '加入成功',
                'data': StudentClassSerializer(student_class).data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['delete'], url_path='leave/(?P<class_id>[^/.]+)')
    def leave(self, request, class_id=None):
        """学生退出班级"""
        try:
            student_class = StudentClass.objects.get(student=request.user, class_obj_id=class_id)
            student_class.delete()
            return Response({'message': '退出成功'})
        except StudentClass.DoesNotExist:
            return Response({'error': '未找到该班级关联'}, status=status.HTTP_404_NOT_FOUND)
