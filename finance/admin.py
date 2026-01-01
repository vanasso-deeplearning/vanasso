from django.contrib import admin
from .models import Account, Member, Budget, FixedAsset, Transaction, Settlement


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ['code', 'category_large', 'category_small', 'account_type', 'is_active']
    list_filter = ['account_type', 'is_active', 'category_large']
    search_fields = ['code', 'category_small']
    ordering = ['code']


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ['name', 'partner_type', 'business_number', 'contact_person', 'is_active']
    list_filter = ['partner_type', 'is_active']
    search_fields = ['name', 'business_number']
    ordering = ['name']


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ['fiscal_year', 'account', 'annual_amount', 'supplementary_amount', 'get_total_budget']
    list_filter = ['fiscal_year']
    search_fields = ['account__category_small']
    ordering = ['fiscal_year', 'account__code']

    @admin.display(description='총 예산액')
    def get_total_budget(self, obj):
        return f"₩{obj.total_budget:,.0f}"


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
    search_fields = ['description', 'account__category_small']
    date_hierarchy = 'date'
    ordering = ['-date', '-created_at']


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ['fiscal_year', 'closing_date', 'status', 'created_at']
    list_filter = ['status', 'fiscal_year']
    ordering = ['-fiscal_year']
