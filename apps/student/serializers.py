from rest_framework import serializers  # type: ignore
from exam_core.models import ExamPaper, ExamPaperQuestion, WrongQuestion
from question_bank.models import Question
import json


class ExamListSerializer(serializers.ModelSerializer):
    """试卷列表序列化器（学生端，不含答案）"""
    creator_name = serializers.CharField(source='creator.real_name', read_only=True)
    question_count = serializers.SerializerMethodField()

    class Meta:
        model = ExamPaper
        fields = [
            'id', 'name', 'duration', 'total_score',
            'published_at', 'creator_name', 'question_count'
        ]

    def get_question_count(self, obj):
        """返回题目数量（不暴露答案）"""
        return obj.paper_questions.count()


class QuestionSerializer(serializers.ModelSerializer):
    """题目序列化器（不含答案）"""

    class Meta:
        model = ExamPaperQuestion
        fields = ['id', 'content', 'question_type', 'options', 'order']

    def to_representation(self, instance):
        """重写方法，直接返回题目的字段"""
        try:
            options = json.loads(instance.question.options) if instance.question.options else {}
        except json.JSONDecodeError:
            options = {}
        return {
            'id': instance.question.id,
            'content': instance.question.content,
            'question_type': instance.question.question_type,
            'options': options,
            'order': instance.order
        }


class ExamDetailSerializer(serializers.ModelSerializer):
    """试卷详情序列化器（学生端，不含答案）"""
    creator_name = serializers.CharField(source='creator.real_name', read_only=True)
    questions = serializers.SerializerMethodField()

    class Meta:
        model = ExamPaper
        fields = [
            'id', 'name', 'duration', 'total_score',
            'published_at', 'creator_name', 'questions'
        ]

    def get_questions(self, obj):
        """返回题目列表（不含答案）"""
        paper_questions = obj.paper_questions.select_related('question').order_by('order')
        return QuestionSerializer(paper_questions, many=True).data


class WrongQuestionSerializer(serializers.ModelSerializer):
    """错题本序列化器（兼容主题库和AI库）"""
    wrong_id = serializers.IntegerField(source='id', read_only=True)
    question_id = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()
    question_type = serializers.SerializerMethodField()
    options = serializers.SerializerMethodField()
    answer = serializers.SerializerMethodField()
    analysis = serializers.SerializerMethodField()
    knowledge_point = serializers.SerializerMethodField()
    difficulty = serializers.SerializerMethodField()

    def get_question_id(self, obj):
        if obj.source_type == 'ai':
            return obj.source_id
        return obj.question_id if obj.question else None

    def get_content(self, obj):
        if obj.source_type == 'ai' or not obj.question:
            return ''
        return obj.question.content

    def get_question_type(self, obj):
        if obj.source_type == 'ai' or not obj.question:
            return ''
        return obj.question.question_type

    def get_options(self, obj):
        if obj.source_type == 'ai' or not obj.question:
            return {}
        try:
            return json.loads(obj.question.options) if obj.question.options else {}
        except json.JSONDecodeError:
            return {}

    def get_answer(self, obj):
        if obj.source_type == 'ai' or not obj.question:
            return ''
        return obj.question.answer

    def get_analysis(self, obj):
        if obj.source_type == 'ai' or not obj.question:
            return ''
        return obj.question.analysis or ''

    def get_knowledge_point(self, obj):
        if obj.source_type == 'ai' or not obj.question:
            return ''
        return obj.question.knowledge_point or ''

    def get_difficulty(self, obj):
        if obj.source_type == 'ai' or not obj.question:
            return 3
        return obj.question.difficulty

    class Meta:
        model = WrongQuestion
        fields = [
            'wrong_id', 'question_id', 'content', 'question_type',
            'options', 'answer', 'analysis', 'knowledge_point', 'difficulty',
            'is_mastered', 'created_at', 'source_type', 'source_id'
        ]
