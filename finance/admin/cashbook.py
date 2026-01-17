# finance/admin/cashbook.py
# 출납장 관리 Admin (예금/현금/예수금출납장)

from django.contrib import admin
from django.urls import path
from django.shortcuts import redirect
from django.contrib import messages
from django.db import transaction
from django.template.response import TemplateResponse
from django.http import HttpResponse
from django.db.models import Sum
from decimal import Decimal

from ..models import Account, Transaction, CashBook, CashBookCategory, BankAccount, DepositLedger, MonthlySnapshot


class CashBookAdminMixin:
    """출납장 관련 메서드 Mixin"""

    def monthly_report_main(self, request):
        """월간보고서 메인 화면"""
        from datetime import datetime
        current_month = datetime.now().month

        default_year = 2025
        selected_year = int(request.GET.get('year', default_year))
        selected_month = int(request.GET.get('month', current_month))

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

    def cashbook_combined_view(self, request, year, month):
        """예금/현금출납장 통합 화면"""
        from calendar import monthrange

        _, last_day = monthrange(year, month)

        def get_cashbook_data(book_type):
            income_categories = CashBookCategory.objects.filter(
                book_type=book_type, entry_type='INCOME', is_active=True
            ).order_by('name')

            expense_accounts = list(Account.objects.filter(
                fiscal_year=year,
                account_type__in=['EXPENSE', 'LIABILITY', 'EQUITY'],
                is_active=True
            ).order_by('code'))

            if not expense_accounts:
                latest_year = Account.objects.filter(account_type__in=['EXPENSE', 'LIABILITY', 'EQUITY']).order_by('-fiscal_year').values_list('fiscal_year', flat=True).first()
                if latest_year:
                    expense_accounts = list(Account.objects.filter(
                        fiscal_year=latest_year,
                        account_type__in=['EXPENSE', 'LIABILITY', 'EQUITY'],
                        is_active=True
                    ).order_by('code'))

            expense_categories = list(CashBookCategory.objects.filter(
                book_type=book_type, entry_type='EXPENSE', is_active=True
            ).order_by('name'))

            expense_items = []
            for acc in expense_accounts:
                expense_items.append({'value': f"account:{acc.id}", 'display_name': acc.account_name})
            for cat in expense_categories:
                expense_items.append({'value': f"category:{cat.id}", 'display_name': cat.name})

            income_entries = list(CashBook.objects.filter(
                book_type=book_type, year=year, month=month, entry_type='INCOME'
            ).order_by('order').values('id', 'date', 'category_id', 'description', 'amount', 'bank_account_id', 'note', 'order'))

            expense_entries_raw = list(CashBook.objects.filter(
                book_type=book_type, year=year, month=month, entry_type='EXPENSE'
            ).order_by('order').values('id', 'date', 'account_id', 'category_id', 'description', 'amount', 'bank_account_id', 'note', 'order'))

            expense_entries = []
            for entry in expense_entries_raw:
                if entry['account_id']:
                    entry['selected_value'] = f"account:{entry['account_id']}"
                elif entry['category_id']:
                    entry['selected_value'] = f"category:{entry['category_id']}"
                else:
                    entry['selected_value'] = ''
                expense_entries.append(entry)

            income_row_count = 20 if book_type == 'BANK' else 5
            while len(income_entries) < income_row_count:
                income_entries.append({'id': None, 'date': None, 'category_id': None, 'description': '', 'amount': 0, 'bank_account_id': None, 'note': '', 'order': len(income_entries)})
            while len(expense_entries) < 20:
                expense_entries.append({'id': None, 'date': None, 'account_id': None, 'category_id': None, 'selected_value': '', 'description': '', 'amount': 0, 'bank_account_id': None, 'note': '', 'order': len(expense_entries)})

            income_total = sum(e['amount'] for e in income_entries if e['amount'])
            expense_total = sum(e['amount'] for e in expense_entries if e['amount'])

            return {
                'income_categories': income_categories,
                'expense_items': expense_items,
                'income_entries': income_entries,
                'expense_entries': expense_entries,
                'income_total': income_total,
                'expense_total': expense_total,
            }

        bank_data = get_cashbook_data('BANK')
        cash_data = get_cashbook_data('CASH')

        year_range = list(range(2024, 2028))
        month_range = list(range(1, 13))

        bank_snapshot = MonthlySnapshot.objects.filter(
            snapshot_type='CASHBOOK_BANK', fiscal_year=year, month=month
        ).first()
        cash_snapshot = MonthlySnapshot.objects.filter(
            snapshot_type='CASHBOOK_CASH', fiscal_year=year, month=month
        ).first()
        bank_is_confirmed = bank_snapshot is not None
        cash_is_confirmed = cash_snapshot is not None
        bank_confirmed_at = bank_snapshot.confirmed_at if bank_snapshot else None
        cash_confirmed_at = cash_snapshot.confirmed_at if cash_snapshot else None

        context = {
            **self.admin_site.each_context(request),
            'title': f'예금/현금출납장 ({year}. {month}월)',
            'opts': self.model._meta,
            'year': year,
            'month': month,
            'last_day': last_day,
            'year_range': year_range,
            'month_range': month_range,
            'bank_income_categories': bank_data['income_categories'],
            'bank_expense_items': bank_data['expense_items'],
            'bank_income_entries': bank_data['income_entries'],
            'bank_expense_entries': bank_data['expense_entries'],
            'bank_income_total': bank_data['income_total'],
            'bank_expense_total': bank_data['expense_total'],
            'cash_income_categories': cash_data['income_categories'],
            'cash_expense_items': cash_data['expense_items'],
            'cash_income_entries': cash_data['income_entries'],
            'cash_expense_entries': cash_data['expense_entries'],
            'cash_income_total': cash_data['income_total'],
            'cash_expense_total': cash_data['expense_total'],
            'bank_is_confirmed': bank_is_confirmed,
            'bank_confirmed_at': bank_confirmed_at,
            'cash_is_confirmed': cash_is_confirmed,
            'cash_confirmed_at': cash_confirmed_at,
        }

        return TemplateResponse(request, 'admin/cashbook_combined.html', context)

    def cashbook_view(self, request, book_type, year, month):
        """출납장 조회/편집 화면"""
        from calendar import monthrange

        _, last_day = monthrange(year, month)

        bank_accounts = BankAccount.objects.filter(is_active=True).order_by('order') if book_type == 'BANK' else []

        income_categories = CashBookCategory.objects.filter(
            book_type=book_type, entry_type='INCOME', is_active=True
        ).order_by('name')

        expense_accounts = list(Account.objects.filter(
            fiscal_year=year,
            account_type__in=['EXPENSE', 'LIABILITY', 'EQUITY'],
            is_active=True
        ).order_by('code'))

        if not expense_accounts:
            latest_year = Account.objects.filter(account_type__in=['EXPENSE', 'LIABILITY', 'EQUITY']).order_by('-fiscal_year').values_list('fiscal_year', flat=True).first()
            if latest_year:
                expense_accounts = list(Account.objects.filter(
                    fiscal_year=latest_year,
                    account_type__in=['EXPENSE', 'LIABILITY', 'EQUITY'],
                    is_active=True
                ).order_by('code'))

        expense_categories = list(CashBookCategory.objects.filter(
            book_type=book_type, entry_type='EXPENSE', is_active=True
        ).order_by('name'))

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

        income_entries = list(CashBook.objects.filter(
            book_type=book_type, year=year, month=month, entry_type='INCOME'
        ).order_by('order').values(
            'id', 'date', 'category_id', 'description', 'amount', 'bank_account_id', 'note', 'order'
        ))

        expense_entries_raw = list(CashBook.objects.filter(
            book_type=book_type, year=year, month=month, entry_type='EXPENSE'
        ).order_by('order').values(
            'id', 'date', 'account_id', 'category_id', 'description', 'amount', 'bank_account_id', 'note', 'order'
        ))

        expense_entries = []
        for entry in expense_entries_raw:
            if entry['account_id']:
                entry['selected_value'] = f"account:{entry['account_id']}"
            elif entry['category_id']:
                entry['selected_value'] = f"category:{entry['category_id']}"
            else:
                entry['selected_value'] = ''
            expense_entries.append(entry)

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

        income_total = sum(e['amount'] for e in income_entries if e['amount'])
        expense_total = sum(e['amount'] for e in expense_entries if e['amount'])

        book_type_display = '예금출납장' if book_type == 'BANK' else '현금출납장'

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

        old_cashbooks = CashBook.objects.filter(book_type=book_type, year=year, month=month)
        linked_transaction_ids = list(old_cashbooks.exclude(
            linked_transaction__isnull=True
        ).values_list('linked_transaction_id', flat=True))
        old_cashbooks.delete()
        if linked_transaction_ids:
            Transaction.objects.filter(id__in=linked_transaction_ids).delete()

        saved_count = 0

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

        return redirect('admin:cashbook_combined', year=year, month=month)

    def cashbook_combined_save(self, request):
        """예금/현금출납장 통합 저장"""
        if request.method != 'POST':
            return redirect('admin:monthly_report')

        year = int(request.POST.get('year'))
        month = int(request.POST.get('month'))

        total_saved = 0
        total_transactions = 0

        for book_type, prefix in [('BANK', 'bank'), ('CASH', 'cash')]:
            old_cashbooks = CashBook.objects.filter(book_type=book_type, year=year, month=month)
            linked_transaction_ids = list(old_cashbooks.exclude(
                linked_transaction__isnull=True
            ).values_list('linked_transaction_id', flat=True))
            old_cashbooks.delete()
            if linked_transaction_ids:
                Transaction.objects.filter(id__in=linked_transaction_ids).delete()

            saved_count = 0

            idx = 0
            while True:
                day = request.POST.get(f'{prefix}_income_day_{idx}')
                if day is None:
                    break

                category_id = request.POST.get(f'{prefix}_income_category_{idx}', '').strip()
                amount_str = request.POST.get(f'{prefix}_income_amount_{idx}', '0').replace(',', '')
                note = request.POST.get(f'{prefix}_income_note_{idx}', '').strip()

                if day and category_id:
                    try:
                        from datetime import date
                        entry_date = date(year, month, int(day))
                        amount = Decimal(amount_str) if amount_str else Decimal('0')

                        category = CashBookCategory.objects.get(pk=category_id)

                        CashBook.objects.create(
                            book_type=book_type,
                            year=year,
                            month=month,
                            entry_type='INCOME',
                            date=entry_date,
                            category=category,
                            amount=amount,
                            note=note,
                            order=saved_count,
                        )
                        saved_count += 1
                    except Exception as e:
                        pass

                idx += 1

            idx = 0
            transaction_saved = 0
            while True:
                day = request.POST.get(f'{prefix}_expense_day_{idx}')
                if day is None:
                    break

                item_value = request.POST.get(f'{prefix}_expense_item_{idx}', '').strip()
                amount_str = request.POST.get(f'{prefix}_expense_amount_{idx}', '0').replace(',', '')
                note = request.POST.get(f'{prefix}_expense_note_{idx}', '').strip()

                if day and item_value:
                    try:
                        from datetime import date
                        entry_date = date(year, month, int(day))
                        amount = Decimal(amount_str) if amount_str else Decimal('0')

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

                        linked_trans = None
                        if account and amount > 0:
                            payment_method = 'BANK' if book_type == 'BANK' else 'CASH'
                            linked_trans = Transaction.objects.create(
                                date=entry_date,
                                transaction_type='EXPENSE',
                                account=account,
                                description=display_name + (f' ({note})' if note else ''),
                                amount=amount,
                                payment_method=payment_method,
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

            total_saved += saved_count
            total_transactions += transaction_saved

        msg = f'{year}년 {month}월 예금/현금출납장 저장 완료 ({total_saved}건)'
        if total_transactions > 0:
            msg += f' - 거래내역 {total_transactions}건 동시 저장'
        messages.success(request, msg)

        return redirect('admin:cashbook_combined', year=year, month=month)

    def cashbook_pdf(self, request, book_type, year, month):
        """출납장 PDF 출력"""
        income_entries = CashBook.objects.filter(
            book_type=book_type, year=year, month=month, entry_type='INCOME'
        ).select_related('category', 'bank_account', 'account').order_by('order')

        expense_entries = CashBook.objects.filter(
            book_type=book_type, year=year, month=month, entry_type='EXPENSE'
        ).select_related('category', 'bank_account', 'account').order_by('order')

        income_total = sum(e.amount for e in income_entries)
        expense_total = sum(e.amount for e in expense_entries)

        book_type_display = '예금출납장' if book_type == 'BANK' else '현금출납장'

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

    def deposit_ledger_view(self, request, year, month):
        """예수금출납장 조회/편집 화면"""
        from calendar import monthrange

        _, last_day = monthrange(year, month)

        expense_categories = list(CashBookCategory.objects.filter(
            book_type='DEPOSIT', entry_type='EXPENSE', is_active=True
        ).order_by('name'))

        expense_entries = list(DepositLedger.objects.filter(
            year=year, month=month
        ).order_by('order').values(
            'id', 'date', 'category_id', 'description', 'amount', 'note', 'order'
        ))

        while len(expense_entries) < 5:
            expense_entries.append({
                'id': None, 'date': None, 'category_id': None, 'description': '',
                'amount': 0, 'note': '', 'order': len(expense_entries)
            })

        expense_total = sum(e['amount'] for e in expense_entries if e['amount'])

        year_range = list(range(2024, 2028))
        month_range = list(range(1, 13))

        context = {
            **self.admin_site.each_context(request),
            'title': f'예수금출납장(월간보고용) ({year}. {month}월)',
            'opts': self.model._meta,
            'year': year,
            'month': month,
            'expense_categories': expense_categories,
            'expense_entries': expense_entries,
            'expense_total': expense_total,
            'last_day': last_day,
            'year_range': year_range,
            'month_range': month_range,
        }

        return TemplateResponse(request, 'admin/deposit_ledger_form.html', context)

    def deposit_ledger_save(self, request):
        """예수금출납장 저장"""
        if request.method != 'POST':
            return redirect('admin:monthly_report')

        year = int(request.POST.get('year'))
        month = int(request.POST.get('month'))

        DepositLedger.objects.filter(year=year, month=month).delete()

        saved_count = 0

        idx = 0
        while True:
            day = request.POST.get(f'expense_day_{idx}')
            if day is None:
                break

            category_id = request.POST.get(f'expense_category_{idx}', '').strip()
            amount_str = request.POST.get(f'expense_amount_{idx}', '0').replace(',', '')
            note = request.POST.get(f'expense_note_{idx}', '').strip()

            if day and category_id:
                try:
                    from datetime import date
                    entry_date = date(year, month, int(day))
                    amount = Decimal(amount_str) if amount_str else Decimal('0')

                    category = CashBookCategory.objects.get(pk=category_id)

                    DepositLedger.objects.create(
                        year=year,
                        month=month,
                        date=entry_date,
                        category=category,
                        description=category.name,
                        amount=amount,
                        note=note,
                        order=saved_count,
                    )
                    saved_count += 1
                except Exception as e:
                    pass

            idx += 1

        messages.success(request, f'{year}년 {month}월 예수금출납장(월간보고용) 저장 완료 ({saved_count}건)')

        return redirect('admin:deposit_ledger', year=year, month=month)
