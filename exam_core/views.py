from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Sum, Avg

from .models import ExamPaper, ExamPaperQuestion, ExamRecord, AnswerDetail, WrongQuestion
from question_bank.models import Question
from .serializers import (
    ExamPaperSerializer, ExamPaperListSerializer, ExamPaperCreateSerializer,
    ExamPaperQuestionSerializer, ExamRecordSerializer, ExamRecordDetailSerializer,
    AnswerDetailSerializer, SubmitAnswerSerializer, ExamStartSerializer,
    WrongQuestionSerializer, WrongQuestionCreateSerializer
)


class ExamPaperViewSet(viewsets.ModelViewSet):
    """试卷管理视图集"""
    queryset = ExamPaper.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name']
    ordering_fields = ['created_at', 'published_at']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return ExamPaperListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return ExamPaperCreateSerializer
        return ExamPaperSerializer
    
    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        
        if user.role == 'teacher':
            # 教师查看自己创建的试卷
            queryset = queryset.filter(creator=user)
        elif user.role == 'student':
            # 学生查看已发布且班级匹配的试卷
            queryset = queryset.filter(
                published_at__isnull=False,
                published_at__lte=timezone.now(),
                target_class__class_students__student=user
            ).distinct()
        
        return queryset
    
    def perform_create(self, serializer):
        if self.request.user.role not in ['teacher', 'admin']:
            raise PermissionError('只有教师或管理员才能创建试卷')
        serializer.save(creator=self.request.user)
    
    @action(detail=True, methods=['get'])
    def questions(self, request, pk=None):
        """获取试卷题目列表"""
        paper = self.get_object()
        questions = ExamPaperQuestion.objects.filter(paper=paper).order_by('order')
        serializer = ExamPaperQuestionSerializer(questions, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def add_question(self, request, pk=None):
        """向试卷添加题目"""
        paper = self.get_object()
        question_id = request.data.get('question_id')
        score = request.data.get('score', 10)
        
        try:
            question = Question.objects.get(id=question_id)
            order = paper.exampaperquestion_set.count()
            paper_question, created = ExamPaperQuestion.objects.get_or_create(
                paper=paper,
                question=question,
                defaults={'score': score, 'order': order}
            )
            if not created:
                return Response({'error': '该题目已在试卷中'}, status=status.HTTP_400_BAD_REQUEST)
            return Response({'message': '添加成功'})
        except Question.DoesNotExist:
            return Response({'error': '题目不存在'}, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=True, methods=['delete'], url_path='remove_question/(?P<question_id>[^/.]+)')
    def remove_question(self, request, pk=None, question_id=None):
        """从试卷移除题目"""
        paper = self.get_object()
        try:
            paper_question = ExamPaperQuestion.objects.get(paper=paper, question_id=question_id)
            paper_question.delete()
            return Response({'message': '移除成功'})
        except ExamPaperQuestion.DoesNotExist:
            return Response({'error': '题目不在试卷中'}, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """发布试卷"""
        paper = self.get_object()
        if paper.published_at:
            return Response({'error': '试卷已发布'}, status=status.HTTP_400_BAD_REQUEST)
        paper.published_at = timezone.now()
        paper.save()
        return Response({'message': '发布成功', 'published_at': paper.published_at})
    
    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """获取试卷统计信息"""
        paper = self.get_object()
        records = ExamRecord.objects.filter(paper=paper, status='graded')
        
        stats = {
            'total_students': paper.target_class.class_students.count(),
            'submitted_count': records.count(),
            'average_score': records.aggregate(Avg('score'))['score__avg'] or 0,
            'max_score': records.aggregate(Sum('score'))['score__sum'] or 0,
            'min_score': records.order_by('score').first().score if records.exists() else 0,
        }
        return Response(stats)


class ExamRecordViewSet(viewsets.ModelViewSet):
    """考试记录视图集"""
    queryset = ExamRecord.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['started_at', 'submitted_at']
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ExamRecordDetailSerializer
        return ExamRecordSerializer
    
    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        
        if user.role == 'student':
            queryset = queryset.filter(student=user)
        elif user.role == 'teacher':
            queryset = queryset.filter(paper__creator=user)
        
        return queryset
    
    @action(detail=False, methods=['post'])
    def start(self, request):
        """开始考试"""
        serializer = ExamStartSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        paper_id = serializer.validated_data['paper_id']
        user = request.user
        
        if user.role != 'student':
            return Response({'error': '只有学生才能参加考试'}, status=status.HTTP_403_FORBIDDEN)
        
        try:
            paper = ExamPaper.objects.get(id=paper_id)
        except ExamPaper.DoesNotExist:
            return Response({'error': '试卷不存在'}, status=status.HTTP_404_NOT_FOUND)
        
        # 检查是否已有考试记录
        record, created = ExamRecord.objects.get_or_create(
            student=user,
            paper=paper,
            defaults={'status': 'ongoing'}
        )
        
        if not created and record.status != 'ongoing':
            return Response({'error': '您已完成该考试'}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response({
            'message': '考试开始',
            'record': ExamRecordSerializer(record).data,
            'questions': ExamPaperQuestionSerializer(
                paper.paper_questions.all().order_by('order'),
                many=True
            ).data
        })
    
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """提交考试"""
        record = self.get_object()
        
        if record.status != 'ongoing':
            return Response({'error': '考试已提交'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 检查考试是否超时
        elapsed = (timezone.now() - record.started_at).total_seconds() / 60
        if elapsed > record.paper.duration:
            return Response({'error': '考试已超时'}, status=status.HTTP_400_BAD_REQUEST)
        
        serializer = SubmitAnswerSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        total_score = 0
        wrong_questions = []
        
        for answer_data in serializer.validated_data['answers']:
            question_id = answer_data.get('question_id')
            student_answer = answer_data.get('answer')
            
            try:
                question = Question.objects.get(id=question_id)
                is_correct = str(student_answer).strip() == str(question.answer).strip()
                score = 0
                
                if is_correct:
                    # 获取该题分值
                    paper_question = ExamPaperQuestion.objects.get(
                        paper=record.paper,
                        question=question
                    )
                    score = paper_question.score
                    total_score += float(score)
                
                # 保存答题详情
                AnswerDetail.objects.update_or_create(
                    record=record,
                    question=question,
                    defaults={
                        'student_answer': student_answer,
                        'is_correct': is_correct,
                        'score': score if is_correct else 0
                    }
                )
                
                # 记录错题
                if not is_correct:
                    wrong_questions.append({
                        'question': question,
                        'wrong_answer': student_answer
                    })
                    WrongQuestion.objects.update_or_create(
                        student=record.student,
                        question=question,
                        defaults={
                            'wrong_answer': student_answer,
                            'is_mastered': False
                        }
                    )
            
            except Question.DoesNotExist:
                continue
        
        # 更新考试记录
        record.score = total_score
        record.status = 'submitted'
        record.submitted_at = timezone.now()
        record.save()
        
        return Response({
            'message': '提交成功',
            'score': total_score,
            'wrong_count': len(wrong_questions)
        })
    
    @action(detail=True, methods=['get'])
    def review(self, request, pk=None):
        """查看答卷详情"""
        record = self.get_object()
        
        # 学生只能查看自己的已提交试卷
        if request.user.role == 'student' and record.student != request.user:
            return Response({'error': '无权限'}, status=status.HTTP_403_FORBIDDEN)
        
        if record.status == 'ongoing':
            return Response({'error': '考试进行中'}, status=status.HTTP_400_BAD_REQUEST)
        
        answers = AnswerDetail.objects.filter(record=record)
        serializer = AnswerDetailSerializer(answers, many=True)
        
        return Response({
            'record': ExamRecordSerializer(record).data,
            'answers': serializer.data
        })


class WrongQuestionViewSet(viewsets.ModelViewSet):
    """错题本视图集"""
    queryset = WrongQuestion.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['created_at']
    
    def get_serializer_class(self):
        if self.action == 'create':
            return WrongQuestionCreateSerializer
        return WrongQuestionSerializer
    
    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        
        if user.role == 'student':
            queryset = queryset.filter(student=user)
        elif user.role == 'teacher':
            queryset = queryset.filter(question__creator=user)
        
        return queryset
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """获取错题统计"""
        queryset = self.get_queryset()
        total = queryset.count()
        mastered = queryset.filter(is_mastered=True).count()
        
        return Response({
            'total': total,
            'mastered': mastered,
            'not_mastered': total - mastered
        })
    
    @action(detail=True, methods=['post'])
    def mark_mastered(self, request, pk=None):
        """标记为已掌握"""
        wrong = self.get_object()
        wrong.is_mastered = True
        wrong.mastered_at = timezone.now()
        wrong.save()
        return Response({'message': '已标记为掌握'})
    
    @action(detail=True, methods=['post'])
    def mark_not_mastered(self, request, pk=None):
        """标记为未掌握"""
        wrong = self.get_object()
        wrong.is_mastered = False
        wrong.mastered_at = None
        wrong.save()
        return Response({'message': '已标记为未掌握'})
