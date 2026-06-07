from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from django_filters.rest_framework import DjangoFilterBackend

from .models import Question
from .serializers import (
    QuestionSerializer, QuestionListSerializer,
    QuestionCreateSerializer, QuestionFilterSerializer
)


class QuestionViewSet(viewsets.ModelViewSet):
    """题目管理视图集"""
    queryset = Question.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['content', 'knowledge_point']
    ordering_fields = ['created_at', 'difficulty']
    filterset_fields = ['question_type', 'difficulty', 'knowledge_point', 'creator']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return QuestionListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return QuestionCreateSerializer
        return QuestionSerializer
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return []
        return [IsAuthenticated()]
    
    def perform_create(self, serializer):
        if self.request.user.role not in ['teacher', 'admin']:
            raise PermissionDenied('只有教师或管理员才能创建题目')
        serializer.save(creator=self.request.user)
    
    @action(detail=False, methods=['get'])
    def filter(self, request):
        """自定义筛选接口"""
        filter_serializer = QuestionFilterSerializer(data=request.query_params)
        if not filter_serializer.is_valid():
            return Response(filter_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        queryset = self.get_queryset()
        filters_data = filter_serializer.validated_data
        
        if filters_data.get('question_type'):
            queryset = queryset.filter(question_type=filters_data['question_type'])
        if filters_data.get('knowledge_point'):
            queryset = queryset.filter(knowledge_point__icontains=filters_data['knowledge_point'])
        if filters_data.get('difficulty'):
            queryset = queryset.filter(difficulty=filters_data['difficulty'])
        if filters_data.get('keyword'):
            queryset = queryset.filter(content__icontains=filters_data['keyword'])
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = QuestionListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = QuestionListSerializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def knowledge_points(self, request):
        """获取所有知识点列表"""
        knowledge_points = Question.objects.exclude(
            knowledge_point__isnull=True
        ).exclude(
            knowledge_point=''
        ).values_list('knowledge_point', flat=True).distinct()
        return Response(list(knowledge_points))
    
    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """获取题目统计信息"""
        question = self.get_object()
        return Response({
            'id': question.id,
            'content': question.content[:50],
            'question_type': question.get_question_type_display(),
            'difficulty': question.get_difficulty_display(),
            'usage_count': question.question_papers.count(),
        })
