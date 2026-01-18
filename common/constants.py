# 공통 상수 정의

# 계정 유형
ACCOUNT_TYPES = [
    ('ASSET', '자산'),
    ('LIABILITY', '부채'),
    ('EQUITY', '자본'),
    ('INCOME', '수입'),
    ('EXPENSE', '지출'),
]

# 결산 상태
SETTLEMENT_STATUS = [
    ('DRAFT', '임시저장'),
    ('SUBMITTED', '제출됨'),
    ('APPROVED', '승인됨'),
]

# 감가상각 방법
DEPRECIATION_METHODS = [
    ('STRAIGHT', '정액법'),
    ('DECLINING', '정률법'),
]
