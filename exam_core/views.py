from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from django.utils import timezone
from django.db.models import Sum, Avg, Count, Max, Min, Q

from users.models import Class
from question_bank.models import Question
from .models import ExamPaper, ExamPaperQuestion, ExamRecord, AnswerDetail, WrongQuestion
from .serializers import (
    ExamPaperSerializer, ExamPaperListSerializer, ExamPaperCreateSerializer,
    ExamPaperQuestionSerializer, ExamRecordSerializer, ExamRecordDetailSerializer,
    AnswerDetailSerializer, SubmitAnswerSerializer, ExamStartSerializer,
    WrongQuestionSerializer, WrongQuestionCreateSerializer, AutoGenerateSerializer
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
        elif self.action == 'auto_generate':
            return AutoGenerateSerializer
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
            raise PermissionDenied('只有教师或管理员才能创建试卷')
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
    


    @action(detail=False, methods=['post'], serializer_class=AutoGenerateSerializer)
    def auto_generate(self, request):
        """智能组卷：按难度/题型比例自动抽题"""
        data = request.data

        # 优先从 raw data 获取 JSON 格式的分布，否则用序列化器校验表单
        type_distribution = data.get('type_distribution')
        difficulty_distribution = data.get('difficulty_distribution')

        # 如果 type_distribution 是字符串（表单提交的JSON字符串），解析它
        if isinstance(type_distribution, str) and type_distribution:
            import json
            try:
                type_distribution = json.loads(type_distribution)
            except json.JSONDecodeError:
                type_distribution = None

        if isinstance(difficulty_distribution, str) and difficulty_distribution:
            import json
            try:
                difficulty_distribution = json.loads(difficulty_distribution)
            except json.JSONDecodeError:
                difficulty_distribution = None

        if isinstance(type_distribution, dict) and type_distribution:
            # raw data JSON 路径 — 直接用解析后的数据
            name = data.get('name')
            target_class_id = data.get('target_class')
            total_score = int(data.get('total_score', 100) or 100)
            duration = int(data.get('duration', 120) or 120)
        else:
            # HTML 表单路径 — 用序列化器校验
            serializer = AutoGenerateSerializer(data=data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            vd = serializer.validated_data
            name = vd['name']
            target_class_id = vd['target_class']
            total_score = vd.get('total_score', 100)
            duration = vd.get('duration', 120)
            type_distribution = vd['type_distribution']
            difficulty_distribution = vd.get('difficulty_distribution', {})

        try:
            target_class = Class.objects.get(id=target_class_id)
        except Class.DoesNotExist:
            return Response({'error': '班级不存在'}, status=status.HTTP_404_NOT_FOUND)

        if request.user.role not in ['teacher', 'admin'] or \
           (request.user.role == 'teacher' and target_class.teacher != request.user):
            return Response({'error': '无权为该班级创建试卷'}, status=status.HTTP_403_FORBIDDEN)

        import random

        type_counts = {k: int(v) for k, v in type_distribution.items() if int(v) > 0}
        diff_counts = {int(k): int(v) for k, v in difficulty_distribution.items() if int(v) > 0} if difficulty_distribution else {}

        total_by_type = sum(type_counts.values())
        total_by_diff = sum(diff_counts.values()) if diff_counts else total_by_type

        if diff_counts and total_by_type != total_by_diff:
            return Response({
                'error': f'题型分布总数({total_by_type})与难度分布总数({total_by_diff})不一致'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 按题型比例分配难度配额，构建 (题型×难度) 目标矩阵
        targets = {}
        for qtype, type_count in type_counts.items():
            if diff_counts:
                # 将 type_count 按难度比例分配
                allocated = 0
                diffs = sorted(diff_counts.keys())
                for idx, diff in enumerate(diffs):
                    if idx == len(diffs) - 1:
                        n = type_count - allocated
                    else:
                        n = round(type_count * diff_counts[diff] / total_by_diff)
                        n = min(n, type_count - allocated)
                    targets[(qtype, diff)] = n
                    allocated += n
            else:
                targets[(qtype, None)] = type_count

        selected = []
        used_ids = set()

        for (qtype, diff), target in targets.items():
            candidates = Question.objects.filter(question_type=qtype)
            if diff is not None:
                candidates = candidates.filter(difficulty=diff)
            candidates = list(candidates.exclude(id__in=used_ids).order_by('?')[:target])
            selected.extend(candidates)
            used_ids.update(q.id for q in candidates)

        # 如果某些 bucket 不足，从同题型其他难度补充
        shortage = total_by_type - len(selected)
        if shortage > 0:
            types_needed = {}
            for qtype, count in type_counts.items():
                already = sum(1 for q in selected if q.question_type == qtype)
                types_needed[qtype] = max(0, count - already)
            for qtype, need in types_needed.items():
                if need > 0:
                    extra = list(Question.objects.filter(
                        question_type=qtype
                    ).exclude(id__in=used_ids).order_by('?')[:need])
                    selected.extend(extra)
                    used_ids.update(q.id for q in extra)

        if not selected:
            return Response({'error': '题库中没有符合条件的题目'}, status=status.HTTP_400_BAD_REQUEST)

        question_count = len(selected)
        score_per_question = round(total_score / question_count, 1)

        paper = ExamPaper.objects.create(
            name=name,
            target_class=target_class,
            total_score=total_score,
            duration=duration,
            creator=request.user
        )

        for order, question in enumerate(selected):
            ExamPaperQuestion.objects.create(
                paper=paper,
                question=question,
                score=score_per_question,
                order=order
            )

        return Response({
            'message': '智能组卷成功',
            'paper': ExamPaperSerializer(paper).data,
            'question_count': question_count,
            'score_per_question': score_per_question
        })
    

    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """获取试卷统计信息"""
        paper = self.get_object()
        records = ExamRecord.objects.filter(paper=paper, status='submitted')

        stats = {
            'total_students': paper.target_class.class_students.count(),
            'submitted_count': records.count(),
            'average_score': float(records.aggregate(Avg('score'))['score__avg'] or 0),
            'max_score': float(records.aggregate(Max('score'))['score__max'] or 0),
            'min_score': float(records.order_by('score').first().score) if records.exists() else 0,
            'pass_count': records.filter(score__gte=60).count(),
            'pass_rate': round(records.filter(score__gte=60).count() / records.count() * 100, 1) if records.exists() else 0,
        }
        return Response(stats)

    @action(detail=False, methods=['get'])
    def class_statistics(self, request):
        """班级成绩分布统计"""
        class_id = request.query_params.get('class_id')
        if not class_id:
            return Response({'error': '请提供class_id参数'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            target_class = Class.objects.get(id=class_id)
        except Class.DoesNotExist:
            return Response({'error': '班级不存在'}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        if user.role == 'teacher' and target_class.teacher != user:
            return Response({'error': '无权查看该班级'}, status=status.HTTP_403_FORBIDDEN)

        papers = ExamPaper.objects.filter(target_class=target_class)
        records = ExamRecord.objects.filter(
            paper__in=papers,
            status__in=['submitted']
        )

        # 班级整体统计
        agg = records.aggregate(
            avg_score=Avg('score'),
            max_score=Max('score'),
            min_score=Min('score'),
            total_count=Count('id')
        )

        # 分数段分布
        score_ranges = [
            {'range': '0-59', 'label': '不及格', 'min': 0, 'max': 59},
            {'range': '60-69', 'label': '及格', 'min': 60, 'max': 69},
            {'range': '70-79', 'label': '中等', 'min': 70, 'max': 79},
            {'range': '80-89', 'label': '良好', 'min': 80, 'max': 89},
            {'range': '90-100', 'label': '优秀', 'min': 90, 'max': 100},
        ]
        distribution = []
        for sr in score_ranges:
            cnt = records.filter(
                score__gte=sr['min'], score__lte=sr['max']
            ).count()
            distribution.append({
                'range': sr['range'],
                'label': sr['label'],
                'count': cnt,
                'ratio': round(cnt / agg['total_count'] * 100, 1) if agg['total_count'] else 0,
            })

        # 每份试卷统计
        paper_stats = []
        for paper in papers:
            prs = records.filter(paper=paper)
            paper_stats.append({
                'paper_id': paper.id,
                'paper_name': paper.name,
                'total_score': float(paper.total_score),
                'submitted_count': prs.count(),
                'avg_score': float(prs.aggregate(Avg('score'))['score__avg'] or 0),
                'highest_score': float(prs.aggregate(Max('score'))['score__max'] or 0),
                'lowest_score': float(prs.aggregate(Min('score'))['score__min'] or 0),
                'pass_rate': round(prs.filter(score__gte=60).count() / prs.count() * 100, 1) if prs.exists() else 0,
            })

        return Response({
            'class_id': target_class.id,
            'class_name': target_class.name,
            'total_students': target_class.class_students.count(),
            'total_exams': agg['total_count'],
            'average_score': float(agg['avg_score'] or 0),
            'highest_score': float(agg['max_score'] or 0),
            'lowest_score': float(agg['min_score'] or 0),
            'score_distribution': distribution,
            'paper_stats': paper_stats,
        })

    @action(detail=True, methods=['get'])
    def question_accuracy(self, request, pk=None):
        """各题正确率统计"""
        paper = self.get_object()
        paper_questions = ExamPaperQuestion.objects.filter(paper=paper).order_by('order')

        question_stats = []
        for pq in paper_questions:
            answers = AnswerDetail.objects.filter(
                record__paper=paper,
                question=pq.question,
                record__status__in=['submitted']
            )
            total = answers.count()
            correct = answers.filter(is_correct=True).count()
            question_stats.append({
                'question_id': pq.question.id,
                'content': pq.question.content[:80],
                'question_type': pq.question.get_question_type_display(),
                'difficulty': pq.question.get_difficulty_display(),
                'score': float(pq.score),
                'total_attempts': total,
                'correct_count': correct,
                'accuracy_rate': round(correct / total * 100, 1) if total > 0 else 0,
            })

        return Response({
            'paper_id': paper.id,
            'paper_name': paper.name,
            'total_questions': len(question_stats),
            'questions': question_stats,
        })


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
