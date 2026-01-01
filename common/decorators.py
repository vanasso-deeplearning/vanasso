# 공통 데코레이터
from functools import wraps
from django.contrib import messages
from django.shortcuts import redirect


def admin_required(view_func):
    """관리자 권한 필요 데코레이터"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, '로그인이 필요합니다.')
            return redirect('login')
        if not request.user.is_staff:
            messages.error(request, '관리자 권한이 필요합니다.')
            return redirect('finance:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper
