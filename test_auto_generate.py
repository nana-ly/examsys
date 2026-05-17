import requests
import json

base_url = "http://127.0.0.1:8000"

session = requests.Session()

# 1. 注册一个测试教师账号
register_data = {
    "username": "admin",
    "password": "admin123",
    "password_confirm": "admin123",
    "role": "teacher",
    "real_name": "测试教师"
}
r = session.post(f"{base_url}/api/users/auth/register/", json=register_data)
print("注册状态:", r.status_code, r.json())

# 2. 获取 CSRF Token
r = session.get(f"{base_url}/api/users/csrf/")
csrf_token = r.json().get('csrfToken') or session.cookies.get('csrftoken')
print("CSRF Token:", csrf_token)

# 3. 登录
login_data = {
    "username": "admin",
    "password": "admin123"
}

headers = {
    'X-CSRFToken': csrf_token or '',
    'Content-Type': 'application/json'
}

login_response = session.post(f"{base_url}/api/users/auth/login/", json=login_data, headers=headers)
print("登录状态:", login_response.status_code)
print("登录返回:", login_response.text)

# 4. 测试智能组卷（带上新的 CSRF Token）
csrf_token = session.cookies.get('csrftoken', csrf_token)
headers['X-CSRFToken'] = csrf_token or ''

url = f"{base_url}/api/exam/papers/auto_generate/"

data = {
    "name": "期中考试",
    "target_class": 1,
    "total_score": 100,
    "duration": 120,
    "type_distribution": {
        "choice": 2,
        "true_false": 1
    },
    "difficulty_distribution": {
        "1": 1,
        "2": 2
    }
}

response = session.post(url, json=data, headers=headers)
print("状态码:", response.status_code)
print("返回:", json.dumps(response.json(), ensure_ascii=False, indent=2))