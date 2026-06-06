from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.contrib.auth import login, logout
from django.middleware.csrf import get_token

from users.models import User
from users.serializers import (
    UserRegisterSerializer, UserLoginSerializer, UserSerializer,
)
from typing import Optional, Dict, Any, Union


class AuthViewSet(viewsets.GenericViewSet):
    """用户认证视图集"""
    permission_classes = [AllowAny]
    serializer_class = UserRegisterSerializer
    
    @action(detail=False, methods=['post'])
    def register(self, request):
        """用户注册（教师注册已关闭，仅限学生自助注册）"""
        role = request.data.get('role', 'student')
        if role == 'teacher':
            return Response(
                {'error': '教师账号由管理员统一创建，不开放自主注册，请联系管理员'},
                status=status.HTTP_403_FORBIDDEN
            )
        serializer = UserRegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response({
                'message': '注册成功',
                'user': UserSerializer(user).data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['post'])
    def login(self, request):
        """用户登录"""
        serializer = UserLoginSerializer(data=request.data)
        if serializer.is_valid():
            validated: Union[Dict[str, Any], Any] = serializer.validated_data
            if validated is None:
                return Response({'error': '验证数据为空'}, status=status.HTTP_400_BAD_REQUEST)
            user: Optional[User] = validated.get('user')
            if user is None:
                return Response({'error': '用户验证失败'}, status=status.HTTP_400_BAD_REQUEST)
            login(request, user)
            return Response({
                'message': '登录成功',
                'user': UserSerializer(user).data,
                'csrfToken': get_token(request)
            })
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def logout(self, request):
        """用户登出"""
        logout(request)
        return Response({'message': '登出成功'})
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def me(self, request):
        """获取当前用户信息"""
        return Response(UserSerializer(request.user).data)

    @action(detail=False, methods=['patch'], permission_classes=[IsAuthenticated])
    def me_update(self, request):
        """更新当前用户个人信息（教师和学生通用）"""
        import re
        user = request.user
        real_name = (request.data.get('real_name') or '').strip()
        phone = (request.data.get('phone') or '').strip()
        email = (request.data.get('email') or '').strip()

        if not real_name:
            return Response({'error': '真实姓名不能为空'}, status=400)
        if phone and not re.match(r'^1[3-9]\d{9}$', phone):
            return Response({'error': '手机号格式不正确'}, status=400)
        if email and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
            return Response({'error': '邮箱格式不正确'}, status=400)

        user.real_name = real_name
        user.phone = phone or ''
        user.email = email or ''
        user.save(update_fields=['real_name', 'phone', 'email'])

        return Response({
            'message': '个人信息更新成功',
            'real_name': user.real_name,
            'phone': user.phone,
            'email': user.email,
        })
