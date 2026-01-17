# finance/admin/account.py
# 계정과목 및 예산 관리 Admin

from django.contrib import admin
from django.urls import path, reverse
from django.shortcuts import redirect
from django.contrib import messages
from django.db import transaction
from django.template.response import TemplateResponse
from decimal import Decimal
import pandas as pd

from ..models import Account, Budget, Transaction


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

    def save_model(self, request, obj, form, change):
        """계정코드 자동 생성 (비어있을 경우)"""
        if not obj.code:
            type_prefix = {
                'ASSET': 'A', 'LIABILITY': 'L', 'EQUITY': 'E',
                'INCOME': 'I', 'EXPENSE': 'X'
            }
            prefix = type_prefix.get(obj.account_type, 'Z')

            existing_codes = Account.objects.filter(
                fiscal_year=obj.fiscal_year,
                code__startswith=prefix
            ).values_list('code', flat=True)

            max_num = 0
            for code in existing_codes:
                try:
                    num = int(code[1:])
                    if num > max_num:
                        max_num = num
                except (ValueError, IndexError):
                    pass

            obj.code = f"{prefix}{max_num + 1:03d}"

        super().save_model(request, obj, form, change)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('main/', self.admin_site.admin_view(self.account_main_view), name='account_main'),
            path('upload/', self.admin_site.admin_view(self.upload_account), name='account_upload'),
            path('budget-edit/', self.admin_site.admin_view(self.budget_edit_view), name='budget_edit'),
            path('budget-edit/save/', self.admin_site.admin_view(self.budget_edit_save), name='budget_edit_save'),
        ]
        return custom_urls + urls

    def account_main_view(self, request):
        """계정과목등록(예산입력) 통합 메뉴"""
        from datetime import datetime
        current_year = datetime.now().year

        selected_year = request.GET.get('year', current_year)
        try:
            selected_year = int(selected_year)
        except:
            selected_year = current_year

        years = list(range(current_year + 2, current_year - 3, -1))

        account_count = Account.objects.filter(fiscal_year=selected_year).count()
        budget_count = Budget.objects.filter(fiscal_year=selected_year).count()

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
        existing_budgets = Budget.objects.filter(fiscal_year=fiscal_year).count()
        if existing_budgets > 0:
            messages.error(request, f'{fiscal_year}년 예산이 이미 존재합니다. 기존 데이터를 삭제 후 업로드해주세요.')
            return redirect(f"{request.path}?year={fiscal_year}")

        try:
            df = pd.read_excel(excel_file)
        except Exception as e:
            messages.error(request, f'엑셀 파일 읽기 오류: {e}')
            return redirect(f"{request.path}?year={fiscal_year}")

        accounts = []
        budgets = {}
        created_account_names = set()
        code_counters = {'인건비': 0, '사업비': 0}

        for _, row in df.iterrows():
            category_large = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
            category_medium = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ''
            category_small = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else ''
            account_name = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else ''

            try:
                amount = Decimal(str(row.iloc[5])) if pd.notna(row.iloc[5]) else Decimal('0')
            except:
                amount = Decimal('0')

            if not category_large or category_large == 'nan' or category_large == '구분(대분류)':
                continue

            if account_name not in budgets:
                budgets[account_name] = amount
            else:
                budgets[account_name] += amount

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
        """연도별 데이터 삭제"""
        year_accounts = Account.objects.filter(fiscal_year=fiscal_year)
        transaction_count = Transaction.objects.filter(account__in=year_accounts).count()

        if transaction_count > 0:
            confirm = request.POST.get('confirm_delete_all')
            if confirm != 'yes':
                messages.warning(
                    request,
                    f'{fiscal_year}년 계정과목에 연결된 거래내역 {transaction_count}건이 있습니다. '
                    f'거래내역도 함께 삭제하려면 다시 삭제 버튼을 클릭하세요.'
                )
                request.session['pending_delete_year'] = fiscal_year
                return redirect(f"{request.path}?year={fiscal_year}&confirm_needed=1")

        with transaction.atomic():
            trans_deleted, _ = Transaction.objects.filter(account__in=year_accounts).delete()
            budget_count, _ = Budget.objects.filter(fiscal_year=fiscal_year).delete()
            account_count, _ = Account.objects.filter(fiscal_year=fiscal_year).delete()

        if 'pending_delete_year' in request.session:
            del request.session['pending_delete_year']

        msg = f'{fiscal_year}년 데이터 삭제 완료: 계정과목 {account_count}건, 예산 {budget_count}건'
        if trans_deleted > 0:
            msg += f', 거래내역 {trans_deleted}건'
        messages.success(request, msg)
        return redirect(f"{request.path}?year={fiscal_year}")

    def budget_edit_view(self, request):
        """예산 일괄 수정/편집 화면"""
        from datetime import datetime

        year = request.GET.get('year', datetime.now().year)
        try:
            year = int(year)
        except:
            year = datetime.now().year

        year_range = list(range(2024, 2028))
        budgets = Budget.objects.filter(fiscal_year=year).select_related('account').order_by('account__code')
        total_budget = sum(b.annual_amount for b in budgets)

        context = {
            **self.admin_site.each_context(request),
            'title': f'{year}년 예산 일괄 수정/편집',
            'opts': self.model._meta,
            'year': year,
            'year_range': year_range,
            'budgets': budgets,
            'total_budget': total_budget,
        }

        return TemplateResponse(request, 'admin/budget_edit.html', context)

    def budget_edit_save(self, request):
        """예산 일괄 저장"""
        if request.method != 'POST':
            return redirect('admin:budget_edit')

        year = int(request.POST.get('year', 0))
        total_count = int(request.POST.get('total_count', 0))

        updated_count = 0
        for i in range(total_count):
            budget_id = request.POST.get(f'budget_id_{i}')
            account_name = request.POST.get(f'account_name_{i}', '').strip()
            amount_str = request.POST.get(f'amount_{i}', '0').replace(',', '')

            if budget_id:
                try:
                    budget = Budget.objects.get(pk=budget_id)
                    amount = Decimal(amount_str) if amount_str else Decimal('0')

                    if budget.annual_amount != amount:
                        budget.annual_amount = amount
                        budget.save()
                        updated_count += 1

                    if budget.account.account_name != account_name:
                        budget.account.account_name = account_name
                        budget.account.save()
                        updated_count += 1

                except (Budget.DoesNotExist, ValueError):
                    pass

        messages.success(request, f'{year}년 예산 저장 완료 ({updated_count}건 수정)')
        return redirect(f"{reverse('admin:budget_edit')}?year={year}")

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
