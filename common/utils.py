# 공통 유틸리티 함수
from decimal import Decimal


def format_currency(amount):
    """금액을 한국 원화 형식으로 포맷팅"""
    if amount is None:
        return "₩0"
    return f"₩{amount:,.0f}"


def calculate_depreciation(cost, salvage_value, useful_life, method='STRAIGHT'):
    """감가상각비 계산

    Args:
        cost: 취득가액
        salvage_value: 잔존가치
        useful_life: 내용연수(년)
        method: 감가상각 방법 (STRAIGHT: 정액법, DECLINING: 정률법)

    Returns:
        연간 감가상각비
    """
    if method == 'STRAIGHT':
        return (Decimal(cost) - Decimal(salvage_value)) / useful_life
    # TODO: 정률법 구현
    return Decimal(0)
