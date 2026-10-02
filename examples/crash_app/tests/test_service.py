from service import format_user


def test_format_user_with_email():
    user = {"name": "홍길동", "email": "hong@example.com"}
    assert format_user(user) == "홍길동 <hong@example.com>"
