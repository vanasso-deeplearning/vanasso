from django.contrib import admin
from django.urls import path
from django.shortcuts import redirect
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.template.response import TemplateResponse
from decimal import Decimal
import pandas as pd
import json

from .models import Account, Member, Budget, FixedAsset, Transaction, Settlement


# 4대보험 구성 항목 (합산 대상)
INSURANCE_ITEMS = ['국민연금', '건강보험', '고용보험', '산재보험']

# 계정코드 자동 생성용 카운터
ACCOUNT_CODE_PREFIX = {
    '인건비': '1',
    '사업비': '2',
}


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ['fiscal_year', 'code', 'account_type', 'category_large', 'category_medium', 'category_small', 'account_name', 'account_name2', 'is_active']
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
        """예산 업로드 처리"""
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

        # BudgetAdmin의 parse_budget_template 로직 재사용
        accounts = []
        budgets = {}
        insurance_total = Decimal('0')
        insurance_account_info = None
        code_counters = {'인건비': 0, '사업비': 0}

        for _, row in df.iterrows():
            category_large = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
            category_medium = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ''
            category_small = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else ''
            account_name = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else ''
            account_name2 = str(row.iloc[4]).strip() if pd.notna(row.iloc[4]) and str(row.iloc[4]) != 'nan' else ''

            try:
                amount = Decimal(str(row.iloc[5])) if pd.notna(row.iloc[5]) else Decimal('0')
            except:
                amount = Decimal('0')

            if not category_large or category_large == 'nan' or category_large == '구분(대분류)':
                continue

            if account_name2 and account_name2 in INSURANCE_ITEMS:
                insurance_total += amount
                if insurance_account_info is None:
                    insurance_account_info = {'account_name': account_name}
                code_counters[category_large] = code_counters.get(category_large, 0) + 1
                code = f"{ACCOUNT_CODE_PREFIX.get(category_large, '9')}{code_counters[category_large]:03d}"
                accounts.append({
                    'fiscal_year': fiscal_year, 'code': code,
                    'category_large': category_large, 'category_medium': category_medium,
                    'category_small': category_small, 'account_name': account_name,
                    'account_name2': account_name2, 'account_type': 'EXPENSE',
                })
                continue

            code_counters[category_large] = code_counters.get(category_large, 0) + 1
            code = f"{ACCOUNT_CODE_PREFIX.get(category_large, '9')}{code_counters[category_large]:03d}"
            accounts.append({
                'fiscal_year': fiscal_year, 'code': code,
                'category_large': category_large, 'category_medium': category_medium,
                'category_small': category_small, 'account_name': account_name,
                'account_name2': '', 'account_type': 'EXPENSE',
            })
            if account_name not in budgets:
                budgets[account_name] = amount
            else:
                budgets[account_name] += amount

        if insurance_total > 0 and insurance_account_info:
            budgets[insurance_account_info['account_name']] = insurance_total

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
                        fiscal_year=fiscal_year, account_name=account_name, account_name2=''
                    ).first() or Account.objects.filter(
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
                account_name2 = str(row.get('계정명2', '')).strip() if pd.notna(row.get('계정명2')) else ''

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
                    category_small=category_small, account_name=account_name, account_name2=account_name2,
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
                    account_name2 = str(row.get('계정명2', '')).strip() if pd.notna(row.get('계정명2')) else ''

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
                        account_name2=account_name2,
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


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    change_list_template = 'admin/budget_changelist.html'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        """예산 메인 페이지 - 연도별 조회 및 엑셀 업로드"""
        # POST 요청 처리 (조회/삭제)
        if request.method == 'POST':
            action = request.POST.get('action')
            fiscal_year = request.POST.get('view_year')

            if fiscal_year:
                if action == 'view':
                    return redirect('admin:budget_view', fiscal_year=fiscal_year)
                elif action == 'delete':
                    with transaction.atomic():
                        budget_count, _ = Budget.objects.filter(fiscal_year=fiscal_year).delete()
                        account_count, _ = Account.objects.filter(fiscal_year=fiscal_year).delete()
                    messages.success(request, f'{fiscal_year}년 데이터 삭제 완료: 예산 {budget_count}건, 계정과목 {account_count}건')
                    return redirect('admin:finance_budget_changelist')

        # 등록된 연도 목록 조회
        available_years = Budget.objects.values_list('fiscal_year', flat=True).distinct().order_by('-fiscal_year')

        context = {
            **self.admin_site.each_context(request),
            'title': '예산 관리',
            'available_years': available_years,
            'opts': self.model._meta,
        }

        return TemplateResponse(request, 'admin/budget_changelist.html', context)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('upload/', self.admin_site.admin_view(self.upload_budget), name='budget_upload'),
            path('view/<int:fiscal_year>/', self.admin_site.admin_view(self.view_budget), name='budget_view'),
        ]
        return custom_urls + urls

    def parse_budget_template(self, df, fiscal_year):
        """
        burget_account_template.xlsx 형식 파싱
        컬럼: 구분(대분류), 구분(중분류), 구분(소분류), 계정명, 계정명2, 연간예산액

        Returns:
            accounts: 생성할 Account 목록 (4대보험은 합산된 하나의 계정)
            budgets: 생성할 Budget 목록 (account_name을 키로 사용)
        """
        accounts = []
        budgets = {}  # account_name -> amount
        insurance_total = Decimal('0')
        insurance_account_info = None  # 4대보험 계정 정보 저장용

        code_counters = {'인건비': 0, '사업비': 0}

        for _, row in df.iterrows():
            # 컬럼 매핑
            category_large = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
            category_medium = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ''
            category_small = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else ''
            account_name = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else ''
            account_name2 = str(row.iloc[4]).strip() if pd.notna(row.iloc[4]) and str(row.iloc[4]) != 'nan' else ''

            # 연간예산액 (있으면)
            try:
                amount = Decimal(str(row.iloc[5])) if pd.notna(row.iloc[5]) else Decimal('0')
            except:
                amount = Decimal('0')

            # 유효성 검사
            if not category_large or category_large == 'nan' or category_large == '구분(대분류)':
                continue

            # 4대보험 세부 항목 (계정명2가 있는 경우)
            if account_name2 and account_name2 in INSURANCE_ITEMS:
                insurance_total += amount
                if insurance_account_info is None:
                    insurance_account_info = {
                        'category_large': category_large,
                        'category_medium': category_medium,
                        'category_small': category_small,
                        'account_name': account_name,  # '4대보험'
                    }
                # 4대보험 세부 항목도 Account로 저장 (account_name2 포함)
                code_counters[category_large] = code_counters.get(category_large, 0) + 1
                code = f"{ACCOUNT_CODE_PREFIX.get(category_large, '9')}{code_counters[category_large]:03d}"
                accounts.append({
                    'fiscal_year': fiscal_year,
                    'code': code,
                    'category_large': category_large,
                    'category_medium': category_medium,
                    'category_small': category_small,
                    'account_name': account_name,
                    'account_name2': account_name2,
                    'account_type': 'EXPENSE',
                })
                continue

            # 일반 계정
            code_counters[category_large] = code_counters.get(category_large, 0) + 1
            code = f"{ACCOUNT_CODE_PREFIX.get(category_large, '9')}{code_counters[category_large]:03d}"

            accounts.append({
                'fiscal_year': fiscal_year,
                'code': code,
                'category_large': category_large,
                'category_medium': category_medium,
                'category_small': category_small,
                'account_name': account_name,
                'account_name2': '',
                'account_type': 'EXPENSE',
            })

            # 예산 금액 저장 (계정명 기준)
            if account_name not in budgets:
                budgets[account_name] = amount
            else:
                budgets[account_name] += amount

        # 4대보험 합산 예산 추가
        if insurance_total > 0 and insurance_account_info:
            budgets[insurance_account_info['account_name']] = insurance_total

        return accounts, budgets

    def upload_budget(self, request):
        """예산 엑셀 업로드 처리 - Account와 Budget을 함께 생성"""
        context = {
            **self.admin_site.each_context(request),
            'title': '예산 엑셀 업로드',
            'opts': self.model._meta,
        }

        if request.method == 'POST':
            excel_file = request.FILES.get('excel_file')
            fiscal_year = request.POST.get('fiscal_year')

            if not excel_file or not fiscal_year:
                messages.error(request, '파일과 회계연도를 모두 입력해주세요.')
                return TemplateResponse(request, 'admin/budget_upload.html', context)

            try:
                fiscal_year = int(fiscal_year)
            except ValueError:
                messages.error(request, '회계연도는 숫자로 입력해주세요.')
                return TemplateResponse(request, 'admin/budget_upload.html', context)

            # 해당 연도 데이터 존재 여부 확인
            existing_accounts = Account.objects.filter(fiscal_year=fiscal_year).count()
            existing_budgets = Budget.objects.filter(fiscal_year=fiscal_year).count()
            if existing_accounts > 0 or existing_budgets > 0:
                context['fiscal_year'] = fiscal_year
                context['existing_data'] = True
                context['existing_accounts'] = existing_accounts
                context['existing_budgets'] = existing_budgets
                messages.warning(request, f'{fiscal_year}년 데이터가 이미 존재합니다. 기존 데이터를 삭제 후 업로드하거나 다른 연도를 선택해주세요.')
                return TemplateResponse(request, 'admin/budget_upload.html', context)

            # 엑셀 파일 읽기
            try:
                df = pd.read_excel(excel_file)
            except Exception as e:
                messages.error(request, f'엑셀 파일 읽기 오류: {e}')
                return TemplateResponse(request, 'admin/budget_upload.html', context)

            # burget_account_template.xlsx 형식 파싱
            accounts_data, budgets_data = self.parse_budget_template(df, fiscal_year)

            if not accounts_data:
                messages.error(request, '계정 데이터를 찾을 수 없습니다. 파일 형식을 확인해주세요.')
                return TemplateResponse(request, 'admin/budget_upload.html', context)

            # Account 및 Budget 등록
            with transaction.atomic():
                account_count = 0
                budget_count = 0

                # Account 생성
                for acc_data in accounts_data:
                    Account.objects.create(**acc_data)
                    account_count += 1

                # Budget 생성 (account_name 기준으로 Account 찾기, 4대보험은 account_name2가 없는 것 사용)
                for account_name, amount in budgets_data.items():
                    if amount > 0:
                        # 4대보험의 경우 account_name2가 비어있는 행이 없으므로 첫 번째 것 사용
                        account = Account.objects.filter(
                            fiscal_year=fiscal_year,
                            account_name=account_name,
                            account_name2=''
                        ).first()

                        # account_name2가 있는 경우 (4대보험 세부항목)는 첫 번째 것 사용
                        if not account:
                            account = Account.objects.filter(
                                fiscal_year=fiscal_year,
                                account_name=account_name
                            ).first()

                        if account:
                            Budget.objects.create(
                                fiscal_year=fiscal_year,
                                account=account,
                                annual_amount=amount,
                                supplementary_amount=Decimal('0'),
                            )
                            budget_count += 1

            messages.success(request, f'{fiscal_year}년 업로드 완료: 계정과목 {account_count}건, 예산 {budget_count}건')
            return redirect('admin:budget_view', fiscal_year=fiscal_year)

        return TemplateResponse(request, 'admin/budget_upload.html', context)

    def view_budget(self, request, fiscal_year):
        """예산 조회 (2026년 예산.xls 형식)"""
        budgets = Budget.objects.filter(fiscal_year=fiscal_year).select_related('account').order_by('account__code')

        # 대분류별 그룹화
        grouped_budgets = {}
        for budget in budgets:
            category = budget.account.category_large
            if category not in grouped_budgets:
                grouped_budgets[category] = {
                    'items': [],
                    'subtotal': Decimal('0'),
                }
            grouped_budgets[category]['items'].append(budget)
            grouped_budgets[category]['subtotal'] += budget.annual_amount

        # 총합계
        total = budgets.aggregate(total=Sum('annual_amount'))['total'] or 0

        context = {
            **self.admin_site.each_context(request),
            'title': f'{fiscal_year}년 예산',
            'fiscal_year': fiscal_year,
            'grouped_budgets': grouped_budgets,
            'total': total,
            'opts': self.model._meta,
        }
        return TemplateResponse(request, 'admin/budget_view.html', context)


@admin.register(FixedAsset)
class FixedAssetAdmin(admin.ModelAdmin):
    list_display = ['name', 'acquisition_date', 'acquisition_cost', 'useful_life', 'current_value', 'is_active']
    list_filter = ['is_active', 'depreciation_method']
    search_fields = ['name']
    ordering = ['-acquisition_date']


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
            if acc.account_name2:
                display_name += f" ({acc.account_name2})"
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
