from django.core.management.base import BaseCommand
from django.utils import timezone
from users.models import User, Class, StudentClass
from exam_core.models import ExamPaper, ExamPaperQuestion
from question_bank.models import Question


class Command(BaseCommand):
    help = '创建测试数据'

    def handle(self, *args, **options):
        self.stdout.write('开始创建测试数据...\n')

        # 1. 创建教师用户
        teacher, created = User.objects.get_or_create(
            username='teacher1',
            defaults={
                'role': 'teacher',
                'real_name': '测试教师',
                'email': 'teacher1@test.com'
            }
        )
        if created:
            teacher.set_password('test123')
            teacher.save()
            self.stdout.write(self.style.SUCCESS(f'✓ 创建教师用户: teacher1'))
        else:
            self.stdout.write(f'· 教师用户已存在: teacher1')

        # 2. 创建学生用户
        students_data = [
            {'username': 'student1', 'real_name': '学生一'},
            {'username': 'student2', 'real_name': '学生二'},
        ]
        students = []
        for data in students_data:
            student, created = User.objects.get_or_create(
                username=data['username'],
                defaults={
                    'role': 'student',
                    'real_name': data['real_name'],
                    'email': f"{data['username']}@test.com"
                }
            )
            if created:
                student.set_password('test123')
                student.save()
                self.stdout.write(self.style.SUCCESS(f'✓ 创建学生用户: {data["username"]}'))
            else:
                self.stdout.write(f'· 学生用户已存在: {data["username"]}')
            students.append(student)

        # 3. 创建班级
        class_obj, created = Class.objects.get_or_create(
            class_code='TEST001',
            defaults={
                'name': '测试班级',
                'teacher': teacher
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS('✓ 创建班级: 测试班级'))
        else:
            self.stdout.write('· 班级已存在: 测试班级')

        # 4. 将学生加入班级
        for student in students:
            _, created = StudentClass.objects.get_or_create(
                student=student,
                class_obj=class_obj
            )
            if created:
                self.stdout.write(f'✓ 学生 {student.username} 加入班级')

        # 5. 创建试卷
        exam_paper, created = ExamPaper.objects.get_or_create(
            name='Python 基础测试',
            defaults={
                'target_class': class_obj,
                'total_score': 100,
                'duration': 60,
                'creator': teacher,
                'published_at': timezone.now()
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS('✓ 创建试卷: Python 基础测试'))
        else:
            self.stdout.write('· 试卷已存在: Python 基础测试')

        # 6. 创建题目
        questions_data = [
            {
                'content': 'Python 中变量命名下列正确的是？',
                'options': '{"A": "1name", "B": "name_1", "C": "name-1", "D": "class"}',
                'answer': 'B',
                'analysis': 'Python 变量名可以包含字母、数字和下划线，但不能以数字开头，不能使用连字符，不能使用保留字。',
                'knowledge_point': 'Python基础'
            },
            {
                'content': '下列哪个是 Python 的数据类型？',
                'options': '{"A": "int", "B": "string", "C": "char", "D": "boolean"}',
                'answer': 'A',
                'analysis': 'Python 中没有 string、char、boolean 类型，对应的分别是 str、str、bool。',
                'knowledge_point': '数据类型'
            },
            {
                'content': 'print(type([])) 的输出是？',
                'options': '{"A": "<class \'list\'>", "B": "<class \'array\'>", "C": "<class \'tuple\'>", "D": "<class \'dict\'>"}',
                'answer': 'A',
                'analysis': '[] 是空列表，type() 函数返回其类型为 list。',
                'knowledge_point': '数据类型'
            },
            {
                'content': 'Python 中切片操作 list[1:3] 返回几个元素？',
                'options': '{"A": "1个", "B": "2个", "C": "3个", "D": "4个"}',
                'answer': 'B',
                'analysis': '切片 list[1:3] 返回索引 1 和 2 的元素，共 2 个。',
                'knowledge_point': '序列操作'
            },
            {
                'content': '下列哪个方法可以向列表末尾添加元素？',
                'options': '{"A": "add()", "B": "append()", "C": "insert()", "D": "push()"}',
                'answer': 'B',
                'analysis': 'append() 方法向列表末尾添加元素，insert() 在指定位置插入。',
                'knowledge_point': '列表方法'
            },
        ]

        for i, q_data in enumerate(questions_data, 1):
            question, created = Question.objects.get_or_create(
                content=q_data['content'],
                defaults={
                    'question_type': 'choice',
                    'options': q_data['options'],
                    'answer': q_data['answer'],
                    'analysis': q_data['analysis'],
                    'knowledge_point': q_data['knowledge_point'],
                    'difficulty': 2,
                    'creator': teacher
                }
            )
            if created:
                self.stdout.write(f'✓ 创建题目 {i}: {question.content[:20]}...')

            # 关联题目到试卷
            _, created = ExamPaperQuestion.objects.get_or_create(
                paper=exam_paper,
                question=question,
                defaults={'score': 20, 'order': i}
            )

        self.stdout.write(self.style.SUCCESS('\n✓ 测试数据创建完成！'))
        self.stdout.write('\n测试账号:')
        self.stdout.write('  教师: teacher1 / test123')
        self.stdout.write('  学生: student1 / test123')
        self.stdout.write('  学生: student2 / test123')
