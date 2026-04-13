from rest_framework import serializers
from django.utils import timezone
from .models import ExamPaper, ExamPaperQuestion, ExamRecord, AnswerDetail, WrongQuestion
from question_bank.models import Question
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

    def to_internal_value(self, data):
        data = dict(data)
        if 'title' in data and 'name' not in data:
            data['name'] = data.pop('title')
        if 'classIds' in data and 'target_class' not in data:
            class_ids = data.pop('classIds')
            if isinstance(class_ids, list) and class_ids:
                data['target_class'] = class_ids[0]
        if 'totalScore' in data and 'total_score' not in data:
            data['total_score'] = data.pop('totalScore')
        if 'startTime' in data and 'published_at' not in data:
            data['published_at'] = data.pop('startTime')
        if 'questions' in data and 'question_ids' not in data:
            questions = data.pop('questions')
            data['question_ids'] = [q['question_id'] if isinstance(q, dict) else q for q in questions]
            self._question_scores = {q['question_id']: q.get('score', 10)
                                     for q in questions if isinstance(q, dict)}
        else:
            self._question_scores = {}
        data.pop('description', None)
        data.pop('endTime', None)
        data.pop('passScore', None)
        return super().to_internal_value(data)

    def validate_target_class(self, value):
        user = self.context['request'].user
        if value.teacher != user:
            raise serializers.ValidationError('只能为自己的班级创建试卷')
        return value

    def create(self, validated_data):
        question_ids = validated_data.pop('question_ids', [])
        validated_data['creator'] = self.context['request'].user
        paper = ExamPaper.objects.create(**validated_data)

        for order, qid in enumerate(question_ids):
            try:
                question = Question.objects.get(id=qid)
                score = self._question_scores.get(qid, 10)
                ExamPaperQuestion.objects.create(
                    paper=paper,
                    question=question,
                    score=score,
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


class AutoGenerateSerializer(serializers.Serializer):
    name = serializers.CharField(label='试卷名称')
    target_class = serializers.IntegerField(label='目标班级')
    total_score = serializers.IntegerField(label='总分', default=100)
    duration = serializers.IntegerField(label='时长(分钟)', default=120)
    published_at = serializers.DateTimeField(label='发布时间', required=False, allow_null=True)

    # 表单字段 — 用于 HTML form 逐个输入
    choice_count = serializers.IntegerField(label='选择题数量', required=False, min_value=0)
    true_false_count = serializers.IntegerField(label='判断题数量', required=False, min_value=0)
    multiple_choice_count = serializers.IntegerField(label='多选题数量', required=False, min_value=0)
    easy_count = serializers.IntegerField(label='简单题数量', required=False, min_value=0)
    medium_count = serializers.IntegerField(label='中等题数量', required=False, min_value=0)
    hard_count = serializers.IntegerField(label='难题数量', required=False, min_value=0)

    def validate(self, attrs):
        type_dist = {}
        if attrs.get('choice_count'):
            type_dist['choice'] = attrs['choice_count']
        if attrs.get('true_false_count'):
            type_dist['true_false'] = attrs['true_false_count']
        if attrs.get('multiple_choice_count'):
            type_dist['multiple_choice'] = attrs['multiple_choice_count']

        if not type_dist:
            raise serializers.ValidationError({'choice_count': '请至少指定一种题型数量'})

        diff_dist = {}
        if attrs.get('easy_count'):
            diff_dist['1'] = attrs['easy_count']
        if attrs.get('medium_count'):
            diff_dist['2'] = attrs['medium_count']
        if attrs.get('hard_count'):
            diff_dist['3'] = attrs['hard_count']

        attrs['type_distribution'] = type_dist
        attrs['difficulty_distribution'] = diff_dist
        return attrs