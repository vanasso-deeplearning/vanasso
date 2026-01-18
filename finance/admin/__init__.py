# finance/admin/__init__.py
# Admin 통합 등록

from django.contrib import admin
from django.urls import path
from django.shortcuts import redirect
from datetime import date

from ..models import CashBook

# 단순 Admin 클래스 import
from .simple import (
    CustomUserAdmin,
    MemberAdmin,
    FixedAssetAdmin,
    CashBookCategoryAdmin,
    BankAccountAdmin,
    SettlementAdmin,
)

# AccountAdmin import
from .account import AccountAdmin

# TransactionAdmin import
from .transaction import TransactionAdmin

# Mixin import
from .cashbook import CashBookAdminMixin
from .report import ReportAdminMixin


@admin.register(CashBook)
class CashBookAdmin(CashBookAdminMixin, ReportAdminMixin, admin.ModelAdmin):
    """월간보고서 관리 (예금출납장, 현금출납장)"""
    list_display = ['year', 'month', 'book_type', 'entry_type', 'date', 'description', 'amount']
    list_filter = ['book_type', 'year', 'month']
    ordering = ['-year', '-month', 'book_type', 'entry_type', 'order']

    def _redirect_with_current_date(self, url_name):
        """현재 연월로 리다이렉트하는 헬퍼"""
        today = date.today()
        from django.urls import reverse
        return redirect(reverse(f'admin:{url_name}', args=[today.year, today.month]))

    def cashbook_combined_redirect(self, request):
        """예금/현금출납장 - 현재 연월로 리다이렉트"""
        return self._redirect_with_current_date('cashbook_combined')

    def deposit_ledger_redirect(self, request):
        """예수금출납장 - 현재 연월로 리다이렉트"""
        return self._redirect_with_current_date('deposit_ledger')

    def budget_execution_redirect(self, request):
        """월간 예산집행 내역 - 현재 연월로 리다이렉트"""
        return self._redirect_with_current_date('budget_execution')

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            # 월간보고서 메인 (기존 호환용)
            path('monthly-report/', self.admin_site.admin_view(self.monthly_report_main), name='monthly_report'),
            # 출납장 (파라미터 없는 URL 추가)
            path('cashbook-combined/', self.admin_site.admin_view(self.cashbook_combined_redirect), name='cashbook_combined_main'),
            path('cashbook-combined/<int:year>/<int:month>/', self.admin_site.admin_view(self.cashbook_combined_view), name='cashbook_combined'),
            path('cashbook/<str:book_type>/<int:year>/<int:month>/', self.admin_site.admin_view(self.cashbook_view), name='cashbook_view'),
            path('cashbook/save/', self.admin_site.admin_view(self.cashbook_save), name='cashbook_save'),
            path('cashbook-combined/save/', self.admin_site.admin_view(self.cashbook_combined_save), name='cashbook_combined_save'),
            path('cashbook/pdf/<str:book_type>/<int:year>/<int:month>/', self.admin_site.admin_view(self.cashbook_pdf), name='cashbook_pdf'),
            # 예수금출납장 (파라미터 없는 URL 추가)
            path('deposit-ledger/', self.admin_site.admin_view(self.deposit_ledger_redirect), name='deposit_ledger_main'),
            path('deposit-ledger/<int:year>/<int:month>/', self.admin_site.admin_view(self.deposit_ledger_view), name='deposit_ledger'),
            path('deposit-ledger/save/', self.admin_site.admin_view(self.deposit_ledger_save), name='deposit_ledger_save'),
            # 예산집행내역 (파라미터 없는 URL 추가)
            path('budget-execution/', self.admin_site.admin_view(self.budget_execution_redirect), name='budget_execution_main'),
            path('budget-execution/<int:year>/<int:month>/', self.admin_site.admin_view(self.budget_execution_view), name='budget_execution'),
            path('budget-execution/print/<int:year>/<int:month>/', self.admin_site.admin_view(self.budget_execution_print), name='budget_execution_print'),
            # 스냅샷 확정
            path('snapshot/confirm/cashbook/', self.admin_site.admin_view(self.snapshot_confirm_cashbook), name='snapshot_confirm_cashbook'),
            path('snapshot/confirm/budget/', self.admin_site.admin_view(self.snapshot_confirm_budget), name='snapshot_confirm_budget'),
            path('snapshot/cancel/<str:snapshot_type>/<int:year>/<int:month>/', self.admin_site.admin_view(self.snapshot_cancel), name='snapshot_cancel'),
            path('snapshot/confirm/card/', self.admin_site.admin_view(self.snapshot_confirm_card), name='snapshot_confirm_card'),
            # 월간보고서(확정)
            path('confirmed-report/', self.admin_site.admin_view(self.confirmed_report_main), name='confirmed_report'),
            path('confirmed-report/cashbook/<str:book_type>/<int:year>/<int:month>/', self.admin_site.admin_view(self.confirmed_cashbook_view), name='confirmed_cashbook'),
            path('confirmed-report/budget/<int:year>/<int:month>/', self.admin_site.admin_view(self.confirmed_budget_view), name='confirmed_budget'),
            path('confirmed-report/card/<int:year>/<int:month>/', self.admin_site.admin_view(self.confirmed_card_view), name='confirmed_card'),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        """기본 목록 대신 예금/현금출납장으로 리다이렉트"""
        return redirect('admin:cashbook_combined_main')
