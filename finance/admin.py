from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.urls import path
from django.shortcuts import redirect
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.template.response import TemplateResponse
from decimal import Decimal
import pandas as pd
import json

from .models import Account, Member, Budget, FixedAsset, Transaction, Settlement, CashBook, CashBookCategory, BankAccount


# 사용자 Admin 커스터마이징 (스태프 권한 추가 화면에 포함)
admin.site.unregister(User)

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    # 사용자 추가 시 스태프 권한을 바로 설정할 수 있도록
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2', 'is_staff', 'is_active'),
        }),
    )


# 4대보험 구성 항목 (합산 대상)
INSURANCE_ITEMS = ['국민연금', '건강보험', '고용보험', '산재보험']

# 계정코드 자동 생성용 카운터
ACCOUNT_CODE_PREFIX = {
    '인건비': '1',
    '사업비': '2',
}


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ['fiscal_year', 'code', 'account_type', 'category_large', 'category_medium', 'category_small', 'account_name', 'is_active']
    list_filter = ['fiscal_year', 'account_type', 'category_large', 'is_active']
    search_fields = ['code', 'account_name', 'category_small']
    ordering = ['fiscal_year', 'code']

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('main/', self.admin_site.admin_view(self.account_main_view), name='account_main'),
            path('upload/', self.admin_site.admin_view(self.upload_account), name='account_upload'),
        ]
        return custom_urls + urls

    def account_main_view(self, request):
        """계정과목등록(예산입력) 통합 메뉴"""
        from datetime import datetime
        current_year = datetime.now().year

        # 연도 선택
        selected_year = request.GET.get('year', current_year)
        try:
            selected_year = int(selected_year)
        except:
            selected_year = current_year

        # 연도 목록 (현재년도 기준 +-2년)
        years = list(range(current_year + 2, current_year - 3, -1))

        # 기존 데이터 확인
        account_count = Account.objects.filter(fiscal_year=selected_year).count()
        budget_count = Budget.objects.filter(fiscal_year=selected_year).count()

        # POST 처리
        if request.method == 'POST':
            action = request.POST.get('action')
            fiscal_year = int(request.POST.get('fiscal_year', selected_year))
            excel_file = request.FILES.get('excel_file')

            if action == 'budget_upload' and excel_file:
                return self.handle_budget_upload(request, fiscal_year, excel_file)
            elif action == 'account_upload' and excel_file:
                return self.handle_account_upload(request, fiscal_year, excel_file)
            elif action == 'delete_year_data':
                return self.handle_delete_year_data(request, fiscal_year)

        context = {
            **self.admin_site.each_context(request),
            'title': '계정과목등록(예산입력)',
            'opts': self.model._meta,
            'years': years,
            'selected_year': selected_year,
            'account_count': account_count,
            'budget_count': budget_count,
            'existing_data': account_count > 0 or budget_count > 0,
        }

        return TemplateResponse(request, 'admin/account_main.html', context)

    def handle_budget_upload(self, request, fiscal_year, excel_file):
        """예산 업로드 처리 (동일 계정명은 예산 합산, Account는 첫 번째만 생성)"""
        # 기존 예산 데이터 존재 확인
        existing_budgets = Budget.objects.filter(fiscal_year=fiscal_year).count()
        if existing_budgets > 0:
            messages.error(request, f'{fiscal_year}년 예산이 이미 존재합니다. 기존 데이터를 삭제 후 업로드해주세요.')
            return redirect(f"{request.path}?year={fiscal_year}")

        try:
            df = pd.read_excel(excel_file)
        except Exception as e:
            messages.error(request, f'엑셀 파일 읽기 오류: {e}')
            return redirect(f"{request.path}?year={fiscal_year}")

        # 예산 업로드 로직 (동일 계정명은 합산)
        accounts = []
        budgets = {}
        created_account_names = set()  # 이미 생성된 계정명 추적
        code_counters = {'인건비': 0, '사업비': 0}

        for _, row in df.iterrows():
            category_large = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
            category_medium = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ''
            category_small = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else ''
            account_name = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else ''

            # 연간예산액 (6번째 컬럼 - index 5, 계정명2 컬럼이 있으므로)
            try:
                amount = Decimal(str(row.iloc[5])) if pd.notna(row.iloc[5]) else Decimal('0')
            except:
                amount = Decimal('0')

            if not category_large or category_large == 'nan' or category_large == '구분(대분류)':
                continue

            # 예산 금액 저장 (계정명 기준으로 합산)
            if account_name not in budgets:
                budgets[account_name] = amount
            else:
                budgets[account_name] += amount

            # Account 생성 (동일 계정명은 첫 번째만 생성)
            if account_name not in created_account_names:
                code_counters[category_large] = code_counters.get(category_large, 0) + 1
                code = f"{ACCOUNT_CODE_PREFIX.get(category_large, '9')}{code_counters[category_large]:03d}"
                accounts.append({
                    'fiscal_year': fiscal_year, 'code': code,
                    'category_large': category_large, 'category_medium': category_medium,
                    'category_small': category_small, 'account_name': account_name,
                    'account_type': 'EXPENSE',
                })
                created_account_names.add(account_name)

        if not accounts:
            messages.error(request, '계정 데이터를 찾을 수 없습니다.')
            return redirect(f"{request.path}?year={fiscal_year}")

        with transaction.atomic():
            account_count = 0
            budget_count = 0
            for acc_data in accounts:
                Account.objects.create(**acc_data)
                account_count += 1

            for account_name, amount in budgets.items():
                if amount > 0:
                    account = Account.objects.filter(
                        fiscal_year=fiscal_year, account_name=account_name
                    ).first()
                    if account:
                        Budget.objects.create(
                            fiscal_year=fiscal_year, account=account,
                            annual_amount=amount, supplementary_amount=Decimal('0'),
                        )
                        budget_count += 1

        messages.success(request, f'{fiscal_year}년 예산 업로드 완료: 계정과목 {account_count}건, 예산 {budget_count}건')
        return redirect(f"{request.path}?year={fiscal_year}")

    def handle_account_upload(self, request, fiscal_year, excel_file):
        """계정과목 업로드 처리"""
        try:
            df = pd.read_excel(excel_file)
        except Exception as e:
            messages.error(request, f'엑셀 파일 읽기 오류: {e}')
            return redirect(f"{request.path}?year={fiscal_year}")

        created_count = 0
        skipped_count = 0
        code_counter = {}

        with transaction.atomic():
            for _, row in df.iterrows():
                account_type = str(row.get('계정유형', '')).strip()
                category_large = str(row.get('대분류', '')).strip()
                category_medium = str(row.get('중분류', '')).strip()
                category_small = str(row.get('소분류', '')).strip()
                account_name = str(row.get('계정명', '')).strip()

                if not account_type or account_type == 'nan' or not account_name:
                    continue

                type_prefix = {'ASSET': 'A', 'LIABILITY': 'L', 'EQUITY': 'E', 'INCOME': 'I', 'EXPENSE': 'X'}
                prefix = type_prefix.get(account_type, 'Z')
                code_counter[prefix] = code_counter.get(prefix, 0) + 1
                code = f"{prefix}{code_counter[prefix]:03d}"

                if Account.objects.filter(fiscal_year=fiscal_year, account_name=account_name, account_type=account_type).exists():
                    skipped_count += 1
                    continue

                Account.objects.create(
                    fiscal_year=fiscal_year, code=code, account_type=account_type,
                    category_large=category_large, category_medium=category_medium,
                    category_small=category_small, account_name=account_name,
                )
                created_count += 1

        if created_count > 0:
            messages.success(request, f'계정과목 {created_count}건 등록 완료' + (f' (중복 {skipped_count}건 제외)' if skipped_count else ''))
        else:
            messages.warning(request, '등록된 계정과목이 없습니다.')

        return redirect(f"{request.path}?year={fiscal_year}")

    def handle_delete_year_data(self, request, fiscal_year):
        """연도별 데이터 삭제 (거래내역 → 예산 → 계정과목 순서로 삭제)"""
        # 해당 연도 계정과목에 연결된 거래내역 확인
        year_accounts = Account.objects.filter(fiscal_year=fiscal_year)
        transaction_count = Transaction.objects.filter(account__in=year_accounts).count()

        if transaction_count > 0:
            # 거래내역이 있으면 확인 후 함께 삭제
            confirm = request.POST.get('confirm_delete_all')
            if confirm != 'yes':
                messages.warning(
                    request,
                    f'{fiscal_year}년 계정과목에 연결된 거래내역 {transaction_count}건이 있습니다. '
                    f'거래내역도 함께 삭제하려면 다시 삭제 버튼을 클릭하세요.'
                )
                # 세션에 확인 플래그 저장
                request.session['pending_delete_year'] = fiscal_year
                return redirect(f"{request.path}?year={fiscal_year}&confirm_needed=1")

        with transaction.atomic():
            # 1. 거래내역 삭제
            trans_deleted, _ = Transaction.objects.filter(account__in=year_accounts).delete()
            # 2. 예산 삭제
            budget_count, _ = Budget.objects.filter(fiscal_year=fiscal_year).delete()
            # 3. 계정과목 삭제
            account_count, _ = Account.objects.filter(fiscal_year=fiscal_year).delete()

        # 세션 정리
        if 'pending_delete_year' in request.session:
            del request.session['pending_delete_year']

        msg = f'{fiscal_year}년 데이터 삭제 완료: 계정과목 {account_count}건, 예산 {budget_count}건'
        if trans_deleted > 0:
            msg += f', 거래내역 {trans_deleted}건'
        messages.success(request, msg)
        return redirect(f"{request.path}?year={fiscal_year}")

    def upload_account(self, request):
        """계정과목 엑셀 업로드"""
        context = {
            **self.admin_site.each_context(request),
            'title': '계정과목 엑셀 업로드',
            'opts': self.model._meta,
        }

        if request.method == 'POST':
            excel_file = request.FILES.get('excel_file')
            fiscal_year = request.POST.get('fiscal_year')

            if not excel_file or not fiscal_year:
                messages.error(request, '파일과 회계연도를 모두 입력해주세요.')
                return TemplateResponse(request, 'admin/account_upload.html', context)

            try:
                fiscal_year = int(fiscal_year)
            except ValueError:
                messages.error(request, '회계연도는 숫자로 입력해주세요.')
                return TemplateResponse(request, 'admin/account_upload.html', context)

            try:
                df = pd.read_excel(excel_file)
            except Exception as e:
                messages.error(request, f'엑셀 파일 읽기 오류: {e}')
                return TemplateResponse(request, 'admin/account_upload.html', context)

            # 계정과목 생성
            created_count = 0
            skipped_count = 0
            code_counter = {}

            with transaction.atomic():
                for _, row in df.iterrows():
                    account_type = str(row.get('계정유형', '')).strip()
                    category_large = str(row.get('대분류', '')).strip()
                    category_medium = str(row.get('중분류', '')).strip()
                    category_small = str(row.get('소분류', '')).strip()
                    account_name = str(row.get('계정명', '')).strip()

                    if not account_type or account_type == 'nan' or not account_name:
                        continue

                    # 계정코드 자동 생성
                    type_prefix = {'ASSET': 'A', 'LIABILITY': 'L', 'EQUITY': 'E', 'INCOME': 'I', 'EXPENSE': 'X'}
                    prefix = type_prefix.get(account_type, 'Z')
                    code_counter[prefix] = code_counter.get(prefix, 0) + 1
                    code = f"{prefix}{code_counter[prefix]:03d}"

                    # 중복 체크
                    if Account.objects.filter(fiscal_year=fiscal_year, account_name=account_name, account_type=account_type).exists():
                        skipped_count += 1
                        continue

                    Account.objects.create(
                        fiscal_year=fiscal_year,
                        code=code,
                        account_type=account_type,
                        category_large=category_large,
                        category_medium=category_medium,
                        category_small=category_small,
                        account_name=account_name,
                    )
                    created_count += 1

            if created_count > 0:
                messages.success(request, f'계정과목 {created_count}건 등록 완료' + (f' (중복 {skipped_count}건 제외)' if skipped_count else ''))
            else:
                messages.warning(request, '등록된 계정과목이 없습니다.')

            return redirect('admin:finance_account_changelist')

        return TemplateResponse(request, 'admin/account_upload.html', context)


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ['name', 'partner_type', 'business_number', 'contact_person', 'is_active']
    list_filter = ['partner_type', 'is_active']
    search_fields = ['name', 'business_number']
    ordering = ['name']


@admin.register(FixedAsset)
class FixedAssetAdmin(admin.ModelAdmin):
    list_display = ['name', 'acquisition_date', 'acquisition_cost', 'useful_life', 'current_value', 'is_active']
    list_filter = ['is_active', 'depreciation_method']
    search_fields = ['name']
    ordering = ['-acquisition_date']


@admin.register(CashBookCategory)
class CashBookCategoryAdmin(admin.ModelAdmin):
    list_display = ['book_type', 'entry_type', 'name', 'is_active']
    list_filter = ['book_type', 'entry_type', 'is_active']
    list_editable = ['is_active']
    ordering = ['book_type', 'entry_type', 'name']


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ['bank_name', 'account_number', 'account_holder', 'order', 'is_active']
    list_editable = ['order', 'is_active']
    ordering = ['order']


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['date', 'transaction_type', 'account', 'description', 'amount', 'payment_method', 'status']
    list_filter = ['transaction_type', 'payment_method', 'status', 'date']
    search_fields = ['description', 'account__account_name']
    date_hierarchy = 'date'
    ordering = ['-date', '-created_at']

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('list/', self.admin_site.admin_view(self.transaction_list_view), name='transaction_list'),
            path('card-upload/', self.admin_site.admin_view(self.card_upload_view), name='card_upload'),
            path('card-upload/save/', self.admin_site.admin_view(self.card_upload_save), name='card_upload_save'),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        """거래내역추가 메뉴 클릭 시 바로 추가 폼으로 이동"""
        return redirect('admin:finance_transaction_add')

    def transaction_list_view(self, request):
        """거래내역 조회/삭제 화면"""
        return super().changelist_view(request)

    def get_accounts_json(self):
        """현재 연도 계정과목을 JSON으로 반환"""
        from datetime import datetime
        current_year = datetime.now().year

        # 현재 연도 계정과목 조회
        accounts = Account.objects.filter(
            fiscal_year=current_year,
            is_active=True
        ).order_by('account_type', 'code')

        # 현재 연도에 계정이 없으면 가장 최근 연도 사용
        if not accounts.exists():
            latest_year = Account.objects.order_by('-fiscal_year').values_list('fiscal_year', flat=True).first()
            if latest_year:
                accounts = Account.objects.filter(
                    fiscal_year=latest_year,
                    is_active=True
                ).order_by('account_type', 'code')

        account_list = []
        for acc in accounts:
            display_name = f"[{acc.get_account_type_display()}] {acc.account_name}"
            account_list.append({
                'id': acc.id,
                'account_type': acc.account_type,
                'display_name': display_name,
            })

        return json.dumps(account_list, ensure_ascii=False)

    def add_view(self, request, form_url='', extra_context=None):
        """추가 폼 화면 - 구분별 계정과목 필터링"""
        extra_context = extra_context or {}
        extra_context['title'] = '거래내역추가'
        extra_context['show_save_and_add_another'] = False
        extra_context['accounts_json'] = self.get_accounts_json()
        return super().add_view(request, form_url, extra_context)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        """수정 폼 화면 - 구분별 계정과목 필터링"""
        extra_context = extra_context or {}
        extra_context['accounts_json'] = self.get_accounts_json()
        return super().change_view(request, object_id, form_url, extra_context)

    def card_upload_view(self, request):
        """카드 엑셀 업로드 화면"""
        from datetime import datetime

        context = {
            **self.admin_site.each_context(request),
            'title': '카드 엑셀 업로드',
            'opts': self.model._meta,
        }

        if request.method == 'POST' and request.FILES.get('excel_file'):
            excel_file = request.FILES['excel_file']

            try:
                df = pd.read_excel(excel_file)
            except Exception as e:
                messages.error(request, f'엑셀 파일 읽기 오류: {e}')
                return TemplateResponse(request, 'admin/card_upload.html', context)

            # 카드 내역 파싱
            card_items = []
            for idx, row in df.iterrows():
                # 취소 건 제외
                cancel_status = str(row.get('취소\n구분', '')).strip()
                if cancel_status != '정상':
                    continue

                # 이용일자 파싱 (2025.11.02 형식)
                date_str = str(row.get('이용일자', '')).strip()
                try:
                    date_obj = datetime.strptime(date_str, '%Y.%m.%d').date()
                except:
                    continue

                # 매출금액
                try:
                    amount = Decimal(str(row.get('매출금액', 0)))
                except:
                    amount = Decimal('0')

                if amount <= 0:
                    continue

                card_items.append({
                    'index': idx,
                    'date': date_obj,
                    'description': str(row.get('가맹점명', '')).strip(),
                    'amount': amount,
                    'card_number': str(row.get('카드번호', '')).strip(),
                })

            if not card_items:
                messages.error(request, '유효한 카드 내역이 없습니다.')
                return TemplateResponse(request, 'admin/card_upload.html', context)

            # 현재 연도 계정과목 조회
            current_year = datetime.now().year
            accounts = Account.objects.filter(
                fiscal_year=current_year,
                account_type='EXPENSE'
            ).order_by('code')

            # 계정과목이 없으면 전체 조회
            if not accounts.exists():
                accounts = Account.objects.filter(account_type='EXPENSE').order_by('fiscal_year', 'code')

            context['card_items'] = card_items
            context['accounts'] = accounts
            context['total_amount'] = sum(item['amount'] for item in card_items)
            context['total_count'] = len(card_items)

            # 세션에 데이터 저장 (저장 시 사용)
            request.session['card_items'] = [
                {
                    'index': item['index'],
                    'date': item['date'].isoformat(),
                    'description': item['description'],
                    'amount': str(item['amount']),
                    'card_number': item['card_number'],
                }
                for item in card_items
            ]

            return TemplateResponse(request, 'admin/card_upload_confirm.html', context)

        return TemplateResponse(request, 'admin/card_upload.html', context)

    def card_upload_save(self, request):
        """카드 내역 일괄 저장"""
        from datetime import datetime

        if request.method != 'POST':
            return redirect('admin:card_upload')

        card_items = request.session.get('card_items', [])
        if not card_items:
            messages.error(request, '저장할 데이터가 없습니다.')
            return redirect('admin:card_upload')

        saved_count = 0
        skipped_count = 0

        with transaction.atomic():
            for item in card_items:
                account_id = request.POST.get(f'account_{item["index"]}')

                if not account_id:
                    skipped_count += 1
                    continue

                try:
                    account = Account.objects.get(pk=account_id)
                    Transaction.objects.create(
                        date=datetime.fromisoformat(item['date']).date(),
                        transaction_type='EXPENSE',
                        account=account,
                        description=item['description'],
                        amount=Decimal(item['amount']),
                        payment_method='CARD',
                        status='APPROVED',
                    )
                    saved_count += 1
                except Exception as e:
                    skipped_count += 1

        # 세션 정리
        if 'card_items' in request.session:
            del request.session['card_items']

        if saved_count > 0:
            messages.success(request, f'카드 내역 {saved_count}건 저장 완료' + (f' (미선택 {skipped_count}건 제외)' if skipped_count else ''))
        else:
            messages.warning(request, '저장된 내역이 없습니다. 계정과목을 선택해주세요.')

        return redirect('admin:transaction_list')


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ['fiscal_year', 'closing_date', 'status', 'created_at']
    list_filter = ['status', 'fiscal_year']
    ordering = ['-fiscal_year']


@admin.register(CashBook)
class CashBookAdmin(admin.ModelAdmin):
    """월간보고서 관리 (예금출납장, 현금출납장)"""
    list_display = ['year', 'month', 'book_type', 'entry_type', 'date', 'description', 'amount']
    list_filter = ['book_type', 'year', 'month']
    ordering = ['-year', '-month', 'book_type', 'entry_type', 'order']

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('monthly-report/', self.admin_site.admin_view(self.monthly_report_main), name='monthly_report'),
            path('cashbook/<str:book_type>/<int:year>/<int:month>/', self.admin_site.admin_view(self.cashbook_view), name='cashbook_view'),
            path('cashbook/save/', self.admin_site.admin_view(self.cashbook_save), name='cashbook_save'),
            path('cashbook/pdf/<str:book_type>/<int:year>/<int:month>/', self.admin_site.admin_view(self.cashbook_pdf), name='cashbook_pdf'),
            path('budget-execution/<int:year>/<int:month>/', self.admin_site.admin_view(self.budget_execution_view), name='budget_execution'),
            path('budget-execution/print/<int:year>/<int:month>/', self.admin_site.admin_view(self.budget_execution_print), name='budget_execution_print'),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        """기본 목록 대신 월간보고서 메인으로 리다이렉트"""
        return redirect('admin:monthly_report')

    def monthly_report_main(self, request):
        """월간보고서 메인 화면"""
        from datetime import datetime
        current_month = datetime.now().month

        # 연도/월 선택 (기본 연도: 2025년 - 테스트용)
        default_year = 2025
        selected_year = int(request.GET.get('year', default_year))
        selected_month = int(request.GET.get('month', current_month))

        # 연도 목록 (2024~2027)
        years = list(range(2027, 2023, -1))
        months = list(range(1, 13))

        context = {
            **self.admin_site.each_context(request),
            'title': '월간보고서',
            'opts': self.model._meta,
            'years': years,
            'months': months,
            'selected_year': selected_year,
            'selected_month': selected_month,
        }

        return TemplateResponse(request, 'admin/monthly_report_main.html', context)

    def cashbook_view(self, request, book_type, year, month):
        """출납장 조회/편집 화면"""
        from datetime import date
        from calendar import monthrange

        # 해당 월의 첫날, 마지막날
        _, last_day = monthrange(year, month)

        # 계좌 목록 (예금출납장만)
        bank_accounts = BankAccount.objects.filter(is_active=True).order_by('order') if book_type == 'BANK' else []

        # 수입 과목 (CashBookCategory - 수입)
        income_categories = CashBookCategory.objects.filter(
            book_type=book_type, entry_type='INCOME', is_active=True
        ).order_by('name')

        # 지출 과목: 계정과목(EXPENSE, LIABILITY) + 출납장과목(지출)
        # 1. 계정과목 (EXPENSE, LIABILITY 타입)
        expense_accounts = list(Account.objects.filter(
            fiscal_year=year,
            account_type__in=['EXPENSE', 'LIABILITY'],
            is_active=True
        ).order_by('code'))

        # 해당 연도에 없으면 최근 연도 사용
        if not expense_accounts:
            latest_year = Account.objects.filter(account_type__in=['EXPENSE', 'LIABILITY']).order_by('-fiscal_year').values_list('fiscal_year', flat=True).first()
            if latest_year:
                expense_accounts = list(Account.objects.filter(
                    fiscal_year=latest_year,
                    account_type__in=['EXPENSE', 'LIABILITY'],
                    is_active=True
                ).order_by('code'))

        # 2. 출납장과목 (지출)
        expense_categories = list(CashBookCategory.objects.filter(
            book_type=book_type, entry_type='EXPENSE', is_active=True
        ).order_by('name'))

        # 지출 항목 통합 리스트 생성 (계정과목 + 출납장과목)
        expense_items = []
        for acc in expense_accounts:
            expense_items.append({
                'value': f"account:{acc.id}",
                'display_name': acc.account_name,
            })
        for cat in expense_categories:
            expense_items.append({
                'value': f"category:{cat.id}",
                'display_name': cat.name,
            })

        # 기존 데이터 조회 (수입: category_id 사용)
        income_entries = list(CashBook.objects.filter(
            book_type=book_type, year=year, month=month, entry_type='INCOME'
        ).order_by('order').values(
            'id', 'date', 'category_id', 'description', 'amount', 'bank_account_id', 'note', 'order'
        ))

        # 지출 데이터 조회 (account_id 또는 category_id 사용)
        expense_entries_raw = list(CashBook.objects.filter(
            book_type=book_type, year=year, month=month, entry_type='EXPENSE'
        ).order_by('order').values(
            'id', 'date', 'account_id', 'category_id', 'description', 'amount', 'bank_account_id', 'note', 'order'
        ))

        # 지출 항목에 선택값 형식 추가 (account:123 또는 category:456)
        expense_entries = []
        for entry in expense_entries_raw:
            if entry['account_id']:
                entry['selected_value'] = f"account:{entry['account_id']}"
            elif entry['category_id']:
                entry['selected_value'] = f"category:{entry['category_id']}"
            else:
                entry['selected_value'] = ''
            expense_entries.append(entry)

        # 빈 행 추가 (예금출납장: 수입 20줄/지출 20줄, 현금출납장: 수입 5줄/지출 20줄)
        income_row_count = 20 if book_type == 'BANK' else 5
        while len(income_entries) < income_row_count:
            income_entries.append({
                'id': None, 'date': None, 'category_id': None, 'description': '',
                'amount': 0, 'bank_account_id': None, 'note': '', 'order': len(income_entries)
            })
        while len(expense_entries) < 20:
            expense_entries.append({
                'id': None, 'date': None, 'account_id': None, 'category_id': None,
                'selected_value': '', 'description': '',
                'amount': 0, 'bank_account_id': None, 'note': '', 'order': len(expense_entries)
            })

        # 수입/지출 합계
        income_total = sum(e['amount'] for e in income_entries if e['amount'])
        expense_total = sum(e['amount'] for e in expense_entries if e['amount'])

        book_type_display = '예금출납장' if book_type == 'BANK' else '현금출납장'

        # 연월 선택용 범위 (기본 2025년)
        year_range = list(range(2024, 2028))
        month_range = list(range(1, 13))

        context = {
            **self.admin_site.each_context(request),
            'title': f'{book_type_display} ({year}. {month}월)',
            'opts': self.model._meta,
            'book_type': book_type,
            'book_type_display': book_type_display,
            'year': year,
            'month': month,
            'bank_accounts': bank_accounts,
            'income_categories': income_categories,
            'expense_items': expense_items,
            'income_entries': income_entries,
            'expense_entries': expense_entries,
            'income_total': income_total,
            'expense_total': expense_total,
            'last_day': last_day,
            'year_range': year_range,
            'month_range': month_range,
        }

        return TemplateResponse(request, 'admin/cashbook_form.html', context)

    def cashbook_save(self, request):
        """출납장 저장"""
        if request.method != 'POST':
            return redirect('admin:monthly_report')

        book_type = request.POST.get('book_type')
        year = int(request.POST.get('year'))
        month = int(request.POST.get('month'))

        # 기존 데이터 삭제 (연결된 Transaction도 함께 삭제)
        old_cashbooks = CashBook.objects.filter(book_type=book_type, year=year, month=month)
        linked_transaction_ids = list(old_cashbooks.exclude(
            linked_transaction__isnull=True
        ).values_list('linked_transaction_id', flat=True))
        old_cashbooks.delete()
        if linked_transaction_ids:
            Transaction.objects.filter(id__in=linked_transaction_ids).delete()

        saved_count = 0

        # 수입 내역 저장 (CashBookCategory 사용)
        idx = 0
        while True:
            day = request.POST.get(f'income_day_{idx}')
            if day is None:
                break

            category_id = request.POST.get(f'income_category_{idx}', '').strip()
            amount_str = request.POST.get(f'income_amount_{idx}', '0').replace(',', '')
            bank_account_id = request.POST.get(f'income_bank_{idx}', '').strip()
            note = request.POST.get(f'income_note_{idx}', '').strip()

            if day and category_id:
                try:
                    from datetime import date
                    entry_date = date(year, month, int(day))
                    amount = Decimal(amount_str) if amount_str else Decimal('0')

                    category = CashBookCategory.objects.get(pk=category_id)
                    bank_account = BankAccount.objects.get(pk=bank_account_id) if bank_account_id else None

                    CashBook.objects.create(
                        book_type=book_type,
                        year=year,
                        month=month,
                        entry_type='INCOME',
                        date=entry_date,
                        category=category,
                        amount=amount,
                        bank_account=bank_account,
                        note=note,
                        order=saved_count,
                    )
                    saved_count += 1
                except Exception as e:
                    pass

            idx += 1

        # 지출 내역 저장 (account:123 또는 category:456 형식)
        # 예금출납장 + 계정과목(비용/부채) 선택 시 Transaction에도 동시 저장
        idx = 0
        transaction_saved = 0
        while True:
            day = request.POST.get(f'expense_day_{idx}')
            if day is None:
                break

            item_value = request.POST.get(f'expense_item_{idx}', '').strip()
            amount_str = request.POST.get(f'expense_amount_{idx}', '0').replace(',', '')
            note = request.POST.get(f'expense_note_{idx}', '').strip()

            if day and item_value:
                try:
                    from datetime import date
                    entry_date = date(year, month, int(day))
                    amount = Decimal(amount_str) if amount_str else Decimal('0')

                    # item_value 파싱 (account:123 또는 category:456)
                    item_type, item_id = item_value.split(':')
                    account = None
                    category = None
                    display_name = ''

                    if item_type == 'account':
                        account = Account.objects.get(pk=int(item_id))
                        display_name = account.account_name
                    elif item_type == 'category':
                        category = CashBookCategory.objects.get(pk=int(item_id))
                        display_name = category.name

                    # 예금출납장 + 계정과목 선택 시 Transaction 테이블에도 저장
                    linked_trans = None
                    if book_type == 'BANK' and account and amount > 0:
                        linked_trans = Transaction.objects.create(
                            date=entry_date,
                            transaction_type='EXPENSE',
                            account=account,
                            description=display_name + (f' ({note})' if note else ''),
                            amount=amount,
                            payment_method='BANK',
                            status='APPROVED',
                        )
                        transaction_saved += 1

                    CashBook.objects.create(
                        book_type=book_type,
                        year=year,
                        month=month,
                        entry_type='EXPENSE',
                        date=entry_date,
                        account=account,
                        category=category,
                        description=display_name,
                        amount=amount,
                        note=note,
                        order=saved_count,
                        linked_transaction=linked_trans,
                    )
                    saved_count += 1
                except Exception as e:
                    pass

            idx += 1

        book_type_display = '예금출납장' if book_type == 'BANK' else '현금출납장'
        msg = f'{year}년 {month}월 {book_type_display} 저장 완료 ({saved_count}건)'
        if transaction_saved > 0:
            msg += f' - 거래내역 {transaction_saved}건 동시 저장'
        messages.success(request, msg)

        return redirect('admin:cashbook_view', book_type=book_type, year=year, month=month)

    def cashbook_pdf(self, request, book_type, year, month):
        """출납장 PDF 출력"""
        from django.http import HttpResponse

        # 데이터 조회
        income_entries = CashBook.objects.filter(
            book_type=book_type, year=year, month=month, entry_type='INCOME'
        ).select_related('category', 'bank_account', 'account').order_by('order')

        expense_entries = CashBook.objects.filter(
            book_type=book_type, year=year, month=month, entry_type='EXPENSE'
        ).select_related('category', 'bank_account', 'account').order_by('order')

        income_total = sum(e.amount for e in income_entries)
        expense_total = sum(e.amount for e in expense_entries)

        book_type_display = '예금출납장' if book_type == 'BANK' else '현금출납장'

        # HTML로 출력 (브라우저에서 인쇄)
        context = {
            **self.admin_site.each_context(request),
            'title': f'{book_type_display} ({year}. {month}월)',
            'book_type': book_type,
            'book_type_display': book_type_display,
            'year': year,
            'month': month,
            'income_entries': income_entries,
            'expense_entries': expense_entries,
            'income_total': income_total,
            'expense_total': expense_total,
        }

        return TemplateResponse(request, 'admin/cashbook_print.html', context)

    def _get_budget_execution_data(self, year, month):
        """월간예산집행내역 데이터 조회 (공통 로직)"""
        from datetime import date
        from collections import OrderedDict

        budgets = Budget.objects.filter(fiscal_year=year).select_related('account').order_by('account__code')

        year_start = date(year, 1, 1)
        month_start = date(year, month, 1)
        if month == 12:
            next_month_start = date(year + 1, 1, 1)
        else:
            next_month_start = date(year, month + 1, 1)

        # 원본 PDF 형식: 대분류 > 중분류 > 계정명 구조
        # 대분류별로 그룹화하고, 중분류별 소계 표시
        execution_data = OrderedDict()

        for budget in budgets:
            acc = budget.account
            large_cat = acc.category_large  # 인건비, 사업비
            medium_cat = acc.category_medium  # 급여, 복리후생비 등

            # 대분류별로 그룹화
            if large_cat not in execution_data:
                execution_data[large_cat] = {
                    'medium_categories': OrderedDict(),
                    'total_budget': Decimal('0'),
                    'total_executed': Decimal('0'),
                    'total_month': Decimal('0'),
                }

            # 중분류별로 그룹화
            if medium_cat not in execution_data[large_cat]['medium_categories']:
                execution_data[large_cat]['medium_categories'][medium_cat] = {
                    'items': [],
                    'subtotal_budget': Decimal('0'),
                    'subtotal_executed': Decimal('0'),
                    'subtotal_month': Decimal('0'),
                }

            # 누계 집행액 (연초부터 해당 월까지)
            cumulative = Transaction.objects.filter(
                account=acc,
                date__gte=year_start,
                date__lt=next_month_start,
                transaction_type='EXPENSE',
                status='APPROVED'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            # 당월 집행액
            monthly = Transaction.objects.filter(
                account=acc,
                date__gte=month_start,
                date__lt=next_month_start,
                transaction_type='EXPENSE',
                status='APPROVED'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            annual_budget = budget.total_budget
            exec_rate = (cumulative / annual_budget * 100) if annual_budget > 0 else Decimal('0')
            remaining = annual_budget - cumulative

            item = {
                'account': acc,
                'display_name': acc.account_name,
                'annual_budget': annual_budget,
                'cumulative': cumulative,
                'exec_rate': exec_rate,
                'monthly': monthly,
                'remaining': remaining,
                'note': '',
            }

            med_data = execution_data[large_cat]['medium_categories'][medium_cat]
            med_data['items'].append(item)
            med_data['subtotal_budget'] += annual_budget
            med_data['subtotal_executed'] += cumulative
            med_data['subtotal_month'] += monthly

            # 대분류 합계
            execution_data[large_cat]['total_budget'] += annual_budget
            execution_data[large_cat]['total_executed'] += cumulative
            execution_data[large_cat]['total_month'] += monthly

        # 각 레벨별 잔여예산 및 집행률 계산, row_count 계산
        for large_cat, large_data in execution_data.items():
            row_count = 0
            for med_cat, med_data in large_data['medium_categories'].items():
                med_data['subtotal_remaining'] = med_data['subtotal_budget'] - med_data['subtotal_executed']
                med_data['subtotal_rate'] = (med_data['subtotal_executed'] / med_data['subtotal_budget'] * 100) if med_data['subtotal_budget'] > 0 else Decimal('0')
                # 중분류별 행 수 = 항목 수 + (항목이 2개 이상일 때만 소계 1행)
                item_count = len(med_data['items'])
                med_data['show_subtotal'] = item_count > 1
                med_data['row_count'] = item_count + (1 if item_count > 1 else 0)
                row_count += med_data['row_count']

            # 대분류 합계 행은 rowspan 밖에 있으므로 제외
            large_data['row_count'] = row_count

            large_data['total_remaining'] = large_data['total_budget'] - large_data['total_executed']
            large_data['total_rate'] = (large_data['total_executed'] / large_data['total_budget'] * 100) if large_data['total_budget'] > 0 else Decimal('0')

        # 전체 합계
        grand_total_budget = sum(d['total_budget'] for d in execution_data.values())
        grand_total_executed = sum(d['total_executed'] for d in execution_data.values())
        grand_total_month = sum(d['total_month'] for d in execution_data.values())
        grand_total_remaining = grand_total_budget - grand_total_executed
        grand_total_rate = (grand_total_executed / grand_total_budget * 100) if grand_total_budget > 0 else Decimal('0')

        return {
            'execution_data': execution_data,
            'grand_total_budget': grand_total_budget,
            'grand_total_executed': grand_total_executed,
            'grand_total_month': grand_total_month,
            'grand_total_remaining': grand_total_remaining,
            'grand_total_rate': grand_total_rate,
        }

    def budget_execution_view(self, request, year, month):
        """월간예산집행내역 조회"""
        data = self._get_budget_execution_data(year, month)

        # 연월 선택용 범위 (기본 2025년)
        year_range = list(range(2024, 2028))
        month_range = list(range(1, 13))

        context = {
            **self.admin_site.each_context(request),
            'title': f'{year}년 {month}월 예산집행 내역',
            'opts': self.model._meta,
            'year': year,
            'month': month,
            'year_range': year_range,
            'month_range': month_range,
            **data,
        }

        return TemplateResponse(request, 'admin/budget_execution.html', context)

    def budget_execution_print(self, request, year, month):
        """월간예산집행내역 출력용"""
        data = self._get_budget_execution_data(year, month)

        context = {
            'title': f'{year}년 {month}월 예산집행 내역',
            'year': year,
            'month': month,
            **data,
        }

        return TemplateResponse(request, 'admin/budget_execution_print.html', context)
