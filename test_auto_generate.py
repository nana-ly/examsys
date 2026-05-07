import requests
import json

base_url = "http://127.0.0.1:8000"

session = requests.Session()

# 1. 先获取 CSRF Token
session.get(f"{base_url}/api/users/auth/login/")
csrf_token = session.cookies.get('csrftoken')
print("CSRF Token:", csrf_token)

# 2. 登录（带上 CSRF Token）
login_data = {
    "username": "admin",
    "password": "admin123"
}

headers = {
    'X-CSRFToken': csrf_token,
    'Content-Type': 'application/json'
}

login_response = session.post(f"{base_url}/api/users/auth/login/", json=login_data, headers=headers)
print("登录状态:", login_response.status_code)
print("登录返回:", login_response.text)

# 3. 测试智能组卷（带上新的 CSRF Token）
csrf_token = session.cookies.get('csrftoken', csrf_token)
headers['X-CSRFToken'] = csrf_token

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