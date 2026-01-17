# finance/admin/simple.py
# 단순 ModelAdmin 클래스들

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

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
