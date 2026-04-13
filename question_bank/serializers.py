from rest_framework import serializers
import json
from .models import Question


class QuestionSerializer(serializers.ModelSerializer):
    """题目序列化器"""
    creator_name = serializers.CharField(source='creator.real_name', read_only=True)
    question_type_display = serializers.CharField(source='get_question_type_display', read_only=True)
    difficulty_display = serializers.CharField(source='get_difficulty_display', read_only=True)
    
    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # 将 options 从字符串转换为字典
        if isinstance(ret.get('options'), str):
            try:
                ret['options'] = json.loads(ret['options']) if ret['options'] else {}
            except json.JSONDecodeError:
                ret['options'] = {}
        return ret
    
    def to_internal_value(self, data):
        # 处理 options 字段
        if 'options' in data and isinstance(data['options'], dict):
            data = data.copy()
            data['options'] = json.dumps(data['options'])
        return super().to_internal_value(data)
    
    class Meta:
        model = Question
        fields = [
            'id', 'question_type', 'question_type_display', 'content', 'options',
            'answer', 'analysis', 'knowledge_point', 'difficulty', 'difficulty_display',
            'creator', 'creator_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'creator', 'created_at', 'updated_at']


class QuestionListSerializer(serializers.ModelSerializer):
    """题目列表序列化器"""
    creator_name = serializers.CharField(source='creator.real_name', read_only=True)
    question_type_display = serializers.CharField(source='get_question_type_display', read_only=True)
    difficulty_display = serializers.CharField(source='get_difficulty_display', read_only=True)
    
    class Meta:
        model = Question
        fields = [
            'id', 'question_type', 'question_type_display', 'content',
            'knowledge_point', 'difficulty', 'difficulty_display',
            'creator_name', 'created_at'
        ]


class QuestionCreateSerializer(serializers.ModelSerializer):
    """创建题目序列化器"""
    options = serializers.CharField(required=False, allow_blank=True)
    
    def validate(self, attrs):
        question_type = attrs.get('question_type')
        options = attrs.get('options', '{}')
        
        # 选择题和多选题必须有选项
        if question_type in ['choice', 'multiple_choice'] and not options:
            raise serializers.ValidationError({
                'options': '选择题必须提供选项'
            })
        
        # 判断题答案只能是正确或错误
        if question_type == 'true_false' and attrs.get('answer') not in ['正确', '错误', 'true', 'false', 'True', 'False']:
            raise serializers.ValidationError({
                'answer': '判断题答案只能是"正确"或"错误"'
            })
        
        return attrs
    
    def create(self, validated_data):
        validated_data['creator'] = self.context['request'].user
        return super().create(validated_data)
    
    class Meta:
        model = Question
        fields = [
            'question_type', 'content', 'options', 'answer',
            'analysis', 'knowledge_point', 'difficulty'
        ]


class QuestionFilterSerializer(serializers.Serializer):
    """题目筛选序列化器"""
    question_type = serializers.ChoiceField(choices=Question.QUESTION_TYPE_CHOICES, required=False)
    knowledge_point = serializers.CharField(required=False)
    difficulty = serializers.IntegerField(min_value=1, max_value=5, required=False)
    keyword = serializers.CharField(required=False, max_length=200)
