# finance/admin/report.py
# 월간보고서 및 스냅샷 관련 Admin

from django.shortcuts import redirect
from django.contrib import messages
from django.template.response import TemplateResponse
from django.http import JsonResponse
from django.db.models import Sum
from decimal import Decimal
from collections import OrderedDict

from ..models import (
    Budget, Transaction, CashBook, MonthlySnapshot, DepositLedger
)


class ReportAdminMixin:
    """월간보고서 및 스냅샷 관련 Mixin"""

    def _get_budget_execution_data(self, year, month):
        """월간예산집행내역 데이터 조회 (공통 로직)"""
        from datetime import date

        budgets = Budget.objects.filter(fiscal_year=year).select_related('account').order_by('account__code')

        year_start = date(year, 1, 1)
        month_start = date(year, month, 1)
        if month == 12:
            next_month_start = date(year + 1, 1, 1)
        else:
            next_month_start = date(year, month + 1, 1)

        # 예수금출납장에서 '예수금(4대보험)', '예수금(원천세)' 합계 조회 (급여 항목에 합산용)
        # 당월 예수금 합계
        deposit_monthly = DepositLedger.objects.filter(
            year=year, month=month,
            category__name__in=['예수금(4대보험)', '예수금(원천세)']
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        # 누계 예수금 합계 (1월부터 해당 월까지)
        deposit_cumulative = DepositLedger.objects.filter(
            year=year, month__lte=month,
            category__name__in=['예수금(4대보험)', '예수금(원천세)']
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

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

            # '급여' 계정인 경우 예수금출납장 금액 합산
            if acc.account_name == '급여':
                cumulative += deposit_cumulative
                monthly += deposit_monthly

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

        # 확정 상태 조회 (스냅샷 존재 여부로 판단)
        budget_snapshot = MonthlySnapshot.objects.filter(
            snapshot_type='BUDGET', fiscal_year=year, month=month
        ).first()
        is_confirmed = budget_snapshot is not None
        confirmed_at = budget_snapshot.confirmed_at if budget_snapshot else None

        context = {
            **self.admin_site.each_context(request),
            'title': f'{year}년 {month}월 예산집행 내역',
            'opts': self.model._meta,
            'year': year,
            'month': month,
            'year_range': year_range,
            'month_range': month_range,
            'is_confirmed': is_confirmed,
            'confirmed_at': confirmed_at,
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

    def snapshot_confirm_cashbook(self, request):
        """예금/현금출납장 스냅샷 확정"""
        from django.utils import timezone

        if request.method != 'POST':
            return redirect('admin:monthly_report')

        year = int(request.POST.get('year'))
        month = int(request.POST.get('month'))
        requested_snapshot_type = request.POST.get('snapshot_type')  # CASHBOOK_BANK or CASHBOOK_CASH

        # 특정 타입만 확정 (지정된 경우)
        if requested_snapshot_type == 'CASHBOOK_BANK':
            types_to_confirm = [('BANK', 'CASHBOOK_BANK')]
        elif requested_snapshot_type == 'CASHBOOK_CASH':
            types_to_confirm = [('CASH', 'CASHBOOK_CASH')]
        else:
            # 둘 다 확정 (이전 호환성)
            types_to_confirm = [('BANK', 'CASHBOOK_BANK'), ('CASH', 'CASHBOOK_CASH')]

        for book_type, snapshot_type in types_to_confirm:
            # 현재 데이터 조회
            income_entries = list(CashBook.objects.filter(
                book_type=book_type, year=year, month=month, entry_type='INCOME'
            ).select_related('category', 'bank_account').order_by('order').values(
                'id', 'date', 'category__name', 'description', 'amount', 'bank_account__bank_name', 'note', 'order'
            ))

            expense_entries = list(CashBook.objects.filter(
                book_type=book_type, year=year, month=month, entry_type='EXPENSE'
            ).select_related('account', 'category', 'bank_account').order_by('order').values(
                'id', 'date', 'account__account_name', 'category__name', 'description', 'amount', 'bank_account__bank_name', 'note', 'order'
            ))

            # 합계 계산
            income_total = sum(e['amount'] or 0 for e in income_entries)
            expense_total = sum(e['amount'] or 0 for e in expense_entries)

            # 전월이월 계산 (직전 월 스냅샷에서 차월이월 가져오기)
            prev_balance = Decimal('0')
            if month == 1:
                prev_snapshot = MonthlySnapshot.objects.filter(
                    snapshot_type=snapshot_type, fiscal_year=year-1, month=12
                ).first()
            else:
                prev_snapshot = MonthlySnapshot.objects.filter(
                    snapshot_type=snapshot_type, fiscal_year=year, month=month-1
                ).first()
            if prev_snapshot and prev_snapshot.snapshot_data.get('next_balance'):
                prev_balance = Decimal(str(prev_snapshot.snapshot_data['next_balance']))

            # 차월이월 계산
            next_balance = prev_balance + income_total - expense_total

            # 날짜 직렬화를 위한 변환
            def serialize_entries(entries):
                result = []
                for e in entries:
                    item = dict(e)
                    if item.get('date'):
                        item['date'] = item['date'].isoformat()
                    # Decimal을 float로 변환
                    if item.get('amount'):
                        item['amount'] = float(item['amount'])
                    result.append(item)
                return result

            # 스냅샷 데이터 구성
            snapshot_data = {
                'income_entries': serialize_entries(income_entries),
                'expense_entries': serialize_entries(expense_entries),
                'income_total': float(income_total),
                'expense_total': float(expense_total),
                'prev_balance': float(prev_balance),
                'next_balance': float(next_balance),
            }

            # 스냅샷 생성 또는 업데이트
            snapshot, created = MonthlySnapshot.objects.update_or_create(
                snapshot_type=snapshot_type,
                fiscal_year=year,
                month=month,
                defaults={
                    'snapshot_data': snapshot_data,
                    'is_confirmed': True,
                    'confirmed_at': timezone.now(),
                    'confirmed_by': request.user.username if request.user.is_authenticated else '',
                }
            )

        # 메시지 생성
        if requested_snapshot_type == 'CASHBOOK_BANK':
            msg = f'{year}년 {month}월 예금출납장이 확정되었습니다.'
        elif requested_snapshot_type == 'CASHBOOK_CASH':
            msg = f'{year}년 {month}월 현금출납장이 확정되었습니다.'
        else:
            msg = f'{year}년 {month}월 예금/현금출납장이 확정되었습니다.'
        messages.success(request, msg)
        return redirect('admin:cashbook_combined', year=year, month=month)

    def snapshot_confirm_budget(self, request):
        """예산집행내역 스냅샷 확정"""
        from django.utils import timezone

        if request.method != 'POST':
            return redirect('admin:monthly_report')

        year = int(request.POST.get('year'))
        month = int(request.POST.get('month'))

        # 예산집행 데이터 조회
        data = self._get_budget_execution_data(year, month)

        # execution_data를 JSON 직렬화 가능한 형태로 변환
        def serialize_execution_data(execution_data):
            result = {}
            for large_cat, large_data in execution_data.items():
                result[large_cat] = {
                    'medium_categories': {},
                    'total_budget': float(large_data['total_budget']),
                    'total_executed': float(large_data['total_executed']),
                    'total_month': float(large_data['total_month']),
                    'total_remaining': float(large_data['total_remaining']),
                    'total_rate': float(large_data['total_rate']),
                    'row_count': large_data['row_count'],
                }
                for med_cat, med_data in large_data['medium_categories'].items():
                    items = []
                    for item in med_data['items']:
                        items.append({
                            'account_id': item['account'].id,
                            'account_code': item['account'].code,
                            'display_name': item['display_name'],
                            'annual_budget': float(item['annual_budget']),
                            'cumulative': float(item['cumulative']),
                            'exec_rate': float(item['exec_rate']),
                            'monthly': float(item['monthly']),
                            'remaining': float(item['remaining']),
                            'note': item['note'],
                        })
                    result[large_cat]['medium_categories'][med_cat] = {
                        'items': items,
                        'subtotal_budget': float(med_data['subtotal_budget']),
                        'subtotal_executed': float(med_data['subtotal_executed']),
                        'subtotal_month': float(med_data['subtotal_month']),
                        'subtotal_remaining': float(med_data['subtotal_remaining']),
                        'subtotal_rate': float(med_data['subtotal_rate']),
                        'row_count': med_data['row_count'],
                        'show_subtotal': med_data['show_subtotal'],
                    }
            return result

        # 스냅샷 데이터 구성
        snapshot_data = {
            'execution_data': serialize_execution_data(data['execution_data']),
            'grand_total_budget': float(data['grand_total_budget']),
            'grand_total_executed': float(data['grand_total_executed']),
            'grand_total_month': float(data['grand_total_month']),
            'grand_total_remaining': float(data['grand_total_remaining']),
            'grand_total_rate': float(data['grand_total_rate']),
        }

        # 스냅샷 생성 또는 업데이트
        snapshot, created = MonthlySnapshot.objects.update_or_create(
            snapshot_type='BUDGET',
            fiscal_year=year,
            month=month,
            defaults={
                'snapshot_data': snapshot_data,
                'is_confirmed': True,
                'confirmed_at': timezone.now(),
                'confirmed_by': request.user.username if request.user.is_authenticated else '',
            }
        )

        messages.success(request, f'{year}년 {month}월 예산집행내역이 확정되었습니다.')
        return redirect('admin:budget_execution', year=year, month=month)

    def snapshot_cancel(self, request, snapshot_type, year, month):
        """스냅샷 확정 해제"""
        if request.method != 'POST':
            return redirect('admin:monthly_report')

        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        snapshot = MonthlySnapshot.objects.filter(
            snapshot_type=snapshot_type, fiscal_year=year, month=month
        ).first()

        if snapshot:
            type_names = {
                'BUDGET': '예산집행내역',
                'CASHBOOK_BANK': '예금출납장',
                'CASHBOOK_CASH': '현금출납장',
                'CARD_EXPENSE': '카드사용내역',
            }
            type_name = type_names.get(snapshot_type, snapshot_type)
            snapshot.delete()
            msg = f'{year}년 {month}월 {type_name} 확정이 해제되었습니다.'

            if is_ajax:
                return JsonResponse({'success': True, 'message': msg})

            messages.success(request, msg)

        # 리다이렉트
        if snapshot_type == 'BUDGET':
            return redirect('admin:budget_execution', year=year, month=month)
        elif snapshot_type == 'CARD_EXPENSE':
            return redirect('admin:card_upload')
        else:
            return redirect('admin:cashbook_combined', year=year, month=month)

    def confirmed_report_main(self, request):
        """월간보고서(확정) 메인 화면"""
        from datetime import datetime
        current_month = datetime.now().month

        default_year = 2025
        selected_year = int(request.GET.get('year', default_year))
        selected_month = int(request.GET.get('month', current_month))

        years = list(range(2027, 2023, -1))
        months = list(range(1, 13))

        # 확정된 스냅샷 목록 조회
        confirmed_snapshots = MonthlySnapshot.objects.filter(
                    ).values('snapshot_type', 'fiscal_year', 'month', 'confirmed_at').order_by('-fiscal_year', '-month')

        context = {
            **self.admin_site.each_context(request),
            'title': '월간보고서(확정)',
            'opts': self.model._meta,
            'years': years,
            'months': months,
            'selected_year': selected_year,
            'selected_month': selected_month,
            'confirmed_snapshots': confirmed_snapshots,
        }

        return TemplateResponse(request, 'admin/confirmed_report_main.html', context)

    def confirmed_cashbook_view(self, request, book_type, year, month):
        """확정된 출납장 조회"""
        snapshot_type = f'CASHBOOK_{book_type}'
        snapshot = MonthlySnapshot.objects.filter(
            snapshot_type=snapshot_type, fiscal_year=year, month=month
        ).first()

        if not snapshot:
            messages.warning(request, f'{year}년 {month}월 {"예금" if book_type == "BANK" else "현금"}출납장이 확정되지 않았습니다.')
            return redirect('admin:confirmed_report')

        data = snapshot.snapshot_data
        book_type_display = '예금출납장' if book_type == 'BANK' else '현금출납장'

        year_range = list(range(2024, 2028))
        month_range = list(range(1, 13))

        context = {
            **self.admin_site.each_context(request),
            'title': f'{book_type_display}(확정) ({year}. {month}월)',
            'opts': self.model._meta,
            'book_type': book_type,
            'book_type_display': book_type_display,
            'year': year,
            'month': month,
            'year_range': year_range,
            'month_range': month_range,
            'income_entries': data.get('income_entries', []),
            'expense_entries': data.get('expense_entries', []),
            'income_total': data.get('income_total', 0),
            'expense_total': data.get('expense_total', 0),
            'prev_balance': data.get('prev_balance', 0),
            'next_balance': data.get('next_balance', 0),
            'confirmed_at': snapshot.confirmed_at,
            'confirmed_by': snapshot.confirmed_by,
        }

        return TemplateResponse(request, 'admin/confirmed_cashbook.html', context)

    def confirmed_budget_view(self, request, year, month):
        """확정된 예산집행내역 조회"""
        snapshot = MonthlySnapshot.objects.filter(
            snapshot_type='BUDGET', fiscal_year=year, month=month
        ).first()

        if not snapshot:
            messages.warning(request, f'{year}년 {month}월 예산집행내역이 확정되지 않았습니다.')
            return redirect('admin:confirmed_report')

        data = snapshot.snapshot_data

        year_range = list(range(2024, 2028))
        month_range = list(range(1, 13))

        context = {
            **self.admin_site.each_context(request),
            'title': f'{year}년 {month}월 예산집행 내역(확정)',
            'opts': self.model._meta,
            'year': year,
            'month': month,
            'year_range': year_range,
            'month_range': month_range,
            'execution_data': data.get('execution_data', {}),
            'grand_total_budget': data.get('grand_total_budget', 0),
            'grand_total_executed': data.get('grand_total_executed', 0),
            'grand_total_month': data.get('grand_total_month', 0),
            'grand_total_remaining': data.get('grand_total_remaining', 0),
            'grand_total_rate': data.get('grand_total_rate', 0),
            'confirmed_at': snapshot.confirmed_at,
            'confirmed_by': snapshot.confirmed_by,
        }

        return TemplateResponse(request, 'admin/confirmed_budget.html', context)

    def snapshot_confirm_card(self, request):
        """카드사용내역 스냅샷 확정"""
        from django.utils import timezone

        if request.method != 'POST':
            return redirect('admin:monthly_report')

        year = int(request.POST.get('year'))
        month = int(request.POST.get('month'))

        # 해당 월의 카드 지출 조회
        card_items = list(Transaction.objects.filter(
            date__year=year,
            date__month=month,
            payment_method='CARD',
            transaction_type='EXPENSE',
        ).order_by('date').select_related('account').values(
            'id', 'date', 'account__account_name', 'description', 'amount', 'approval_number'
        ))

        # 합계 계산
        total_amount = sum(item['amount'] or 0 for item in card_items)

        # 날짜 직렬화
        serialized_items = []
        for item in card_items:
            serialized_items.append({
                'id': item['id'],
                'date': item['date'].isoformat() if item['date'] else None,
                'day': item['date'].day if item['date'] else None,
                'account_name': item['account__account_name'] or '',
                'description': item['description'] or '',
                'amount': float(item['amount']) if item['amount'] else 0,
                'approval_number': item['approval_number'] or '',
            })

        # 스냅샷 데이터 구성
        snapshot_data = {
            'card_items': serialized_items,
            'total_amount': float(total_amount),
            'item_count': len(card_items),
        }

        # 스냅샷 생성 또는 업데이트
        snapshot, created = MonthlySnapshot.objects.update_or_create(
            snapshot_type='CARD_EXPENSE',
            fiscal_year=year,
            month=month,
            defaults={
                'snapshot_data': snapshot_data,
                'is_confirmed': True,
                'confirmed_at': timezone.now(),
                'confirmed_by': request.user.username if request.user.is_authenticated else '',
            }
        )

        # AJAX 요청 처리
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': f'{year}년 {month}월 카드사용내역이 확정되었습니다.',
                'is_confirmed': True,
                'confirmed_at': snapshot.confirmed_at.strftime('%Y-%m-%d %H:%M'),
            })

        messages.success(request, f'{year}년 {month}월 카드사용내역이 확정되었습니다.')
        return redirect('admin:card_upload')

    def confirmed_card_view(self, request, year, month):
        """확정된 카드사용내역 조회"""
        snapshot = MonthlySnapshot.objects.filter(
            snapshot_type='CARD_EXPENSE', fiscal_year=year, month=month
        ).first()

        if not snapshot:
            messages.warning(request, f'{year}년 {month}월 카드사용내역이 확정되지 않았습니다.')
            return redirect('admin:confirmed_report')

        data = snapshot.snapshot_data

        year_range = list(range(2024, 2028))
        month_range = list(range(1, 13))

        context = {
            **self.admin_site.each_context(request),
            'title': f'카드사용내역(확정) ({year}. {month}월)',
            'opts': self.model._meta,
            'year': year,
            'month': month,
            'year_range': year_range,
            'month_range': month_range,
            'card_items': data.get('card_items', []),
            'total_amount': data.get('total_amount', 0),
            'item_count': data.get('item_count', 0),
            'confirmed_at': snapshot.confirmed_at,
            'confirmed_by': snapshot.confirmed_by,
        }

        return TemplateResponse(request, 'admin/confirmed_card.html', context)
