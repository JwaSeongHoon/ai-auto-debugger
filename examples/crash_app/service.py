USERS = [
    {"name": "김철수", "email": "chulsoo@example.com"},
    {"name": "이영희"},
]


def format_user(user):
    email = user["email"]
    return f"{user['name']} <{email}>"


def start_app():
    for user in USERS:
        print(format_user(user))
    print("모든 사용자 출력 완료")
