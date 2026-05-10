from rest_framework.views import APIView
from rest_framework.response import Response
from django.utils import timezone
from django.http import Http404
from django.db import transaction
import json
import requests

from exam_core.models import ExamPaper, ExamPaperQuestion
from question_bank.models import Question
from .models import ExamRecord, AnswerDetail, WrongQuestion
from .serializers import ExamListSerializer, ExamDetailSerializer, WrongQuestionSerializer


class ExamListView(APIView):
    """学生可参加的试卷列表"""
    permission_classes = []

    def get(self, request):
        # 检查用户是否登录
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        # 只返回已发布的试卷（published_at 不为空且 <= 当前时间）
        # 只返回当前学生所在班级的试卷
        queryset = ExamPaper.objects.filter(
            published_at__isnull=False,
            published_at__lte=timezone.now(),
            target_class__class_students__student=request.user
        ).distinct().order_by('-published_at')

        serializer = ExamListSerializer(queryset, many=True)
        return Response(serializer.data)


class ExamDetailView(APIView):
    """试卷详情"""
    permission_classes = []

    def get(self, request, exam_id):
        # 检查用户是否登录
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        try:
            exam = ExamPaper.objects.get(
                id=exam_id,
                published_at__isnull=False,
                published_at__lte=timezone.now()
            )
        except ExamPaper.DoesNotExist:
            raise Http404('试卷不存在或未发布')

        serializer = ExamDetailSerializer(exam)
        return Response(serializer.data)


class SubmitAnswerView(APIView):
    """提交答案并自动批改"""
    permission_classes = []

    def post(self, request, exam_id):
        # 检查用户是否登录
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        # 获取试卷
        try:
            exam = ExamPaper.objects.get(
                id=exam_id,
                published_at__isnull=False,
                published_at__lte=timezone.now()
            )
        except ExamPaper.DoesNotExist:
            return Response({'error': '试卷不存在或未发布'}, status=404)

        # 获取提交的答案
        answers = request.data.get('answers', [])
        if not answers:
            return Response({'error': '请提交答案'}, status=400)

        # 构建答案字典 {question_id: answer}
        answer_dict = {item['question_id']: item['answer'] for item in answers}

        # 获取试卷的所有题目
        paper_questions = exam.paper_questions.select_related('question').all()
        question_map = {pq.question_id: pq for pq in paper_questions}

        # 自动批改
        correct_count = 0
        total_count = len(paper_questions)
        details = []
        wrong_question_ids = []

        for paper_q in paper_questions:
            question = paper_q.question
            student_answer = answer_dict.get(question.id, '')
            correct_answer = question.answer

            # 比较答案（去除空格后比较）
            is_correct = str(student_answer).strip() == str(correct_answer).strip()

            if is_correct:
                correct_count += 1
            else:
                wrong_question_ids.append(question.id)

            details.append({
                'question_id': question.id,
                'correct': is_correct,
                'correct_answer': correct_answer,
                'explanation': question.analysis or ''
            })

        # 计算得分（每题分数相同）
        score_per_question = float(exam.total_score) / total_count if total_count > 0 else 0
        total_score = round(correct_count * score_per_question, 1)

        # 保存考试记录和答题详情
        with transaction.atomic():
            # 创建 ExamRecord
            exam_record = ExamRecord.objects.create(
                student=request.user,
                exam_paper=exam,
                score=total_score,
                status='submitted',
                end_time=timezone.now()
            )

            # 创建 AnswerDetail
            for paper_q in paper_questions:
                question = paper_q.question
                student_answer = answer_dict.get(question.id, '')
                is_correct = str(student_answer).strip() == str(question.answer).strip()

                AnswerDetail.objects.create(
                    exam_record=exam_record,
                    question=question,
                    student_answer=str(student_answer),
                    is_correct=is_correct
                )

            # 添加错题到错题本
            for q_id in wrong_question_ids:
                WrongQuestion.objects.get_or_create(
                    student=request.user,
                    question_id=q_id
                )

        return Response({
            'total': total_count,
            'correct': correct_count,
            'score': total_score,
            'details': details
        })


class WrongQuestionListView(APIView):
    """错题本列表"""
    permission_classes = []

    def get(self, request):
        # 检查用户是否登录
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        # 获取当前学生的错题
        queryset = WrongQuestion.objects.filter(student=request.user).select_related('question')

        # 按 is_mastered 筛选
        mastered = request.query_params.get('mastered')
        if mastered is not None:
            queryset = queryset.filter(is_mastered=mastered.lower() == 'true')

        # 按知识点筛选
        knowledge_point = request.query_params.get('knowledge_point')
        if knowledge_point:
            queryset = queryset.filter(question__knowledge_point=knowledge_point)

        queryset = queryset.order_by('-added_at')

        serializer = WrongQuestionSerializer(queryset, many=True)
        return Response(serializer.data)


class WrongQuestionAddView(APIView):
    """手动添加错题"""
    permission_classes = []

    def post(self, request):
        # 检查用户是否登录
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        question_id = request.data.get('question_id')
        if not question_id:
            return Response({'error': '请提供 question_id'}, status=400)

        # 检查题目是否存在
        try:
            question = Question.objects.get(id=question_id)
        except Question.DoesNotExist:
            return Response({'error': '题目不存在'}, status=404)

        # 检查是否已在错题本中
        exists = WrongQuestion.objects.filter(
            student=request.user,
            question=question
        ).exists()

        if exists:
            return Response({'message': '已在错题本中'})

        # 添加到错题本
        WrongQuestion.objects.create(student=request.user, question=question)
        return Response({'message': '已添加到错题本'})


class WrongQuestionMasterView(APIView):
    """标记/取消标记已掌握"""
    permission_classes = []

    def patch(self, request, wrong_id):
        # 检查用户是否登录
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        # 获取错题记录
        try:
            wrong_question = WrongQuestion.objects.get(id=wrong_id, student=request.user)
        except WrongQuestion.DoesNotExist:
            return Response({'error': '错题记录不存在'}, status=404)

        is_mastered = request.data.get('is_mastered')
        if is_mastered is None:
            return Response({'error': '请提供 is_mastered'}, status=400)

        wrong_question.is_mastered = is_mastered
        wrong_question.save()

        return Response({
            'message': '已标记为已掌握' if is_mastered else '已取消标记',
            'is_mastered': wrong_question.is_mastered
        })


class AIQuestionGenerateView(APIView):
    """AI 生成题目"""
    permission_classes = []

    def post(self, request):
        # 检查用户是否登录
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        # 获取参数
        knowledge_point = request.data.get('knowledge_point', '')
        question_type = request.data.get('question_type', 'choice')
        difficulty = request.data.get('difficulty', 'medium')

        if not knowledge_point:
            return Response({'error': '请提供知识点'}, status=400)

        # 题型映射
        type_map = {
            'choice': '单选题',
            'judge': '判断题',
            'multiple': '多选题'
        }
        question_type_cn = type_map.get(question_type, '单选题')

        # 难度映射
        diff_map = {
            'easy': '简单',
            'medium': '中等',
            'hard': '困难'
        }
        difficulty_cn = diff_map.get(difficulty, '中等')

        # 构建 Prompt
        prompt = f"""请生成一道{question_type_cn}，知识点为「{knowledge_point}」，难度为{difficulty_cn}。

请严格按以下 JSON 格式返回，不要包含任何其他内容：
{{
    "content": "题目内容",
    "options": {{"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"}},
    "answer": "B",
    "analysis": "解析内容"
}}"""

        # 调用智谱清言 API
        api_url = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
        api_key = '2b41adce08b540f9b9203b161ac550f5.0x2EeGc6rETQMq51'

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        payload = {
            'model': 'glm-4-flash',
            'messages': [
                {'role': 'user', 'content': prompt}
            ]
        }

        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            content = result['choices'][0]['message']['content']

            # 提取 JSON
            content = content.strip()
            if content.startswith('```json'):
                content = content[7:]
            if content.startswith('```'):
                content = content[3:]
            if content.endswith('```'):
                content = content[:-3]

            question_data = json.loads(content.strip())

        except json.JSONDecodeError:
            return Response({'error': 'AI 返回格式错误'}, status=500)
        except Exception as e:
            return Response({'error': f'AI 调用失败: {str(e)}'}, status=500)

        # 保存到数据库
        question = Question.objects.create(
            question_type=question_type,
            content=question_data['content'],
            options=json.dumps(question_data['options']),
            answer=question_data['answer'],
            analysis=question_data.get('analysis', ''),
            knowledge_point=knowledge_point,
            difficulty={'easy': 1, 'medium': 3, 'hard': 5}.get(difficulty, 3),
            creator=request.user
        )

        return Response({
            'message': '题目生成成功',
            'question': {
                'id': question.id,
                'content': question.content,
                'options': json.loads(question.options),
                'answer': question.answer,
                'analysis': question.analysis
            }
        })


class AIQuestionAskView(APIView):
    """学生对错题提问"""
    permission_classes = []

    def post(self, request):
        # 检查用户是否登录
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        # 获取参数
        question_id = request.data.get('question_id')
        student_question = request.data.get('student_question', '')

        if not question_id:
            return Response({'error': '请提供 question_id'}, status=400)

        if not student_question:
            return Response({'error': '请提供 student_question'}, status=400)

        # 获取题目
        try:
            question = Question.objects.get(id=question_id)
        except Question.DoesNotExist:
            return Response({'error': '题目不存在'}, status=404)

        # 构建 Prompt
        prompt = f"""你是学生的老师，正在帮助学生解答疑问。

题目内容：{question.content}
正确答案：{question.answer}
题目解析：{question.analysis or '暂无解析'}

学生的问题：{student_question}

请用老师的口吻，耐心、详细地解答学生的问题。回答要亲切、有帮助性。"""

        # 调用智谱清言 API
        api_url = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
        api_key = '2b41adce08b540f9b9203b161ac550f5.0x2EeGc6rETQMq51'

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        payload = {
            'model': 'glm-4-flash',
            'messages': [
                {'role': 'user', 'content': prompt}
            ]
        }

        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            answer = result['choices'][0]['message']['content']

        except Exception as e:
            return Response({'error': f'AI 调用失败: {str(e)}'}, status=500)

        return Response({'answer': answer})
