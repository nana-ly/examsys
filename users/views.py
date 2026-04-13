from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.contrib.auth import login, logout

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
        """用户注册"""
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
                'user': UserSerializer(user).data
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
