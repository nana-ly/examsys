from rest_framework import serializers  # type: ignore
from exam_core.models import ExamPaper, ExamPaperQuestion
from question_bank.models import Question
from .models import WrongQuestion


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
        return {
            'id': instance.question.id,
            'content': instance.question.content,
            'question_type': instance.question.question_type,
            'options': instance.question.options,
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
    """错题本序列化器（含答案和解析）"""
    wrong_id = serializers.IntegerField(source='id', read_only=True)
    question_id = serializers.IntegerField(source='question.id', read_only=True)
    content = serializers.CharField(source='question.content', read_only=True)
    question_type = serializers.CharField(source='question.question_type', read_only=True)
    options = serializers.CharField(source='question.options', read_only=True)
    answer = serializers.CharField(source='question.answer', read_only=True)
    analysis = serializers.CharField(source='question.analysis', read_only=True)
    knowledge_point = serializers.CharField(source='question.knowledge_point', read_only=True)

    class Meta:
        model = WrongQuestion
        fields = [
            'wrong_id', 'question_id', 'content', 'question_type',
            'options', 'answer', 'analysis', 'knowledge_point',
            'is_mastered', 'added_at'
        ]
