from rest_framework import serializers
from django.utils import timezone
from .models import ExamPaper, ExamPaperQuestion, ExamRecord, AnswerDetail, WrongQuestion
from question_bank.serializers import QuestionSerializer


class ExamPaperQuestionSerializer(serializers.ModelSerializer):
    """试卷题目关联序列化器"""
    question_detail = QuestionSerializer(source='question', read_only=True)
    
    class Meta:
        model = ExamPaperQuestion
        fields = ['id', 'question', 'question_detail', 'score', 'order']


class ExamPaperSerializer(serializers.ModelSerializer):
    """试卷序列化器"""
    target_class_name = serializers.CharField(source='target_class.name', read_only=True)
    creator_name = serializers.CharField(source='creator.real_name', read_only=True)
    question_count = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = ExamPaper
        fields = [
            'id', 'name', 'target_class', 'target_class_name', 'total_score',
            'duration', 'published_at', 'creator', 'creator_name',
            'question_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'creator', 'created_at', 'updated_at']


class ExamPaperListSerializer(serializers.ModelSerializer):
    """试卷列表序列化器"""
    target_class_name = serializers.CharField(source='target_class.name', read_only=True)
    creator_name = serializers.CharField(source='creator.real_name', read_only=True)
    
    class Meta:
        model = ExamPaper
        fields = [
            'id', 'name', 'target_class_name', 'total_score',
            'duration', 'published_at', 'creator_name',
            'question_count', 'created_at'
        ]


class ExamPaperCreateSerializer(serializers.ModelSerializer):
    """创建试卷序列化器"""
    question_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        help_text='题目ID列表'
    )
    
    class Meta:
        model = ExamPaper
        fields = ['name', 'target_class', 'total_score', 'duration', 'published_at', 'question_ids']
    
    def validate_target_class(self, value):
        user = self.context['request'].user
        if value.teacher != user:
            raise serializers.ValidationError('只能为自己的班级创建试卷')
        return value
    
    def create(self, validated_data):
        question_ids = validated_data.pop('question_ids', [])
        validated_data['creator'] = self.context['request'].user
        paper = ExamPaper.objects.create(**validated_data)
        
        # 添加题目到试卷
        for order, qid in enumerate(question_ids):
            try:
                question = Question.objects.get(id=qid)
                ExamPaperQuestion.objects.create(
                    paper=paper,
                    question=question,
                    order=order
                )
            except Question.DoesNotExist:
                pass
        
        return paper


class AnswerDetailSerializer(serializers.ModelSerializer):
    """答题详情序列化器"""
    question_detail = QuestionSerializer(source='question', read_only=True)
    
    class Meta:
        model = AnswerDetail
        fields = ['id', 'question', 'question_detail', 'student_answer', 'is_correct', 'score']


class ExamRecordSerializer(serializers.ModelSerializer):
    """考试记录序列化器"""
    paper_name = serializers.CharField(source='paper.name', read_only=True)
    student_name = serializers.CharField(source='student.real_name', read_only=True)
    
    class Meta:
        model = ExamRecord
        fields = [
            'id', 'student', 'student_name', 'paper', 'paper_name',
            'score', 'status', 'started_at', 'submitted_at'
        ]
        read_only_fields = ['id', 'started_at']


class ExamRecordDetailSerializer(serializers.ModelSerializer):
    """考试记录详情序列化器"""
    paper = ExamPaperSerializer(read_only=True)
    answers = AnswerDetailSerializer(source='answer_details', many=True, read_only=True)
    
    class Meta:
        model = ExamRecord
        fields = [
            'id', 'paper', 'score', 'status', 'started_at',
            'submitted_at', 'answers'
        ]


class SubmitAnswerSerializer(serializers.Serializer):
    """提交答案序列化器"""
    answers = serializers.ListField(
        child=serializers.DictField(),
        help_text='答案列表，格式：[{"question_id": 1, "answer": "A"}]'
    )
    
    def validate_answers(self, value):
        if not value:
            raise serializers.ValidationError('答案不能为空')
        return value


class ExamStartSerializer(serializers.Serializer):
    """开始考试序列化器"""
    paper_id = serializers.IntegerField()


class WrongQuestionSerializer(serializers.ModelSerializer):
    """错题本序列化器"""
    question_detail = QuestionSerializer(source='question', read_only=True)
    student_name = serializers.CharField(source='student.real_name', read_only=True)
    
    class Meta:
        model = WrongQuestion
        fields = [
            'id', 'student', 'student_name', 'question', 'question_detail',
            'wrong_answer', 'is_mastered', 'created_at', 'mastered_at'
        ]
        read_only_fields = ['id', 'created_at']


class WrongQuestionCreateSerializer(serializers.ModelSerializer):
    """创建错题本记录"""
    class Meta:
        model = WrongQuestion
        fields = ['question', 'wrong_answer']
