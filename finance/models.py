from django.db import models
from common.constants import ACCOUNT_TYPES, SETTLEMENT_STATUS, DEPRECIATION_METHODS


class Account(models.Model):
    """계정과목 (AccountSubject) - 연도별로 관리"""
    fiscal_year = models.IntegerField('회계연도', default=2026)
    code = models.CharField('계정코드', max_length=10)
    category_large = models.CharField('대분류(관)', max_length=50)  # 인건비, 사업비
    category_medium = models.CharField('중분류(항)', max_length=50)
    category_small = models.CharField('소분류(목)', max_length=50)
    account_name = models.CharField('계정명', max_length=100, default='')  # 실제 계정명
    account_name2 = models.CharField('계정명2', max_length=100, blank=True)  # 4대보험 세부 항목
    account_type = models.CharField('계정성격', max_length=10, choices=ACCOUNT_TYPES, default='EXPENSE')
    report_position = models.CharField('결산서 위치', max_length=50, blank=True)
    is_active = models.BooleanField('사용여부', default=True)

    class Meta:
        verbose_name = '계정과목'
        verbose_name_plural = '계정과목'
        unique_together = ['fiscal_year', 'code']
        ordering = ['fiscal_year', 'code']

    def __str__(self):
        return f"[{self.fiscal_year}] [{self.code}] {self.account_name}"


class Member(models.Model):
    """거래처/회원사 (Partner)"""
    PARTNER_TYPES = [
        ('MEMBER', '회원사'),
        ('GENERAL', '일반'),
    ]

    name = models.CharField('상호명', max_length=100)
    business_number = models.CharField('사업자번호', max_length=20, blank=True)
    partner_type = models.CharField('유형', max_length=10, choices=PARTNER_TYPES, default='GENERAL')
    contact_person = models.CharField('담당자', max_length=50, blank=True)
    is_active = models.BooleanField('사용여부', default=True)

    class Meta:
        verbose_name = '거래처/회원사'
        verbose_name_plural = '거래처/회원사'
        ordering = ['name']

    def __str__(self):
        return self.name


class Budget(models.Model):
    """예산 관리"""
    fiscal_year = models.IntegerField('회계연도')
    account = models.ForeignKey(Account, on_delete=models.PROTECT, verbose_name='계정과목')
    annual_amount = models.DecimalField('연간예산액', max_digits=15, decimal_places=0, default=0)
    supplementary_amount = models.DecimalField('추경예산액', max_digits=15, decimal_places=0, default=0)

    class Meta:
        verbose_name = '예산'
        verbose_name_plural = '예산'
        unique_together = ['fiscal_year', 'account']
        ordering = ['fiscal_year', 'account__code']

    def __str__(self):
        return f"{self.fiscal_year}년 {self.account}"

    @property
    def total_budget(self):
        """총 예산액 (연간 + 추경)"""
        return self.annual_amount + self.supplementary_amount


class FixedAsset(models.Model):
    """고정자산"""
    name = models.CharField('자산명', max_length=100)
    acquisition_date = models.DateField('취득일')
    acquisition_cost = models.DecimalField('취득가액', max_digits=15, decimal_places=0)
    useful_life = models.IntegerField('내용연수')
    depreciation_method = models.CharField(
        '상각방법', max_length=10, choices=DEPRECIATION_METHODS, default='STRAIGHT'
    )
    salvage_value = models.DecimalField('잔존가치', max_digits=15, decimal_places=0, default=0)
    current_value = models.DecimalField('현재잔액', max_digits=15, decimal_places=0)
    is_active = models.BooleanField('사용여부', default=True)

    class Meta:
        verbose_name = '고정자산'
        verbose_name_plural = '고정자산'
        ordering = ['-acquisition_date']

    def __str__(self):
        return self.name

    @property
    def annual_depreciation(self):
        """연간 감가상각비 (정액법 기준)"""
        if self.depreciation_method == 'STRAIGHT' and self.useful_life > 0:
            return (self.acquisition_cost - self.salvage_value) / self.useful_life
        return 0


class Transaction(models.Model):
    """거래 내역"""
    TRANSACTION_TYPES = [
        ('INCOME', '수입'),
        ('EXPENSE', '지출'),
        ('TRANSFER', '대체'),
    ]

    PAYMENT_METHODS = [
        ('CASH', '현금'),
        ('BANK', '예금'),
        ('CARD', '법인카드'),
        ('OTHER', '기타'),
    ]

    TRANSACTION_STATUS = [
        ('APPROVED', '승인'),
        ('PENDING', '대기'),
    ]

    date = models.DateField('일자')
    transaction_type = models.CharField('구분', max_length=10, choices=TRANSACTION_TYPES)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, verbose_name='계정과목')
    description = models.CharField('적요', max_length=200)
    partner = models.ForeignKey(
        Member, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='거래처'
    )
    amount = models.DecimalField('금액', max_digits=15, decimal_places=0)
    payment_method = models.CharField('결제수단', max_length=10, choices=PAYMENT_METHODS, default='BANK')
    receipt = models.FileField('증빙파일', upload_to='receipts/%Y/%m/', blank=True)
    status = models.CharField('상태', max_length=10, choices=TRANSACTION_STATUS, default='APPROVED')
    created_at = models.DateTimeField('등록일시', auto_now_add=True)
    updated_at = models.DateTimeField('수정일시', auto_now=True)

    class Meta:
        verbose_name = '거래내역추가'
        verbose_name_plural = '거래내역추가'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.date} [{self.get_transaction_type_display()}] {self.description}"


class Settlement(models.Model):
    """결산"""
    fiscal_year = models.IntegerField('회계연도', unique=True)
    closing_date = models.DateField('결산일')
    status = models.CharField('상태', max_length=10, choices=SETTLEMENT_STATUS, default='DRAFT')
    notes = models.TextField('비고', blank=True)
    created_at = models.DateTimeField('생성일시', auto_now_add=True)
    updated_at = models.DateTimeField('수정일시', auto_now=True)

    class Meta:
        verbose_name = '결산'
        verbose_name_plural = '결산'
        ordering = ['-fiscal_year']

    def __str__(self):
        return f"{self.fiscal_year}년 결산"


class CashBookCategory(models.Model):
    """출납장 과목 (예금출납장/현금출납장 수입 항목)"""
    BOOK_TYPES = [
        ('BANK', '예금출납장'),
        ('CASH', '현금출납장'),
    ]

    book_type = models.CharField('출납장유형', max_length=10, choices=BOOK_TYPES)
    name = models.CharField('과목명', max_length=50)
    order = models.IntegerField('순서', default=0)
    is_active = models.BooleanField('사용여부', default=True)

    class Meta:
        verbose_name = '출납장과목'
        verbose_name_plural = '출납장과목'
        ordering = ['book_type', 'order']
        unique_together = ['book_type', 'name']

    def __str__(self):
        return f"[{self.get_book_type_display()}] {self.name}"


class BankAccount(models.Model):
    """예금계좌 (예금출납장 비고용)"""
    bank_name = models.CharField('은행명', max_length=50)
    account_number = models.CharField('계좌번호', max_length=50)
    account_holder = models.CharField('예금주', max_length=50, blank=True)
    is_active = models.BooleanField('사용여부', default=True)
    order = models.IntegerField('순서', default=0)

    class Meta:
        verbose_name = '예금계좌'
        verbose_name_plural = '예금계좌'
        ordering = ['order']

    def __str__(self):
        return f"{self.bank_name} {self.account_number}"


class CashBook(models.Model):
    """출납장 (예금출납장/현금출납장)"""
    BOOK_TYPES = [
        ('BANK', '예금출납장'),
        ('CASH', '현금출납장'),
    ]

    ENTRY_TYPES = [
        ('INCOME', '수입'),
        ('EXPENSE', '지출'),
    ]

    book_type = models.CharField('출납장유형', max_length=10, choices=BOOK_TYPES)
    year = models.IntegerField('년도')
    month = models.IntegerField('월')
    entry_type = models.CharField('구분', max_length=10, choices=ENTRY_TYPES)
    date = models.DateField('일자')
    category = models.ForeignKey(
        CashBookCategory, on_delete=models.PROTECT, verbose_name='과목',
        null=True, blank=True
    )
    account = models.ForeignKey(
        Account, on_delete=models.PROTECT, verbose_name='계정과목',
        null=True, blank=True
    )
    description = models.CharField('내용', max_length=200, blank=True)
    amount = models.DecimalField('금액', max_digits=15, decimal_places=0, default=0)
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.SET_NULL, verbose_name='계좌',
        null=True, blank=True
    )
    note = models.CharField('비고', max_length=200, blank=True)
    order = models.IntegerField('순서', default=0)
    linked_transaction = models.ForeignKey(
        'Transaction', on_delete=models.SET_NULL, verbose_name='연결된 거래',
        null=True, blank=True, related_name='cashbook_entries'
    )
    created_at = models.DateTimeField('생성일시', auto_now_add=True)
    updated_at = models.DateTimeField('수정일시', auto_now=True)

    class Meta:
        verbose_name = '출납장'
        verbose_name_plural = '출납장'
        ordering = ['book_type', 'year', 'month', 'entry_type', 'order']

    def __str__(self):
        category_name = self.category.name if self.category else self.description
        return f"{self.year}.{self.month} [{self.get_book_type_display()}] {category_name}"
