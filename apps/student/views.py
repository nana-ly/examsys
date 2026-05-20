from rest_framework.views import APIView
from rest_framework.response import Response
from django.utils import timezone
from django.http import Http404
from django.db import transaction
from django.db.models import Count
from django.conf import settings
import json
import requests
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

from exam_core.models import ExamPaper, ExamPaperQuestion, ExamRecord, AnswerDetail, WrongQuestion, PracticeRecord
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

            # 创建 AnswerDetail
            for paper_q in paper_questions:
                question = paper_q.question
                student_answer = answer_dict.get(question.id, '')
                is_correct = str(student_answer).strip() == str(question.answer).strip()

                AnswerDetail.objects.create(
                    record=exam_record,
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

        queryset = queryset.order_by('-created_at')

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

        # 题型映射 (内部使用)
        type_map = {
            'choice': '单选题',
            'judge': '判断题',
            'multiple': '多选题'
        }
        question_type_cn = type_map.get(question_type, '单选题')

        # 前端题型映射 (返回给前端)
        frontend_type_map = {
            'choice': 'choice',
            'judge': 'true_false',
            'multiple': 'multiple_choice'
        }
        frontend_question_type = frontend_type_map.get(question_type, 'choice')

        # 难度映射
        diff_map = {
            'easy': '简单',
            'medium': '中等',
            'hard': '困难'
        }
        difficulty_cn = diff_map.get(difficulty, '中等')

        # 构建 Prompt (单题生成)
        is_multiple = (question_type == 'multiple')
        multi_instruction = ''
        if is_multiple:
            multi_instruction = '\n注意：这是**多选题**，必须返回多个正确答案，answer格式如"A,B,C"。如果该知识点无法出多选题，请改为出单选题并设置question_type为"choice"。\n'

        # 单题 Prompt 模板
        single_prompt_template = """你是一位资深的网络安全/计算机专业出题老师。

你需要出一道{question_type_cn}，知识点：「{knowledge_point}」，难度：「{difficulty_cn}」。
{multi_instruction}
要求：
1. 题目要结合实际应用场景，考查理解能力而非死记硬背
2. 选项要有迷惑性，错误选项要像常见错误答案
3. 解析要详细（50字以上），解释为什么对、为什么错
4. 严格按JSON格式返回

返回格式：
{{"content": "题目内容", "question_type": "choice", "options": {{"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"}}, "answer": "A", "analysis": "详细解析"}}"""

        def generate_single_question(index):
            """生成单题的函数，供线程池调用"""
            prompt = single_prompt_template.format(
                question_type_cn=question_type_cn,
                knowledge_point=knowledge_point,
                difficulty_cn=difficulty_cn,
                multi_instruction=multi_instruction
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
        answer_dict = {item['question_id']: item['answer'] for item in answers}

        # 4. 获取题目并批改
        question_ids = list(answer_dict.keys())
        questions = Question.objects.filter(id__in=question_ids)
        question_map = {q.id: q for q in questions}

        correct_count = 0
        total_count = len(question_ids)
        details = []

        for q_id, student_answer in answer_dict.items():
            question = question_map.get(q_id)
            if question is None:
                continue

            # 比较答案
            is_correct = str(student_answer).strip().upper() == str(question.answer).strip().upper()
            if is_correct:
                correct_count += 1

            details.append({
                'question_id': question.id,
                'content': question.content,
                'correct': is_correct,
                'correct_answer': question.answer,
                'analysis': question.analysis or ''
            })

        # 计算得分
        accuracy = round(correct_count / total_count * 100, 1) if total_count > 0 else 0

        # 5. 创建练习记录（用于学习统计）
        try:
            exam_record = ExamRecord.objects.create(
                student=request.user,
                paper=None,  # 练习不关联特定试卷
                score=accuracy,
                status='submitted',
                submitted_at=timezone.now(),
                is_practice=True,
                question_count=total_count
            )
        except Exception as e:
            # 记录创建失败不影响答题反馈返回
            print(f"创建练习记录失败: {e}")

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


class StudyActivityView(APIView):
    """学生学习活跃度数据 - 用于 ECharts 热力图"""
    permission_classes = []

    def get(self, request):
        """返回过去 30 天每天的题目数量和平均得分"""
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        from datetime import timedelta
        from django.db.models import Avg, Sum

        # 计算过去 30 天的日期范围
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=29)

        # 查询已提交的考试记录
        records = ExamRecord.objects.filter(
            student=request.user,
            status__in=['submitted', 'graded'],
            submitted_at__date__gte=start_date,
            submitted_at__date__lte=end_date
        )

        # 查询练习记录数量（用于计算练习题目）
        from exam_core.models import PracticeRecord
        practice_count_map = {}
        practice_records_all = PracticeRecord.objects.filter(
            student=request.user,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).values('created_at__date').annotate(count=Count('id'))
        for item in practice_records_all:
            practice_count_map[item['created_at__date']] = item['count']

        # 按日期分组统计
        activity_data = []
        current_date = start_date

        while current_date <= end_date:
            day_records = records.filter(submitted_at__date=current_date)
            day_record_list = list(day_records)

            # 统计考试题目数量
            exam_questions = 0
            # 先尝试累加 question_count > 0 的记录
            for record in day_record_list:
                if record.question_count and record.question_count > 0:
                    exam_questions += record.question_count
            
            # 如果没有 question_count > 0 的记录，用考试次数统计
            if exam_questions == 0:
                exam_questions = len(day_record_list)

            # 练习模式：每次练习默认 5 题
            practice_count = practice_count_map.get(current_date, 0)
            practice_questions = practice_count * 5

            total_questions = exam_questions + practice_questions

            avg_score = 0.0
            if day_record_list:
                avg_score = sum(r.score or 0 for r in day_record_list) / len(day_record_list)
                avg_score = round(avg_score, 1)

            activity_data.append({
                'date': current_date.strftime('%Y-%m-%d'),
                'count': total_questions,
                'avg_score': avg_score
            })

            current_date += timedelta(days=1)

        return Response(activity_data)


class PracticeRecordView(APIView):
    """做题记录"""
    permission_classes = []

    def get(self, request):
        """获取做题记录（考试和练习的汇总记录，按分页）"""
        if not request.user.is_authenticated:
            return Response({'error': '请先登录'}, status=401)

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))

        # 查询已提交的考试记录
        exam_records = ExamRecord.objects.filter(
            student=request.user,
            status__in=['submitted', 'graded']
        ).order_by('-submitted_at')

        # 查询练习记录
        practice_records = PracticeRecord.objects.filter(
            student=request.user
        ).order_by('-created_at')

        # 合并记录
        combined_data = []

        for r in exam_records:
            combined_data.append({
                'id': r.id,
                'type': 'exam',
                'record_type': '考试',
                'date': r.submitted_at.strftime('%Y-%m-%d') if r.submitted_at else '',
                'datetime': r.submitted_at.strftime('%Y-%m-%d %H:%M') if r.submitted_at else '',
                'question_count': r.question_count or 0,
                'score': r.score or 0,
                'paper_name': r.paper.name if r.paper else 'AI练习' if r.is_practice else '练习',
            })

        for r in practice_records:
            combined_data.append({
                'id': r.id,
                'type': 'practice',
                'record_type': '练习',
                'date': r.created_at.strftime('%Y-%m-%d') if r.created_at else '',
                'datetime': r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else '',
                'question_count': 1,
                'score': 100 if r.is_correct else 0,
                'paper_name': r.question_content[:20] + '...' if r.question_content and len(r.question_content) > 20 else r.question_content or '练习',
            })

        # 按时间倒序排列
        combined_data.sort(key=lambda x: x['datetime'], reverse=True)

        # 分页
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


