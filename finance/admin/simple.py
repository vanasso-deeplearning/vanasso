# finance/admin/simple.py
# 단순 ModelAdmin 클래스들

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.urls import path
from django.shortcuts import redirect
from django.contrib import messages
from django.template.response import TemplateResponse

from ..models import Member, FixedAsset, CashBookCategory, BankAccount, Settlement


# 사용자 Admin 커스터마이징
admin.site.unregister(User)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """사용자 추가 시 스태프 권한을 바로 설정할 수 있도록"""
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2', 'is_staff', 'is_active'),
        }),
    )


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

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('main/', self.admin_site.admin_view(self.category_main_view), name='cashbook_category_main'),
            path('main/save/', self.admin_site.admin_view(self.category_save), name='cashbook_category_save'),
            path('main/delete/<int:pk>/', self.admin_site.admin_view(self.category_delete), name='cashbook_category_delete'),
            path('main/search/', self.admin_site.admin_view(self.category_search), name='cashbook_category_search'),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        """기본 목록 대신 커스텀 화면으로 리다이렉트"""
        return redirect('admin:cashbook_category_main')

    def category_main_view(self, request):
        """출납장과목 메인 화면"""
        from datetime import datetime

        book_type = request.GET.get('book_type', 'ALL')

        if book_type == 'ALL':
            income_categories = CashBookCategory.objects.filter(entry_type='INCOME').order_by('book_type', 'name')
            expense_categories = CashBookCategory.objects.filter(entry_type='EXPENSE').order_by('book_type', 'name')
        else:
            income_categories = CashBookCategory.objects.filter(book_type=book_type, entry_type='INCOME').order_by('name')
            expense_categories = CashBookCategory.objects.filter(book_type=book_type, entry_type='EXPENSE').order_by('name')

        # 조회용 데이터
        all_categories = CashBookCategory.objects.filter(is_active=True).order_by('book_type', 'entry_type', 'name')
        current_year = datetime.now().year
        years = list(range(current_year, current_year - 5, -1))
        months = list(range(1, 13))

        context = {
            **self.admin_site.each_context(request),
            'title': '출납장과목',
            'opts': self.model._meta,
            'book_type': book_type,
            'income_categories': income_categories,
            'expense_categories': expense_categories,
            'all_categories': all_categories,
            'years': years,
            'months': months,
            'current_year': current_year,
        }

        return TemplateResponse(request, 'admin/cashbook_category_main.html', context)

    def category_save(self, request):
        """출납장과목 저장"""
        if request.method != 'POST':
            return redirect('admin:cashbook_category_main')

        book_type = request.POST.get('current_book_type', 'ALL')
        saved_count = 0
        deleted_count = 0

        # 수입과목 처리
        idx = 0
        while True:
            cat_id = request.POST.get(f'income_id_{idx}')
            if cat_id is None:
                break

            name = request.POST.get(f'income_name_{idx}', '').strip()
            is_active = request.POST.get(f'income_active_{idx}') == 'on'
            is_deleted = request.POST.get(f'income_delete_{idx}') == '1'
            cat_book_type = request.POST.get(f'income_book_type_{idx}', 'BANK')

            if cat_id and is_deleted:
                CashBookCategory.objects.filter(pk=cat_id).delete()
                deleted_count += 1
            elif cat_id and name:
                CashBookCategory.objects.filter(pk=cat_id).update(name=name, is_active=is_active)
                saved_count += 1

            idx += 1

        # 새 수입과목
        new_income_name = request.POST.get('income_name_new', '').strip()
        new_income_book_type = request.POST.get('income_book_type_new', 'BANK')
        if new_income_name and new_income_book_type != 'ALL':
            CashBookCategory.objects.create(
                book_type=new_income_book_type,
                entry_type='INCOME',
                name=new_income_name,
                is_active=True
            )
            saved_count += 1

        # 지출과목 처리
        idx = 0
        while True:
            cat_id = request.POST.get(f'expense_id_{idx}')
            if cat_id is None:
                break

            name = request.POST.get(f'expense_name_{idx}', '').strip()
            is_active = request.POST.get(f'expense_active_{idx}') == 'on'
            is_deleted = request.POST.get(f'expense_delete_{idx}') == '1'
            cat_book_type = request.POST.get(f'expense_book_type_{idx}', 'BANK')

            if cat_id and is_deleted:
                CashBookCategory.objects.filter(pk=cat_id).delete()
                deleted_count += 1
            elif cat_id and name:
                CashBookCategory.objects.filter(pk=cat_id).update(name=name, is_active=is_active)
                saved_count += 1

            idx += 1

        # 새 지출과목
        new_expense_name = request.POST.get('expense_name_new', '').strip()
        new_expense_book_type = request.POST.get('expense_book_type_new', 'BANK')
        if new_expense_name and new_expense_book_type != 'ALL':
            CashBookCategory.objects.create(
                book_type=new_expense_book_type,
                entry_type='EXPENSE',
                name=new_expense_name,
                is_active=True
            )
            saved_count += 1

        msg = f'출납장과목 저장 완료 ({saved_count}건)'
        if deleted_count > 0:
            msg += f', 삭제 {deleted_count}건'
        messages.success(request, msg)

        return redirect(f"{request.path.replace('/save/', '')}?book_type={book_type}")

    def category_delete(self, request, pk):
        """출납장과목 삭제 (AJAX)"""
        from django.http import JsonResponse
        from ..models import CashBook, DepositLedger

        if request.method == 'POST':
            try:
                category = CashBookCategory.objects.get(pk=pk)

                # 사용 여부 확인
                cashbook_count = CashBook.objects.filter(category=category).count()
                deposit_count = DepositLedger.objects.filter(category=category).count()

                if cashbook_count > 0 or deposit_count > 0:
                    usage_details = []
                    if cashbook_count > 0:
                        usage_details.append(f'출납장 {cashbook_count}건')
                    if deposit_count > 0:
                        usage_details.append(f'예수금출납장 {deposit_count}건')
                    return JsonResponse({
                        'success': False,
                        'error': f'이 과목이 사용 중입니다 ({", ".join(usage_details)}). 삭제할 수 없습니다.'
                    }, status=400)

                category.delete()
                return JsonResponse({'success': True})
            except CashBookCategory.DoesNotExist:
                return JsonResponse({'success': False, 'error': '과목을 찾을 수 없습니다.'}, status=404)
        return JsonResponse({'success': False, 'error': 'POST 요청만 허용됩니다.'}, status=405)

    def category_search(self, request):
        """과목내역 조회 (AJAX)"""
        from django.http import JsonResponse
        from ..models import CashBook, DepositLedger

        book_type = request.GET.get('book_type')
        category_id = request.GET.get('category_id')
        year = request.GET.get('year')
        month = request.GET.get('month')

        if not book_type or not category_id or not year:
            return JsonResponse({'success': False, 'error': '필수 조건을 선택해주세요.'}, status=400)

        try:
            year = int(year)
            month = int(month) if month else None
        except ValueError:
            return JsonResponse({'success': False, 'error': '잘못된 값입니다.'}, status=400)

        results = []

        if book_type == 'DEPOSIT':
            # 예수금출납장
            queryset = DepositLedger.objects.filter(
                category_id=category_id,
                year=year
            )
            if month:
                queryset = queryset.filter(month=month)

            queryset = queryset.order_by('-date', '-order')

            for entry in queryset:
                results.append({
                    'date': entry.date.strftime('%Y-%m-%d'),
                    'description': entry.description or '',
                    'amount': int(entry.amount),
                    'note': entry.note or '',
                })
        else:
            # 예금/현금출납장
            queryset = CashBook.objects.filter(
                book_type=book_type,
                category_id=category_id,
                year=year
            )
            if month:
                queryset = queryset.filter(month=month)

            queryset = queryset.order_by('-date', '-order')

            for entry in queryset:
                results.append({
                    'date': entry.date.strftime('%Y-%m-%d'),
                    'description': entry.description or '',
                    'amount': int(entry.amount),
                    'note': entry.note or '',
                })

        total_amount = sum(item['amount'] for item in results)

        return JsonResponse({
            'success': True,
            'results': results,
            'total_count': len(results),
            'total_amount': total_amount,
        })


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ['bank_name', 'account_number', 'account_holder', 'order', 'is_active']
    list_editable = ['order', 'is_active']
    ordering = ['order']


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ['fiscal_year', 'closing_date', 'status', 'created_at']
    list_filter = ['status', 'fiscal_year']
    ordering = ['-fiscal_year']
