from datetime import datetime

from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import User, Class, StudentClass


class UserRegisterSerializer(serializers.ModelSerializer):
    """用户注册序列化器"""
    password = serializers.CharField(write_only=True, min_length=6, label='密码')
    password_confirm = serializers.CharField(write_only=True, label='确认密码')
    
    class Meta:
        model = User
        fields = ['username', 'password', 'password_confirm', 'role', 'phone', 'real_name', 'email']
        extra_kwargs = {
            'email': {'required': False},
            'phone': {'required': False},
            'real_name': {'required': False},
        }
    
    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password_confirm': '两次密码不一致'})
        return attrs
    
    def create(self, validated_data):
        validated_data.pop('password_confirm')
        user = User.objects.create_user(**validated_data)
        return user


class UserLoginSerializer(serializers.Serializer):
    """用户登录序列化器"""
    username = serializers.CharField(label='用户名')
    password = serializers.CharField(label='密码', write_only=True)
    
    def validate(self, attrs):
        user = authenticate(username=attrs['username'], password=attrs['password'])
        if not user:
            raise serializers.ValidationError('用户名或密码错误')
        if not user.is_active:
            raise serializers.ValidationError('用户已被禁用')
        attrs['user'] = user
        return attrs


class UserSerializer(serializers.ModelSerializer):
    """用户详细信息序列化器"""
    class Meta:
        model = User
        fields = ['id', 'username', 'role', 'phone', 'real_name', 'email', 'date_joined']
        read_only_fields = ['id', 'username', 'date_joined']


class UserListSerializer(serializers.ModelSerializer):
    """用户列表序列化器"""
    class Meta:
        model = User
        fields = ['id', 'username', 'role', 'real_name', 'phone', 'email']


class ClassSerializer(serializers.ModelSerializer):
    """班级序列化器"""
    teacher_name = serializers.CharField(source='teacher.real_name', read_only=True)
    
    class Meta:
        model = Class
        fields = ['id', 'name', 'teacher', 'teacher_name', 'class_code', 'created_at']
        read_only_fields = ['id', 'teacher', 'created_at']


class ClassCreateSerializer(serializers.ModelSerializer):
    """创建班级序列化器"""
    class Meta:
        model = Class
        fields = ['name', 'class_code']
        extra_kwargs = {'class_code': {'required': False}}

    def validate_name(self, value):
        user = self.context['request'].user
        qs = Class.objects.filter(name=value, teacher=user)
        if self.instance:
            qs = qs.exclude(id=self.instance.id)
        if qs.exists():
            raise serializers.ValidationError('您已经创建过同名班级，请使用不同的班级名称')
        return value

    def create(self, validated_data):
        validated_data['teacher'] = self.context['request'].user
        if not validated_data.get('class_code'):
            validated_data['class_code'] = f"C{validated_data['teacher'].id}{int(datetime.now().timestamp())}"
        return super().create(validated_data)


class StudentClassSerializer(serializers.ModelSerializer):
    """学生班级关联序列化器"""
    username = serializers.CharField(source='student.username', read_only=True)
    real_name = serializers.CharField(source='student.real_name', read_only=True)
    email = serializers.CharField(source='student.email', read_only=True)
    class_name = serializers.CharField(source='class_obj.name', read_only=True)
    join_time = serializers.DateTimeField(source='joined_at', read_only=True)

    class Meta:
        model = StudentClass
        fields = ['id', 'student', 'username', 'real_name', 'email', 'class_obj', 'class_name', 'join_time']
        read_only_fields = ['id', 'join_time']


class AddStudentSerializer(serializers.Serializer):
    """教师添加学生序列化器"""
    student_ids = serializers.ListField(child=serializers.IntegerField(), label='学生ID列表')

    def validate_student_ids(self, value):
        students = []
        for sid in value:
            try:
                student = User.objects.get(id=sid, role='student')
                students.append(student)
            except User.DoesNotExist:
                raise serializers.ValidationError(f'学生ID {sid} 不存在或非学生角色')
        self._students = students
        return value

    def validate(self, attrs):
        class_obj = self.context['class_obj']
        for student in self._students:
            if StudentClass.objects.filter(student=student, class_obj=class_obj).exists():
                raise serializers.ValidationError(f'学生 {student.real_name} 已在班级中')
        return attrs

    def save(self):
        class_obj = self.context['class_obj']
        return [StudentClass.objects.create(student=s, class_obj=class_obj) for s in self._students]


class JoinClassSerializer(serializers.Serializer):
    """加入班级序列化器"""
    class_code = serializers.CharField(max_length=20, label='班级码')
    
    def validate_class_code(self, value):
        try:
            class_obj = Class.objects.get(class_code=value)
        except Class.DoesNotExist:
            raise serializers.ValidationError('班级码不存在')
        self._class_obj = class_obj
        return value
    
    def validate(self, attrs):
        user = self.context['request'].user
        if user.role != 'student':
            raise serializers.ValidationError('只有学生才能加入班级')
        if StudentClass.objects.filter(student=user, class_obj=self._class_obj).exists():
            raise serializers.ValidationError('您已经加入过该班级')
        attrs['class_obj'] = self._class_obj
        return attrs
    
    def save(self):
        return StudentClass.objects.create(
            student=self.context['request'].user,
            class_obj=self.validated_data['class_obj']
        )
