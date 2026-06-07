from rest_framework.views import APIView
from rest_framework.response import Response
from django.utils import timezone
from django.http import Http404
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.conf import settings
import json
import requests
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

from exam_core.models import ExamPaper, ExamPaperQuestion, ExamRecord, AnswerDetail, WrongQuestion, PracticeRecord, StudySession
from question_bank.models import Question, QuestionAI
from .serializers import ExamListSerializer, ExamDetailSerializer, WrongQuestionSerializer


class ExamListView(APIView):
    """学生可参加的试卷列表"""
    permission_classes = []

    def get(self, request):
        # 检查用户是否登录
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        # 查出学生所在的所有班级 ID
        class_ids = request.user.student_classes.values_list('class_obj_id', flat=True)

        # 查询这些班级的已发布试卷，排除已提交的
        submitted_paper_ids = ExamRecord.objects.filter(
            student=request.user,
            status='submitted'
        ).exclude(paper_id__isnull=True).values_list('paper_id', flat=True)

        queryset = ExamPaper.objects.filter(
            published_at__isnull=False,
            published_at__lte=timezone.now(),
            target_class_id__in=class_ids
        ).exclude(
            id__in=submitted_paper_ids
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
        paper_questions = exam.paper_questions.select_related('question').all()
        total_count = len(paper_questions)

        # 0 题的试卷允许直接提交
        if total_count == 0:
            with transaction.atomic():
                try:
                    exam_record = ExamRecord.objects.get(
                        student=request.user,
                        paper=exam,
                        status='ongoing'
                    )
                    exam_record.score = 0
                    exam_record.status = 'submitted'
                    exam_record.question_count = 0
                    exam_record.submitted_at = timezone.now()
                    exam_record.save()
                except ExamRecord.DoesNotExist:
                    pass
            return Response({
                'total': 0, 'correct': 0, 'score': 0, 'details': []
            })

        if not answers:
            return Response({'error': '请提交答案'}, status=400)

        # 构建答案字典 {question_id: answer}
        answer_dict = {item['question_id']: item['answer'] for item in answers}

        question_map = {pq.question_id: pq for pq in paper_questions}

        # 自动批改
        correct_count = 0
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
            # 获取进行中的 ExamRecord
            try:
                exam_record = ExamRecord.objects.get(
                    student=request.user,
                    paper=exam,
                    status='ongoing'
                )
                exam_record.score = total_score
                exam_record.status = 'submitted'
                exam_record.submitted_at = timezone.now()
                # 只有在 question_count 未设置时才赋值
                if not exam_record.question_count:
                    exam_record.question_count = total_count
                exam_record.save()
            except ExamRecord.DoesNotExist:
                return Response({'error': '没有找到进行中的考试记录，请先开始考试'}, status=400)

            # 保存 AnswerDetail（已有自动保存进度，用 update_or_create 避免重复插入）
            for paper_q in paper_questions:
                question = paper_q.question
                student_answer = answer_dict.get(question.id, '')
                is_correct = str(student_answer).strip() == str(question.answer).strip()

                AnswerDetail.objects.update_or_create(
                    record=exam_record,
                    question=question,
                    defaults={
                        'student_answer': str(student_answer),
                        'is_correct': is_correct
                    }
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

        # 按题型筛选
        question_type = request.query_params.get('question_type')
        if question_type:
            queryset = queryset.filter(question__question_type=question_type)

        # 按知识点筛选
        knowledge_point = request.query_params.get('knowledge_point')
        if knowledge_point:
            queryset = queryset.filter(question__knowledge_point=knowledge_point)

        # 按关键词搜索
        keyword = request.query_params.get('keyword')
        if keyword:
            queryset = queryset.filter(
                Q(question__content__icontains=keyword) |
                Q(question__knowledge_point__icontains=keyword)
            )

        queryset = queryset.order_by('-created_at')

        # summary 模式：只返回数量统计，不返回全量数据（首页只需要错题数）
        if request.query_params.get('summary') == 'true':
            base_qs = WrongQuestion.objects.filter(student=request.user)
            return Response({
                'total': base_qs.count(),
                'mastered_count': base_qs.filter(is_mastered=True).count(),
                'unmastered_count': base_qs.filter(is_mastered=False).count(),
            })

        total = queryset.count()
        mastered_count = queryset.filter(is_mastered=True).count()
        unmastered_count = queryset.filter(is_mastered=False).count()
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))
        start = (page - 1) * page_size
        paged = queryset[start:start + page_size]

        serializer = WrongQuestionSerializer(paged, many=True)
        return Response({
            'total': total,
            'mastered_count': mastered_count,
            'unmastered_count': unmastered_count,
            'page': page,
            'page_size': page_size,
            'results': serializer.data,
        })


class WrongQuestionAddView(APIView):
    """手动添加错题"""
    permission_classes = []

    def post(self, request):
        # 检查用户是否登录
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        # 手动添加错题：支持传入原始题目数据（content + answer）来创建新 Question
        content = request.data.get('content', '').strip()
        correct_answer = request.data.get('answer', '').strip()
        if content and correct_answer:
            question_type = request.data.get('question_type', 'choice')
            wrong_answer = request.data.get('wrong_answer', '')
            knowledge_point = request.data.get('knowledge_point', '')
            analysis = request.data.get('analysis', '')

            question = Question.objects.create(
                question_type=question_type,
                content=content,
                answer=correct_answer,
                knowledge_point=knowledge_point,
                analysis=analysis,
                created_by=request.user
            )

            WrongQuestion.objects.create(
                student=request.user,
                question=question,
                source_type='main',
                source_id=question.id,
                wrong_answer=wrong_answer,
                is_mastered=False
            )
            return Response({'message': '已添加到错题本', 'question_id': question.id})

        question_id = request.data.get('question_id')
        source_type = request.data.get('source_type', 'main')
        wrong_answer = request.data.get('wrong_answer', '')

        if not question_id:
            return Response({'error': '请提供 question_id'}, status=400)

        # 根据来源查找题目
        if source_type == 'ai':
            try:
                ai_question = QuestionAI.objects.get(id=question_id)
            except QuestionAI.DoesNotExist:
                return Response({'error': 'AI题目不存在'}, status=404)

            # 检查是否已在错题本中
            exists = WrongQuestion.objects.filter(
                student=request.user,
                source_type='ai',
                source_id=question_id
            ).exists()
            if exists:
                return Response({'message': '已在错题本中'})

            WrongQuestion.objects.create(
                student=request.user,
                source_type='ai',
                source_id=question_id,
                wrong_answer=wrong_answer,
                is_mastered=False
            )
        else:
            try:
                question = Question.objects.get(id=question_id)
            except Question.DoesNotExist:
                return Response({'error': '题目不存在'}, status=404)

            exists = WrongQuestion.objects.filter(
                student=request.user,
                question=question
            ).exists()
            if exists:
                return Response({'message': '已在错题本中'})

            WrongQuestion.objects.create(
                student=request.user,
                question=question,
                source_type='main',
                source_id=question_id,
                wrong_answer=wrong_answer,
                is_mastered=False
            )

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
        count = min(int(request.data.get('count', 1)), 30)  # 最大30道题
        target_library = request.data.get('target_library', 'main')  # main 或 ai_practice

        if not knowledge_point:
            return Response({'error': '请提供知识点'}, status=400)

        if count < 1:
            count = 1

        # 题型映射 (接收前端传入的 question_type，转换为中文描述)
        type_map = {
            'choice': '单选题',
            'true_false': '判断题',
            'multiple_choice': '多选题',
            'fill_blank': '填空题',
            'essay': '简答题',
            # 兼容旧前端传值
            'judge': '判断题',
            'multiple': '多选题',
        }
        question_type_cn = type_map.get(question_type, '单选题')

        # 前端题型映射 (返回给前端)
        frontend_type_map = {
            'choice': 'choice',
            'true_false': 'true_false',
            'multiple_choice': 'multiple_choice',
            'fill_blank': 'fill_blank',
            'essay': 'essay',
            # 兼容旧键
            'judge': 'true_false',
            'multiple': 'multiple_choice',
        }
        frontend_question_type = frontend_type_map.get(question_type, 'choice')

        # 难度映射
        diff_map = {
            'easy': '简单',
            'medium': '中等',
            'hard': '困难'
        }
        difficulty_cn = diff_map.get(difficulty, '中等')

        # 构建 Prompt —— 根据题型生成不同的提示
        is_true_false = (question_type in ('true_false', 'judge'))
        is_multiple = (question_type in ('multiple_choice', 'multiple'))
        is_fill_blank = (question_type == 'fill_blank')
        is_essay = (question_type == 'essay')

        # 构建每种题型的 JSON 示例格式
        if is_true_false:
            type_example = '{"content": "判断以下说法是否正确：XXX", "question_type": "true_false", "options": {"正确": "正确", "错误": "错误"}, "answer": "正确", "analysis": "详细解析"}'
        elif is_multiple:
            type_example = '{"content": "以下哪些是XXX？（多选）", "question_type": "multiple_choice", "options": {"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"}, "answer": "A,C", "analysis": "详细解析"}'
        elif is_fill_blank:
            type_example = '{"content": "XXX的______是YYY。多空用英文分号隔开，如 答案1;答案2", "question_type": "fill_blank", "options": {}, "answer": "正确答案", "analysis": "详细解析"}'
        elif is_essay:
            type_example = '{"content": "请简述XXX的原理和实现方法。", "question_type": "essay", "options": {}, "answer": "参考答案要点：1. ... 2. ...", "analysis": "详细解析"}'
        else:
            type_example = '{"content": "题目内容", "question_type": "choice", "options": {"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"}, "answer": "A", "analysis": "详细解析"}'

        # 题型特殊要求
        type_requirements = ''
        if is_true_false:
            type_requirements = '\n注意：这是**判断题**，只需要判断正误。答案只能是"正确"或"错误"。options固定为{"正确":"正确","错误":"错误"}。\n'
        elif is_multiple:
            type_requirements = '\n注意：这是**多选题**，必须返回2个或以上正确答案，answer格式如"A,C,D"（多个答案用英文逗号连接）。选项数量4-6个。如果该知识点确实无法出多选题，请改为出单选题并设question_type为"choice"。\n'
        elif is_fill_blank:
            type_requirements = '\n注意：这是**填空题**，题目中挖空处用______或___标记。多个填空的答案用英文分号隔开，如"答案1;答案2"。options可以为空对象{}。\n'
        elif is_essay:
            type_requirements = '\n注意：这是**简答题**，需要学生用自己的话作答。answer字段填写参考答案要点，分点列出。options可以为空对象{}。\n'

        # 单题 Prompt 模板
        single_prompt_template = """你是一位资深的网络安全/计算机专业出题老师。

你需要出一道{question_type_cn}，知识点：「{knowledge_point}」，难度：「{difficulty_cn}」。
{type_requirements}
要求：
1. 题目要结合实际应用场景，考查理解能力而非死记硬背
2. 选项要有迷惑性，错误选项要像常见错误答案（判断题、填空题、简答题除外）
3. 解析要详细（50字以上），解释为什么对、为什么错
4. 严格按JSON格式返回，不要有额外文字

返回格式示例：
{type_example}"""

        def generate_single_question(index):
            """生成单题的函数，供线程池调用"""
            prompt = single_prompt_template.format(
                question_type_cn=question_type_cn,
                knowledge_point=knowledge_point,
                difficulty_cn=difficulty_cn,
                type_requirements=type_requirements,
                type_example=type_example
            )
            
            api_url = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
            api_key = settings.ZHIPU_API_KEY

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
                response = requests.post(api_url, headers=headers, json=payload, timeout=60)
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
                if not isinstance(question_data, list):
                    question_data = [question_data]
                return question_data[0] if question_data else None
            except Exception as e:
                print(f"生成第 {index + 1} 题时出错: {str(e)}")
                return None

        # 使用 ThreadPoolExecutor 并发调用 AI API（最多3个线程）
        question_data_list = []
        max_workers = min(3, count)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(generate_single_question, i) for i in range(count)]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    question_data_list.append(result)

        if not question_data_list:
            return Response({'error': 'AI 生成题目全部失败'}, status=500)

        # 根据 target_library 选择存储的表
        is_ai_practice = target_library == 'ai_practice'
        difficulty_value = {'easy': 1, 'medium': 3, 'hard': 5}.get(difficulty, 3)

        # AI 返回的 question_type 映射（AI可能降级为choice）
        ai_type_map_reverse = {
            'choice': 'choice',
            'multiple_choice': 'multiple_choice',
            'multiple': 'multiple_choice',
            'single': 'choice',
        }

        # 保存到数据库并构建返回数据
        questions_list = []
        for q_data in question_data_list:
            # 优先使用AI返回的question_type，否则用请求的type
            ai_type = q_data.get('question_type', frontend_question_type)
            final_type = ai_type_map_reverse.get(ai_type, frontend_question_type)

            if is_ai_practice:
                question = QuestionAI.objects.create(
                    question_type=final_type,
                    content=q_data['content'],
                    options=json.dumps(q_data.get('options', {})),
                    answer=q_data.get('answer', ''),
                    analysis=q_data.get('analysis', ''),
                    knowledge_point=knowledge_point,
                    difficulty=difficulty_value,
                    creator=request.user
                )
            else:
                question = Question.objects.create(
                    question_type=final_type,
                    content=q_data['content'],
                    options=json.dumps(q_data.get('options', {})),
                    answer=q_data.get('answer', ''),
                    analysis=q_data.get('analysis', ''),
                    knowledge_point=knowledge_point,
                    difficulty=difficulty_value,
                    creator=request.user
                )
            questions_list.append({
                'id': question.id,
                'content': question.content,
                'question_type': final_type,
                'options': json.loads(question.options),
                'answer': question.answer,
                'analysis': question.analysis,
                'source_type': 'ai_practice' if is_ai_practice else 'main'
            })

        return Response({
            'message': f'成功生成 {len(questions_list)} 道题目',
            'questions': questions_list
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
        source_type = request.data.get('source_type', 'main')  # main 或 ai

        if not question_id:
            return Response({'error': '请提供 question_id'}, status=400)

        if not student_question:
            return Response({'error': '请提供 student_question'}, status=400)

        # 根据 source_type 从不同表获取题目
        try:
            if source_type == 'ai':
                question = QuestionAI.objects.get(id=question_id)
            else:
                question = Question.objects.get(id=question_id)
        except (Question.DoesNotExist, QuestionAI.DoesNotExist):
            return Response({'error': '题目不存在'}, status=404)

        # 构建 Prompt
        prompt = f"""你是一位耐心的老师，学生在做错题后向你请教。

题目：{question.content}
正确答案：{question.answer}
解析：{question.analysis or '暂无解析'}

学生问：{student_question}

请按以下格式回答：
1. 先肯定学生的提问（如"这是个好问题"）
2. 分步骤解释（1. 2. 3. 列出要点）
3. 如果是概念题，给出记忆技巧
4. 给出类似的练习题思路
5. 语气亲切自然"""

        # 调用智谱清言 API
        api_url = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
        api_key = settings.ZHIPU_API_KEY

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




class StartExamView(APIView):
    """开始考试，创建考试记录"""
    
    def post(self, request, exam_id):
        # 1. 检查登录
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)
        
        # 2. 检查试卷是否存在且已发布
        try:
            exam = ExamPaper.objects.get(
                id=exam_id,
                published_at__isnull=False,
                published_at__lte=timezone.now()
            )
        except ExamPaper.DoesNotExist:
            return Response({'error': '试卷不存在或未发布'}, status=404)
        
        # 3. 检查是否已有进行中的考试记录（避免重复创建）
        existing_record = ExamRecord.objects.filter(
            student=request.user,
            paper=exam,
            status='ongoing'
        ).first()
        
        if existing_record:
            return Response({
                'message': '继续考试',
                'exam_record_id': existing_record.id
            })
        
        # 4. 创建 ExamRecord，status='ongoing'
        exam_record = ExamRecord.objects.create(
            student=request.user,
            paper=exam,
            status='ongoing'
        )
        
        # 5. 返回 exam_record_id
        return Response({
            'message': '开始考试成功',
            'exam_record_id': exam_record.id
        })


class SaveProgressView(APIView):
    """保存答题进度 + 服务端超时验证"""

    def post(self, request, exam_id):
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        try:
            exam = ExamPaper.objects.get(
                id=exam_id,
                published_at__isnull=False,
                published_at__lte=timezone.now()
            )
        except ExamPaper.DoesNotExist:
            return Response({'error': '试卷不存在'}, status=404)

        # 获取进行中的 ExamRecord
        exam_record = ExamRecord.objects.filter(
            student=request.user,
            paper=exam,
            status='ongoing'
        ).first()

        if not exam_record:
            return Response({'error': '没有进行中的考试记录'}, status=400)

        # 服务端超时验证
        duration_minutes = exam.duration or 120
        deadline = exam_record.started_at + timezone.timedelta(minutes=duration_minutes)
        if timezone.now() > deadline:
            return Response({'error': '考试时间已到', 'timed_out': True}, status=403)

        # 保存/更新部分答案到 AnswerDetail
        answers = request.data.get('answers', {})
        if answers:
            paper_questions = exam.paper_questions.select_related('question').all()
            for pq in paper_questions:
                question = pq.question
                if str(question.id) in answers:
                    student_answer = str(answers[str(question.id)])
                    AnswerDetail.objects.update_or_create(
                        record=exam_record,
                        question=question,
                        defaults={'student_answer': student_answer}
                    )

        return Response({'saved': True})


class ReportTabSwitchView(APIView):
    """学生切屏上报"""
    
    def post(self, request):
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)
        
        exam_record_id = request.data.get('exam_record_id')
        if not exam_record_id:
            return Response({'error': '请提供 exam_record_id'}, status=400)
        
        try:
            exam_record = ExamRecord.objects.get(
                id=exam_record_id,
                student=request.user,
                status='ongoing'
            )
        except ExamRecord.DoesNotExist:
            return Response({'error': '没有正在进行的考试'}, status=404)
        
        exam_record.tab_switch_count += 1
        exam_record.save()
        
        if exam_record.tab_switch_count >= 3:
            exam_record.status = 'submitted'
            exam_record.submitted_at = timezone.now()
            exam_record.save()
            return Response({
                'warning': '切屏次数超过3次，考试已自动提交',
                'force_submit': True,
                'count': exam_record.tab_switch_count
            })
        
        return Response({
            'warning': f'切屏警告！还剩{3 - exam_record.tab_switch_count}次机会',
            'count': exam_record.tab_switch_count
        })


class PracticeModeView(APIView):
    """练习模式 - 从题库随机抽取题目"""
    permission_classes = []

    def get(self, request):
        """获取练习题目（随机抽取）"""
        # 1. 检查登录
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        # 2. 获取筛选参数
        count = int(request.query_params.get('count', 10))  # 默认抽取10道
        question_type = request.query_params.get('question_type')  # 题型筛选
        difficulty = request.query_params.get('difficulty')  # 难度筛选
        knowledge_point = request.query_params.get('knowledge_point')  # 知识点筛选

        # 限制抽取数量范围 1-50
        count = max(1, min(count, 50))

        # 3. 构建查询
        queryset = Question.objects.all()

        if question_type:
            queryset = queryset.filter(question_type=question_type)
        if difficulty:
            queryset = queryset.filter(difficulty=int(difficulty))
        if knowledge_point:
            queryset = queryset.filter(knowledge_point__icontains=knowledge_point)

        # 4. 随机抽取
        total_count = queryset.count()
        if total_count == 0:
            return Response({
                'message': '题库中没有符合条件的题目',
                'count': 0,
                'questions': []
            })

        # 如果抽取数量大于可用数量，返回全部
        if count >= total_count:
            selected_questions = list(queryset)
        else:
            selected_questions = list(queryset.order_by('?')[:count])

        # 5. 序列化（包含答案和解析，练习模式需要即时反馈）
        questions_data = []
        for q in selected_questions:
            # 解析 options JSON
            try:
                options = json.loads(q.options) if q.options else {}
            except json.JSONDecodeError:
                options = {}

            questions_data.append({
                'id': q.id,
                'content': q.content,
                'question_type': q.question_type,
                'question_type_display': q.get_question_type_display(),
                'options': options,
                'answer': q.answer,
                'analysis': q.analysis or '',
                'knowledge_point': q.knowledge_point or '',
                'difficulty': q.difficulty,
                'difficulty_display': q.get_difficulty_display(),
            })

        return Response({
            'message': '获取成功',
            'total_available': total_count,
            'selected_count': len(questions_data),
            'questions': questions_data
        })

    def post(self, request):
        """提交练习答案并获取反馈"""
        # 1. 检查登录
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        # 2. 获取提交的答案
        answers = request.data.get('answers', [])
        if not answers:
            return Response({'error': '请提交答案'}, status=400)

        # 3. 构建答案字典
        answers_dict = {item['question_id']: item.get('answer', '') for item in answers}

        # 4. 获取题目并批改
        question_ids = list(answers_dict.keys())
        questions = Question.objects.filter(id__in=question_ids)
        question_map = {q.id: q for q in questions}

        total_count = len(question_ids)
        correct_count = 0
        details = []

        for q_id, student_answer in answers_dict.items():
            question = question_map.get(q_id)
            if question is None:
                continue
            if not student_answer:
                is_correct = False
            else:
                is_correct = str(student_answer).strip() == str(question.answer).strip()
            if is_correct:
                correct_count += 1
            details.append({
                'question_id': question.id,
                'content': question.content,
                'correct': is_correct,
                'correct_answer': question.answer,
                'analysis': question.analysis or ''
            })

        # 正确率
        accuracy = round(correct_count / total_count * 100, 1) if total_count > 0 else 0

        # 5. 创建练习记录和答题详情
        with transaction.atomic():
            exam_record = ExamRecord.objects.create(
                student=request.user,
                paper=None,
                score=accuracy,
                status='submitted',
                submitted_at=timezone.now(),
                is_practice=True,
                question_count=total_count
            )

            # 创建 AnswerDetail，按前端发送顺序保存（保证历史记录顺序一致）
            for q_id in question_ids:
                q = question_map.get(q_id)
                if not q:
                    continue
                student_answer = answers_dict.get(q_id, '')
                if not student_answer:
                    student_answer = '未作答'
                    is_correct = False
                else:
                    is_correct = str(student_answer).strip() == str(q.answer).strip()
                AnswerDetail.objects.create(
                    record=exam_record,
                    question=q,
                    student_answer=str(student_answer),
                    is_correct=is_correct
                )

            # 添加错题到错题本
            for q_id in question_ids:
                q = question_map.get(q_id)
                if not q:
                    continue
                student_answer = answers_dict.get(q_id, '')
                is_correct = str(student_answer).strip() == str(q.answer).strip()
                if not is_correct:
                    WrongQuestion.objects.get_or_create(
                        student=request.user,
                        question=q
                    )

        return Response({
            'total': total_count,
            'correct': correct_count,
            'accuracy': accuracy,
            'details': details
        })


class PracticeKnowledgePointsView(APIView):
    """获取练习模式可用的知识点列表"""
    permission_classes = []

    def get(self, request):
        """获取所有可用的知识点"""
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        knowledge_points = Question.objects.exclude(
            knowledge_point__isnull=True
        ).exclude(
            knowledge_point=''
        ).values('knowledge_point').annotate(
            count=Count('id')
        ).order_by('-count')

        return Response({
            'knowledge_points': [
                {'name': kp['knowledge_point'], 'count': kp['count']}
                for kp in knowledge_points
            ]
        })


class PracticeIncompleteView(APIView):
    """保存未完成的练习（离开练习页时调用）"""
    permission_classes = []

    def post(self, request):
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        questions = request.data.get('questions', [])
        answers = request.data.get('answers', {})
        paper_name = request.data.get('paper_name', '练习模式')
        record_id = request.data.get('record_id')
        source_type = request.data.get('source_type', 'main')

        if not questions:
            return Response({'error': '缺少题目数据'}, status=400)

        # 如果有 record_id，说明是更新已有未完成记录
        if record_id:
            try:
                record = ExamRecord.objects.get(
                    id=record_id, student=request.user,
                    is_practice=True, is_completed=False
                )
                # 删除旧的 AnswerDetail，重新创建
                AnswerDetail.objects.filter(record=record).delete()
                record.question_count = len(questions)
                record.save()
            except ExamRecord.DoesNotExist:
                record_id = None

        if not record_id:
            # 创建新的未完成练习记录
            record = ExamRecord.objects.create(
                student=request.user,
                paper=None,
                score=None,
                status='ongoing',
                is_practice=True,
                is_completed=False,
                question_count=len(questions),
            )

        # 保存题目和已有答案到 AnswerDetail
        for idx, q_data in enumerate(questions):
            q_id = q_data.get('id')
            if not q_id:
                continue
            try:
                question = Question.objects.get(id=q_id)
            except Question.DoesNotExist:
                continue
            student_answer = answers.get(str(q_id), '')
            AnswerDetail.objects.create(
                record=record,
                question=question,
                student_answer=student_answer if student_answer else '',
                is_correct=False,
            )

        return Response({
            'record_id': record.id,
            'message': '未完成练习已保存',
        })


class PracticeRecordQuestionsView(APIView):
    """获取未完成练习记录的题目和已有答案"""
    permission_classes = []

    def get(self, request, record_id):
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        try:
            record = ExamRecord.objects.get(
                id=record_id, student=request.user,
                is_practice=True, is_completed=False
            )
        except ExamRecord.DoesNotExist:
            return Response({'error': '未完成的练习记录不存在'}, status=404)

        details = AnswerDetail.objects.filter(record=record).select_related('question').order_by('id')
        questions = []
        answers = {}
        for d in details:
            q = d.question
            try:
                options = json.loads(q.options) if q.options else {}
            except json.JSONDecodeError:
                options = {}
            questions.append({
                'id': q.id,
                'content': q.content,
                'question_type': q.question_type,
                'options': options,
                'answer': q.answer,
                'analysis': q.analysis or '',
                'knowledge_point': q.knowledge_point or '',
                'difficulty': q.difficulty,
            })
            answers[str(q.id)] = d.student_answer if d.student_answer else ''

        return Response({
            'paper_name': '练习模式',
            'questions': questions,
            'answers': answers,
            'record_id': record.id,
        })


class PracticeRecordCompleteView(APIView):
    """完成提交未完成的练习"""
    permission_classes = []

    def post(self, request, record_id):
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        try:
            record = ExamRecord.objects.get(
                id=record_id, student=request.user,
                is_practice=True, is_completed=False
            )
        except ExamRecord.DoesNotExist:
            return Response({'error': '未完成的练习记录不存在'}, status=404)

        answers = request.data.get('answers', [])
        if not answers:
            return Response({'error': '请提交答案'}, status=400)

        answers_dict = {item['question_id']: item.get('answer', '') for item in answers}
        question_ids = list(answers_dict.keys())
        questions = Question.objects.filter(id__in=question_ids)
        question_map = {q.id: q for q in questions}

        total_count = len(question_ids)
        correct_count = 0
        details = []

        with transaction.atomic():
            # 更新已有的 AnswerDetail
            for q_id, student_answer in answers_dict.items():
                question = question_map.get(q_id)
                if question is None:
                    continue
                if not student_answer:
                    is_correct = False
                else:
                    is_correct = str(student_answer).strip() == str(question.answer).strip()
                if is_correct:
                    correct_count += 1
                details.append({
                    'question_id': question.id,
                    'content': question.content,
                    'correct': is_correct,
                    'correct_answer': question.answer,
                    'analysis': question.analysis or ''
                })
                # 更新 AnswerDetail
                AnswerDetail.objects.filter(
                    record=record, question_id=q_id
                ).update(
                    student_answer=str(student_answer) if student_answer else '未作答',
                    is_correct=is_correct,
                )

            # 添加错题到错题本
            for q_id in question_ids:
                q = question_map.get(q_id)
                if not q:
                    continue
                student_answer = answers_dict.get(q_id, '')
                is_correct = str(student_answer).strip() == str(q.answer).strip()
                if not is_correct:
                    WrongQuestion.objects.get_or_create(
                        student=request.user,
                        question=q
                    )

            # 更新记录状态
            accuracy = round(correct_count / total_count * 100, 1) if total_count > 0 else 0
            record.score = accuracy
            record.status = 'submitted'
            record.is_completed = True
            record.submitted_at = timezone.now()
            record.question_count = total_count
            record.save()

        return Response({
            'total': total_count,
            'correct': correct_count,
            'accuracy': accuracy,
            'details': details,
        })


class StudyActivityView(APIView):
    """学生学习活跃度数据 - 按月展示的日历热力图"""
    permission_classes = []

    def get(self, request):
        """支持 ?year=2026&month=5 筛选某月，?months=6 按月汇总，默认返回注册至今全部数据"""
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        from datetime import timedelta, datetime
        from django.db.models import Count, Sum
        import calendar

        year = request.query_params.get('year')
        month = request.query_params.get('month')
        months = request.query_params.get('months')

        if months:
            months = int(months)
            end_date = timezone.now().date()
            start_date = (end_date.replace(day=1) - timedelta(days=1)).replace(day=1)
            for _ in range(months - 1):
                start_date = (start_date - timedelta(days=1)).replace(day=1)

            from django.db.models.functions import TruncMonth
            month_stats = AnswerDetail.objects.filter(
                record__student=request.user,
                record__status__in=['submitted', 'graded'],
                record__submitted_at__date__gte=start_date,
                record__submitted_at__date__lte=end_date
            ).annotate(month=TruncMonth('record__submitted_at')).values('month').annotate(
                total=Count('id')
            ).order_by('month')

            stats_map = {item['month'].strftime('%Y-%m'): item['total'] for item in month_stats}
            monthly = []
            cursor = start_date
            while cursor <= end_date:
                month_key = cursor.strftime('%Y-%m')
                monthly.append({'month': month_key, 'label': f"{cursor.month}月", 'count': stats_map.get(month_key, 0)})
                if cursor.month == 12:
                    cursor = cursor.replace(year=cursor.year + 1, month=1)
                else:
                    cursor = cursor.replace(month=cursor.month + 1)
            return Response(monthly)

        if year and month:
            year = int(year)
            month = int(month)
            start_date = datetime(year, month, 1).date()
            _, last_day = calendar.monthrange(year, month)
            end_date = datetime(year, month, last_day).date()
        else:
            end_date = timezone.now().date()
            start_date = request.user.date_joined.date()

        records = ExamRecord.objects.filter(
            student=request.user,
            status__in=['submitted', 'graded'],
            submitted_at__date__gte=start_date,
            submitted_at__date__lte=end_date
        )

        from django.db.models.functions import TruncDate
        answer_daily = AnswerDetail.objects.filter(
            record__student=request.user,
            record__status__in=['submitted', 'graded'],
            record__submitted_at__date__gte=start_date,
            record__submitted_at__date__lte=end_date
        ).annotate(day=TruncDate('record__submitted_at')).values('day').annotate(
            total=Count('id'),
            correct=Count('id', filter=Q(is_correct=True))
        ).order_by('day')

        answer_map = {item['day']: item for item in answer_daily}
        activity_data = []
        current_date = start_date

        while current_date <= end_date:
            day_records = records.filter(submitted_at__date=current_date)
            day_record_list = list(day_records)
            day_stats = answer_map.get(current_date, {'total': 0, 'correct': 0})
            total_questions = day_stats['total']
            correct_questions = day_stats['correct']
            correct_rate = round(correct_questions / total_questions * 100, 1) if total_questions > 0 else 0
            avg_score = 0.0
            if day_record_list:
                avg_score = sum(r.score or 0 for r in day_record_list) / len(day_record_list)
                avg_score = round(avg_score, 1)
            activity_data.append({
                'date': current_date.strftime('%Y-%m-%d'),
                'count': total_questions,
                'avg_score': avg_score,
                'correct_rate': correct_rate,
            })
            current_date += timedelta(days=1)

        if not (year and month):
            from datetime import datetime as dt
            today_start = dt.combine(timezone.now().date(), dt.min.time())
            today_end = dt.combine(timezone.now().date(), dt.max.time())
            session_dur = StudySession.objects.filter(
                user=request.user, start_time__gte=today_start, start_time__lte=today_end
            ).aggregate(total=Sum('duration'))['total'] or 0
            return Response({'data': activity_data, 'today_duration': session_dur})

        return Response(activity_data)


class PracticeRecordView(APIView):
    """做题记录"""
    permission_classes = []

    def get(self, request):
        """获取做题记录（考试和练习的汇总记录，按分页）"""
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 5))
        record_type = request.query_params.get('record_type')

        # 已完成的记录
        completed_qs = ExamRecord.objects.filter(
            student=request.user,
            is_completed=True,
        ).select_related('paper', 'student')

        # 未完成的练习记录（is_completed=False）
        incomplete_qs = ExamRecord.objects.filter(
            student=request.user,
            is_practice=True,
            is_completed=False,
        ).select_related('paper', 'student')

        if record_type == 'exam':
            completed_qs = completed_qs.filter(is_practice=False)
            incomplete_qs = incomplete_qs.none()
        elif record_type == 'practice':
            completed_qs = completed_qs.filter(is_practice=True)

        exam_qs = completed_qs.filter(is_practice=False).order_by('-submitted_at') if record_type in (None, 'exam') else completed_qs.none()
        practice_qs = completed_qs.filter(is_practice=True).order_by('-submitted_at') if record_type in (None, 'practice') else completed_qs.none()

        combined_data = []

        for r in exam_qs:
            combined_data.append({
                'id': r.id,
                'type': 'exam',
                'record_type': '考试',
                'is_completed': True,
                'date': r.submitted_at.strftime('%Y-%m-%d') if r.submitted_at else '',
                'datetime': r.submitted_at.strftime('%Y-%m-%d %H:%M') if r.submitted_at else '',
                'question_count': r.question_count or 0,
                'score': float(r.score) if r.score else 0,
                'paper_name': r.paper.name if r.paper else '考试',
            })

        practice_list = list(practice_qs)
        first_question_map = {}
        if practice_list:
            practice_ids = [r.id for r in practice_list]
            all_details = AnswerDetail.objects.filter(
                record_id__in=practice_ids
            ).select_related('question').order_by('record_id', 'id')
            seen = set()
            for d in all_details:
                if d.record_id not in seen:
                    seen.add(d.record_id)
                    content = d.question.content or ''
                    first_question_map[d.record_id] = (content[:20] + '...') if len(content) > 20 else content

        for r in practice_list:
            preview = first_question_map.get(r.id)
            paper_name = preview if preview else f'练习 {r.question_count or 0}题'
            combined_data.append({
                'id': r.id,
                'type': 'practice',
                'record_type': '练习',
                'is_completed': True,
                'date': r.submitted_at.strftime('%Y-%m-%d') if r.submitted_at else '',
                'datetime': r.submitted_at.strftime('%Y-%m-%d %H:%M') if r.submitted_at else '',
                'question_count': r.question_count or 0,
                'score': float(r.score) if r.score else 0,
                'paper_name': paper_name,
            })

        # 未完成的练习记录
        incomplete_list = list(incomplete_qs.order_by('-started_at'))
        incomplete_ids = [r.id for r in incomplete_list]
        incomplete_first_map = {}
        if incomplete_ids:
            inc_details = AnswerDetail.objects.filter(
                record_id__in=incomplete_ids
            ).select_related('question').order_by('record_id', 'id')
            seen = set()
            for d in inc_details:
                if d.record_id not in seen:
                    seen.add(d.record_id)
                    content = d.question.content or ''
                    incomplete_first_map[d.record_id] = (content[:20] + '...') if len(content) > 20 else content

        for r in incomplete_list:
            preview = incomplete_first_map.get(r.id)
            paper_name = preview if preview else f'练习 {r.question_count or 0}题'
            combined_data.append({
                'id': r.id,
                'type': 'practice',
                'record_type': '练习',
                'is_completed': False,
                'date': r.started_at.strftime('%Y-%m-%d') if r.started_at else '',
                'datetime': r.started_at.strftime('%Y-%m-%d %H:%M') if r.started_at else '',
                'question_count': r.question_count or 0,
                'score': 0,
                'paper_name': paper_name,
            })

        combined_data.sort(key=lambda x: x['datetime'], reverse=True)

        total = len(combined_data)
        start = (page - 1) * page_size
        end = start + page_size
        paged_data = combined_data[start:end]

        return Response({
            'total': total,
            'page': page,
            'page_size': page_size,
            'results': paged_data,
        })

    def post(self, request):
        """保存一条做题记录"""
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        required_fields = ['source_type', 'question_id', 'question_content',
                           'question_type', 'student_answer', 'correct_answer']
        for field in required_fields:
            if field not in request.data:
                return Response({'error': f'缺少必填字段: {field}'}, status=400)

        record = PracticeRecord.objects.create(
            student=request.user,
            source_type=request.data.get('source_type', 'main'),
            question_id=request.data.get('question_id'),
            question_content=request.data.get('question_content'),
            question_type=request.data.get('question_type'),
            student_answer=request.data.get('student_answer'),
            correct_answer=request.data.get('correct_answer'),
            is_correct=request.data.get('is_correct', False),
            knowledge_point=request.data.get('knowledge_point', ''),
        )

        return Response({
            'message': '保存成功',
            'record_id': record.id,
        })


class PracticeRecordDeleteView(APIView):
    """删除练习/考试记录"""
    permission_classes = []

    def delete(self, request, record_id):
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        try:
            record = ExamRecord.objects.get(id=record_id, student=request.user)
        except ExamRecord.DoesNotExist:
            return Response({'error': '记录不存在'}, status=404)

        # 级联删除 AnswerDetail
        AnswerDetail.objects.filter(record=record).delete()
        record.delete()
        return Response({'message': '删除成功'})


class ProfileView(APIView):
    """学生个人信息"""
    permission_classes = []

    def get(self, request):
        """获取当前登录学生的基本信息"""
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        user = request.user
        # 获取学生所在班级
        classes = user.student_classes.all()
        class_names = [sc.class_obj.name for sc in classes]

        # 统计考试次数（is_practice=False, status='submitted'）
        total_exams = ExamRecord.objects.filter(
            student=user,
            is_practice=False,
            status='submitted'
        ).count()

        # 统计练习次数（is_practice=True, status='submitted'）
        total_practice = ExamRecord.objects.filter(
            student=user,
            is_practice=True,
            status='submitted'
        ).count()

        # 统计错题总数（is_mastered=False）
        total_wrong = WrongQuestion.objects.filter(
            student=user,
            is_mastered=False
        ).count()

        # 统计已掌握错题数（is_mastered=True）
        mastered_wrong = WrongQuestion.objects.filter(
            student=user,
            is_mastered=True
        ).count()

        # 计算平均分
        from django.db.models import Avg
        avg_score_data = ExamRecord.objects.filter(
            student=user,
            status__in=['submitted', 'graded']
        ).aggregate(avg_score=Avg('score'))
        avg_score = round(avg_score_data['avg_score'] or 0, 1)

        # 统计有记录的天数（按日期去重）
        from django.db.models.functions import TruncDate
        exam_dates = ExamRecord.objects.filter(
            student=user,
            status__in=['submitted', 'graded'],
            submitted_at__isnull=False
        ).annotate(date=TruncDate('submitted_at')).values('date').distinct()
        practice_dates = PracticeRecord.objects.filter(
            student=user
        ).annotate(date=TruncDate('created_at')).values('date').distinct()
        all_dates = set()
        for d in exam_dates:
            if d['date']:
                all_dates.add(d['date'])
        for d in practice_dates:
            if d['date']:
                all_dates.add(d['date'])
        study_days = len(all_dates)

        # 计算正确率：正确的题数 ÷ 总做题数 × 100
        from django.db.models import Count, Q
        answer_stats = AnswerDetail.objects.filter(
            record__student=user,
            record__status__in=['submitted', 'graded']
        ).aggregate(
            total=Count('id'),
            correct=Count('id', filter=Q(is_correct=True))
        )
        total_answers = answer_stats['total'] or 0
        correct_answers = answer_stats['correct'] or 0
        correct_rate = round((correct_answers / total_answers * 100) if total_answers > 0 else 0, 1)

        # 计算学习时长（小时）：累加 started_at 到 submitted_at 的差值
        from django.db.models import Sum, F, ExpressionWrapper, DurationField
        from django.db.models.functions import Coalesce
        exam_records = ExamRecord.objects.filter(
            student=user,
            status__in=['submitted', 'graded'],
            started_at__isnull=False,
            submitted_at__isnull=False
        ).annotate(
            duration=ExpressionWrapper(
                F('submitted_at') - F('started_at'),
                output_field=DurationField()
            )
        )
        total_seconds = 0
        for record in exam_records:
            if record.duration:
                total_seconds += record.duration.total_seconds()
        study_hours = round(total_seconds / 3600, 1)

        return Response({
            'id': user.id,
            'username': user.username,
            'real_name': user.real_name,
            'email': user.email,
            'phone': user.phone,
            'school': '',
            'classes': class_names,
            'total_exams': total_exams,
            'total_practice': total_practice,
            'total_wrong': total_wrong,
            'mastered_wrong': mastered_wrong,
            'avg_score': avg_score,
            'study_days': study_days,
            'correct_rate': correct_rate,
            'study_hours': study_hours,
        })

    def put(self, request):
        """更新当前登录学生的个人信息（真实姓名、手机号、邮箱）"""
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        user = request.user
        real_name = (request.data.get('real_name') or '').strip()
        phone = (request.data.get('phone') or '').strip()
        email = (request.data.get('email') or '').strip()

        if not real_name:
            return Response({'error': '真实姓名不能为空'}, status=400)

        user.real_name = real_name
        user.phone = phone or ''
        user.email = email or ''
        user.save(update_fields=['real_name', 'phone', 'email'])

        return Response({
            'message': '个人信息更新成功',
            'real_name': user.real_name,
            'phone': user.phone,
            'email': user.email,
        })


class ChangePasswordView(APIView):
    """修改密码（需要旧密码）"""
    permission_classes = []

    def post(self, request):
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        user = request.user
        old_password = request.data.get('old_password', '')
        new_password = request.data.get('new_password', '')
        confirm_password = request.data.get('confirm_password', '')

        if not old_password:
            return Response({'error': '请输入旧密码'}, status=400)
        if not new_password:
            return Response({'error': '请输入新密码'}, status=400)
        if len(new_password) < 6:
            return Response({'error': '新密码至少需要6位'}, status=400)
        if new_password != confirm_password:
            return Response({'error': '两次输入的新密码不一致'}, status=400)

        if not user.check_password(old_password):
            return Response({'error': '旧密码不正确'}, status=400)

        user.set_password(new_password)
        user.save()

        return Response({'message': '密码修改成功，请重新登录'})


class ForgotPasswordView(APIView):
    """忘记密码 - 通过用户名和邮箱重置密码（不登录状态可用）"""
    permission_classes = []

    def post(self, request):
        action = request.data.get('action', 'reset').strip()
        username = request.data.get('username', '').strip()
        email = request.data.get('email', '').strip()
        new_password = request.data.get('new_password', '')
        confirm_password = request.data.get('confirm_password', '')

        if not username:
            return Response({'error': '请输入用户名'}, status=400)

        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response({'error': '用户名不存在'}, status=404)

        if email and user.email and user.email.strip().lower() != email.strip().lower():
            return Response({'error': '邮箱与账号不匹配'}, status=400)

        if action == 'verify':
            return Response({
                'message': '身份验证通过',
                'username': user.username,
            })

        if not new_password:
            return Response({'error': '请输入新密码'}, status=400)
        if len(new_password) < 6:
            return Response({'error': '新密码至少需要6位'}, status=400)
        if new_password != confirm_password:
            return Response({'error': '两次输入的新密码不一致'}, status=400)

        user.set_password(new_password)
        user.save()

        return Response({'message': '密码重置成功，请使用新密码登录'})


class WrongQuestionDeleteView(APIView):
    """删除错题"""
    permission_classes = []

    def delete(self, request, wrong_id):
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        try:
            wrong = WrongQuestion.objects.get(id=wrong_id)
        except WrongQuestion.DoesNotExist:
            return Response({'error': '错题记录不存在'}, status=404)

        if wrong.student != request.user:
            return Response({'error': '无权删除他人的错题'}, status=403)

        wrong.delete()
        return Response({'message': '已删除'})


class RecordDetailView(APIView):
    """某次做题/考试记录的题目详情"""
    permission_classes = []

    def get(self, request, record_id):
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        # 先尝试 ExamRecord
        try:
            record = ExamRecord.objects.get(id=record_id, student=request.user)
            details = AnswerDetail.objects.filter(record=record).select_related('question').order_by('id')
            questions = []
            for d in details:
                q = d.question
                try:
                    options = json.loads(q.options) if q.options else {}
                except json.JSONDecodeError:
                    options = {}
                questions.append({
                    'question_id': q.id,
                    'question_content': q.content,
                    'question_type': q.question_type,
                    'options': options,
                    'student_answer': d.student_answer,
                    'correct_answer': q.answer,
                    'is_correct': d.is_correct,
                })
            return Response({
                'record_id': record.id,
                'type': 'practice' if record.is_practice else 'exam',
                'paper_name': record.paper.name if record.paper else ('练习' if record.is_practice else '考试'),
                'score': float(record.score) if record.score else 0,
                'question_count': record.question_count or len(questions),
                'questions': questions,
            })
        except ExamRecord.DoesNotExist:
            pass

        # 练习记录回退：查 PracticeRecord
        try:
            pr = PracticeRecord.objects.get(id=record_id, student=request.user)
            return Response({
                'record_id': pr.id,
                'type': 'practice',
                'paper_name': f'练习 - {pr.question_content[:20]}',
                'score': 100 if pr.is_correct else 0,
                'question_count': 1,
                'questions': [{
                    'question_id': pr.question_id,
                    'question_content': pr.question_content,
                    'question_type': pr.question_type,
                    'options': {},
                    'student_answer': pr.student_answer,
                    'correct_answer': pr.correct_answer,
                    'is_correct': pr.is_correct,
                }],
            })
        except PracticeRecord.DoesNotExist:
            return Response({'error': '记录不存在'}, status=404)


class StudySessionStartView(APIView):
    """开始学习时段"""
    permission_classes = []

    def post(self, request):
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        session = StudySession.objects.create(user=request.user)
        return Response({
            'session_id': session.id,
            'start_time': session.start_time.isoformat()
        })


class StudySessionEndView(APIView):
    """结束学习时段"""
    permission_classes = []

    def post(self, request):
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        session = StudySession.objects.filter(
            user=request.user,
            end_time__isnull=True
        ).order_by('-start_time').first()

        if not session:
            return Response({'message': '没有进行中的学习时段'})

        session.end_time = timezone.now()
        session.duration = int((session.end_time - session.start_time).total_seconds())
        session.save()

        return Response({
            'session_id': session.id,
            'duration': session.duration
        })


class DailyStatsView(APIView):
    """学生首页 - 今日做题统计"""
    permission_classes = []

    def get(self, request):
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        from datetime import timedelta

        user = request.user
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        today_str = now.strftime('%Y-%m-%d')

        answer_stats = AnswerDetail.objects.filter(
            record__student=user,
            record__status__in=['submitted', 'graded'],
            record__submitted_at__gte=today_start,
            record__submitted_at__lt=today_end
        ).aggregate(
            total=Count('id'),
            correct=Count('id', filter=Q(is_correct=True))
        )
        total_questions = answer_stats['total'] or 0
        correct_questions = answer_stats['correct'] or 0
        correct_rate = round((correct_questions / total_questions * 100) if total_questions > 0 else 0, 1)

        duration_seconds = StudySession.objects.filter(
            user=user,
            start_time__gte=today_start,
            start_time__lt=today_end,
            duration__isnull=False
        ).aggregate(total=Sum('duration'))['total'] or 0

        return Response({
            'date': today_str,
            'count': total_questions,
            'correct_count': correct_questions,
            'correct_rate': correct_rate,
            'duration': duration_seconds,
        })


class KnowledgeStatsView(APIView):
    """知识点掌握分布统计"""
    permission_classes = []

    def get(self, request):
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        stats = AnswerDetail.objects.filter(
            record__student=request.user,
            record__status__in=['submitted', 'graded'],
            question__isnull=False
        ).values('question__knowledge_point').annotate(
            total=Count('id'),
            correct=Count('id', filter=Q(is_correct=True))
        ).order_by('-total')

        result = []
        for item in stats:
            kp = item['question__knowledge_point'] or '未分类'
            result.append({
                'knowledge_point': kp,
                'correct': item['correct'] or 0,
                'total': item['total'] or 0,
            })

        return Response(result)


class StudyDurationStatsView(APIView):
    """学习时长统计：总量 + 今日/本周/本月 + 每日分布"""
    permission_classes = []

    def get(self, request):
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        from django.db.models import Sum, F, ExpressionWrapper, DurationField
        from django.db.models.functions import TruncDate
        from datetime import timedelta

        user = request.user
        now = timezone.now()
        today = now.date()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)

        exam_records = ExamRecord.objects.filter(
            student=user,
            status__in=['submitted', 'graded'],
            started_at__isnull=False,
            submitted_at__isnull=False
        ).annotate(duration=ExpressionWrapper(
            F('submitted_at') - F('started_at'),
            output_field=DurationField()
        ))
        total_exam_seconds = sum(r.duration.total_seconds() for r in exam_records if r.duration)

        session_seconds = StudySession.objects.filter(
            user=user, duration__gt=0
        ).aggregate(total=Sum('duration'))['total'] or 0

        total_seconds = total_exam_seconds + session_seconds

        today_seconds = StudySession.objects.filter(
            user=user,
            start_time__date=today,
            duration__gt=0
        ).aggregate(total=Sum('duration'))['total'] or 0

        week_seconds = StudySession.objects.filter(
            user=user,
            start_time__date__gte=week_start,
            start_time__date__lte=today,
            duration__gt=0
        ).aggregate(total=Sum('duration'))['total'] or 0

        month_seconds = StudySession.objects.filter(
            user=user,
            start_time__date__gte=month_start,
            start_time__date__lte=today,
            duration__gt=0
        ).aggregate(total=Sum('duration'))['total'] or 0

        daily_distribution = StudySession.objects.filter(
            user=user,
            start_time__date__gte=month_start,
            start_time__date__lte=today,
            duration__gt=0
        ).annotate(date=TruncDate('start_time')).values('date').annotate(
            total_duration=Sum('duration')
        ).order_by('date')

        daily = [
            {'date': d['date'].strftime('%Y-%m-%d'), 'duration': d['total_duration'] or 0}
            for d in daily_distribution
        ]

        return Response({
            'total': total_seconds,
            'today': today_seconds,
            'week': week_seconds,
            'month': month_seconds,
            'daily': daily,
        })







