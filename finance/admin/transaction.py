# finance/admin/transaction.py
# 거래내역 및 카드 업로드 Admin

from django.contrib import admin
from django.urls import path
from django.shortcuts import redirect, render
from django.contrib import messages
from django.db import transaction
from django.template.response import TemplateResponse
from django.http import JsonResponse
from decimal import Decimal, InvalidOperation
import pandas as pd
import json

from ..models import Account, Transaction, MonthlySnapshot


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
            path('card-upload/', self.admin_site.admin_view(self.card_upload_view), name='card_upload'),
            path('card-upload/save/', self.admin_site.admin_view(self.card_upload_save), name='card_upload_save'),
            path('card-delete/', self.admin_site.admin_view(self.card_delete_items), name='card_delete_items'),
            path('card-query/', self.admin_site.admin_view(self.card_query), name='card_query'),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        """거래내역조회/삭제 목록 화면"""
        extra_context = extra_context or {}
        extra_context['title'] = '거래내역조회/삭제'
        return super().changelist_view(request, extra_context)

    def get_accounts_json(self):
        """현재 연도 계정과목을 JSON으로 반환"""
        from datetime import datetime
        current_year = datetime.now().year

        accounts = Account.objects.filter(
            fiscal_year=current_year,
            is_active=True
        ).order_by('account_type', 'code')

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
        """추가 폼 화면"""
        extra_context = extra_context or {}
        extra_context['title'] = '거래내역추가'
        extra_context['show_save_and_add_another'] = False
        extra_context['accounts_json'] = self.get_accounts_json()
        return super().add_view(request, form_url, extra_context)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        """수정 폼 화면"""
        extra_context = extra_context or {}
        extra_context['accounts_json'] = self.get_accounts_json()
        return super().change_view(request, object_id, form_url, extra_context)

    def card_upload_view(self, request):
        """카드 엑셀 업로드 화면"""
        from datetime import datetime

        current_year = datetime.now().year
        current_month = datetime.now().month

        # 지출 계정과목 목록 조회
        expense_accounts = Account.objects.filter(
            fiscal_year=current_year,
            account_type='EXPENSE',
            is_active=True
        ).order_by('code')

        context = {
            **self.admin_site.each_context(request),
            'title': '카드 엑셀 업로드',
            'opts': self.model._meta,
            'year_range': range(current_year - 1, current_year + 2),
            'month_range': range(1, 13),
            'current_year': current_year,
            'current_month': current_month,
            'expense_accounts': expense_accounts,
        }

        if request.method == 'POST' and request.FILES.get('excel_file'):
            excel_file = request.FILES['excel_file']

            df = None
            header_row = None

            try:
                df_raw = pd.read_excel(excel_file, header=None)

                for i in range(min(10, len(df_raw))):
                    first_cell = str(df_raw.iloc[i, 0]).strip() if pd.notna(df_raw.iloc[i, 0]) else ''
                    if first_cell == 'NO':
                        header_row = i
                        break

                if header_row is None:
                    header_keywords = ['이용일', '승인금액', '매출금액', '가맹점명', '카드번호']
                    for i in range(min(10, len(df_raw))):
                        row_str = ' '.join(str(v) for v in df_raw.iloc[i].tolist() if pd.notna(v))
                        if any(kw in row_str for kw in header_keywords):
                            header_row = i
                            break

                excel_file.seek(0)
                if header_row is not None:
                    df = pd.read_excel(excel_file, header=header_row)
                else:
                    df = pd.read_excel(excel_file)

            except Exception as e:
                messages.error(request, f'엑셀 파일 읽기 오류: {e}')
                return TemplateResponse(request, 'admin/card_upload.html', context)

            column_mapping = {
                'cancel': ['취소\n구분', '취소구분', '취소 구분', '상태', '승인상태'],
                'cancel_amount': ['취소매출금액', '취소금액'],
                'date': ['이용일자', '이용일', '거래일자', '거래일', '승인일자', '승인일'],
                'amount': ['매출금액', '이용금액', '승인금액', '결제금액', '금액'],
                'exchange_fee': ['환가료'],
                'description': ['가맹점명', '가맹점', '이용가맹점', '이용처', '사용처'],
                'card_number': ['카드번호', '카드 번호', '카드NO'],
                'approval_number': ['승인번호', '승인NO', '승인 번호'],
            }

            def find_column(df, candidates):
                for col in candidates:
                    if col in df.columns:
                        return col
                return None

            cancel_col = find_column(df, column_mapping['cancel'])
            cancel_amount_col = find_column(df, column_mapping['cancel_amount'])
            date_col = find_column(df, column_mapping['date'])
            amount_col = find_column(df, column_mapping['amount'])
            exchange_fee_col = find_column(df, column_mapping['exchange_fee'])
            desc_col = find_column(df, column_mapping['description'])
            card_col = find_column(df, column_mapping['card_number'])
            approval_col = find_column(df, column_mapping['approval_number'])

            if not date_col or not amount_col:
                col_list = ', '.join(str(c) for c in df.columns.tolist())
                messages.error(request, f'필수 컬럼을 찾을 수 없습니다. 엑셀 컬럼: [{col_list}]')
                return TemplateResponse(request, 'admin/card_upload.html', context)

            card_items = []
            for idx, row in df.iterrows():
                if cancel_col:
                    cancel_status = str(row.get(cancel_col, '')).strip()
                    if cancel_status and cancel_status not in ['정상', '승인', '']:
                        continue

                if cancel_amount_col:
                    try:
                        cancel_val = row.get(cancel_amount_col, 0)
                        if isinstance(cancel_val, str):
                            cancel_val = cancel_val.replace(',', '').replace('-', '')
                        if cancel_val and float(cancel_val) > 0:
                            continue
                    except (ValueError, TypeError):
                        pass

                date_val = row.get(date_col, '')
                date_obj = None

                if pd.notna(date_val) and hasattr(date_val, 'date'):
                    date_obj = date_val.date()
                else:
                    date_str = str(date_val).strip()
                    for fmt in ['%Y.%m.%d', '%Y-%m-%d', '%Y/%m/%d', '%Y%m%d']:
                        try:
                            date_obj = datetime.strptime(date_str, fmt).date()
                            break
                        except ValueError:
                            continue

                if not date_obj:
                    continue

                try:
                    amount_val = row.get(amount_col, 0)
                    if isinstance(amount_val, str):
                        amount_val = amount_val.replace(',', '')
                    amount = Decimal(str(amount_val))
                except (ValueError, InvalidOperation):
                    amount = Decimal('0')

                # 환가료 합산
                if exchange_fee_col:
                    try:
                        fee_val = row.get(exchange_fee_col, 0)
                        if isinstance(fee_val, str):
                            fee_val = fee_val.replace(',', '')
                        if fee_val and str(fee_val).strip():
                            amount += Decimal(str(fee_val))
                    except (ValueError, InvalidOperation):
                        pass

                if amount <= 0:
                    continue

                # 승인번호 처리 (NaN 값 처리)
                approval_number = ''
                if approval_col:
                    approval_val = row.get(approval_col, '')
                    if pd.notna(approval_val):
                        approval_number = str(approval_val).strip()
                        # 'nan' 문자열 제거
                        if approval_number.lower() == 'nan':
                            approval_number = ''

                card_items.append({
                    'index': idx,
                    'date': date_obj,
                    'description': str(row.get(desc_col, '')).strip() if desc_col else '',
                    'amount': amount,
                    'card_number': str(row.get(card_col, '')).strip() if card_col else '',
                    'approval_number': approval_number,
                })

            if not card_items:
                messages.error(request, '유효한 카드 내역이 없습니다.')
                return TemplateResponse(request, 'admin/card_upload.html', context)

            # 카드 내역의 연도를 기준으로 계정과목 조회
            card_year = card_items[0]['date'].year
            accounts = Account.objects.filter(
                fiscal_year=card_year,
                account_type='EXPENSE'
            ).order_by('code')

            if not accounts.exists():
                # 해당 연도 계정이 없으면 현재 연도로 fallback
                accounts = Account.objects.filter(
                    fiscal_year=datetime.now().year,
                    account_type='EXPENSE'
                ).order_by('code')

            context['card_items'] = card_items
            context['accounts'] = accounts
            context['total_amount'] = sum(item['amount'] for item in card_items)
            context['total_count'] = len(card_items)

            request.session['card_items'] = [
                {
                    'index': item['index'],
                    'date': item['date'].isoformat(),
                    'description': item['description'],
                    'amount': str(item['amount']),
                    'card_number': item['card_number'],
                    'approval_number': item['approval_number'],
                }
                for item in card_items
            ]

            if card_items:
                first_date = card_items[0]['date']
                upload_year = first_date.year
                upload_month = first_date.month

                existing_card_expenses = Transaction.objects.filter(
                    date__year=upload_year,
                    date__month=upload_month,
                    transaction_type='EXPENSE',
                    payment_method='CARD'
                ).select_related('account').order_by('date')

                existing_items = []
                existing_total = Decimal('0')
                for txn in existing_card_expenses:
                    existing_items.append({
                        'id': txn.id,
                        'day': txn.date.day,
                        'account_name': txn.account.account_name if txn.account else '',
                        'amount': int(txn.amount),
                        'description': txn.description or '',
                    })
                    existing_total += txn.amount

                context['existing_items'] = existing_items
                context['existing_total'] = int(existing_total)
                context['existing_count'] = len(existing_items)
                context['upload_year'] = upload_year
                context['upload_month'] = upload_month

                snapshot = MonthlySnapshot.objects.filter(
                    fiscal_year=upload_year,
                    month=upload_month,
                    snapshot_type='CARD_EXPENSE',
                    is_confirmed=True
                ).first()

                if snapshot:
                    context['is_confirmed'] = True
                    context['confirmed_at'] = snapshot.confirmed_at.strftime('%Y-%m-%d %H:%M')
                else:
                    context['is_confirmed'] = False
                    context['confirmed_at'] = None

            return TemplateResponse(request, 'admin/card_upload_confirm.html', context)

        return TemplateResponse(request, 'admin/card_upload.html', context)

    def card_upload_save(self, request):
        """카드 내역 일괄 저장"""
        from datetime import datetime

        if request.method != 'POST':
            return redirect('admin:card_upload')

        card_items = request.session.get('card_items', [])
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if not card_items:
            if is_ajax:
                return JsonResponse({'error': '저장할 데이터가 없습니다.'}, status=400)
            messages.error(request, '저장할 데이터가 없습니다.')
            return redirect('admin:card_upload')

        saved_count = 0
        skipped_count = 0
        updated_count = 0
        saved_items = []

        with transaction.atomic():
            for item in card_items:
                account_id = request.POST.get(f'account_{item["index"]}')

                if not account_id:
                    skipped_count += 1
                    continue

                try:
                    account = Account.objects.get(pk=account_id)
                    txn_date = datetime.fromisoformat(item['date']).date()
                    txn_amount = Decimal(item['amount'])
                    approval_number = item.get('approval_number', '')

                    # 중복 체크: 승인번호가 있으면 승인번호로, 없으면 날짜+금액+가맹점명으로
                    existing_txn = None
                    if approval_number:
                        existing_txn = Transaction.objects.filter(
                            approval_number=approval_number,
                            payment_method='CARD',
                        ).first()
                    else:
                        # 승인번호 없는 경우 날짜+금액+가맹점명으로 중복 체크
                        existing_txn = Transaction.objects.filter(
                            date=txn_date,
                            amount=txn_amount,
                            description=item['description'],
                            payment_method='CARD',
                        ).first()

                    if existing_txn:
                        # 계정과목이 다르면 업데이트
                        if existing_txn.account_id != account.id:
                            existing_txn.account = account
                            existing_txn.save(update_fields=['account'])
                            saved_items.append({
                                'index': item['index'],
                                'day': txn_date.day,
                                'date': txn_date.isoformat(),
                                'account_name': account.account_name,
                                'amount': int(txn_amount),
                                'description': item['description'],
                            })
                            updated_count += 1
                        else:
                            skipped_count += 1
                        continue

                    Transaction.objects.create(
                        date=txn_date,
                        transaction_type='EXPENSE',
                        account=account,
                        description=item['description'],
                        amount=txn_amount,
                        payment_method='CARD',
                        approval_number=approval_number if approval_number else None,
                        status='APPROVED',
                    )
                    saved_items.append({
                        'index': item['index'],
                        'day': txn_date.day,
                        'date': txn_date.isoformat(),
                        'account_name': account.account_name,
                        'amount': int(txn_amount),
                        'description': item['description'],
                    })
                    saved_count += 1
                except Exception:
                    skipped_count += 1

        if is_ajax:
            if card_items:
                first_date = datetime.fromisoformat(card_items[0]['date']).date()
                year = first_date.year
                month = first_date.month

                all_card_items = Transaction.objects.filter(
                    date__year=year,
                    date__month=month,
                    payment_method='CARD',
                    transaction_type='EXPENSE',
                ).order_by('date').select_related('account')

                all_items = [{
                    'id': txn.id,
                    'day': txn.date.day,
                    'date': txn.date.isoformat(),
                    'account_name': txn.account.account_name,
                    'amount': int(txn.amount),
                    'description': txn.description,
                } for txn in all_card_items]
                total_amount = sum(item['amount'] for item in all_items)
            else:
                all_items = []
                total_amount = 0
                year = 0
                month = 0

            saved_indices = [item['index'] for item in saved_items]

            is_confirmed = False
            confirmed_at = None
            if card_items:
                snapshot = MonthlySnapshot.objects.filter(
                    snapshot_type='CARD_EXPENSE',
                    fiscal_year=year,
                    month=month,
                    is_confirmed=True
                ).first()
                if snapshot:
                    is_confirmed = True
                    confirmed_at = snapshot.confirmed_at.strftime('%Y-%m-%d %H:%M') if snapshot.confirmed_at else None

            return JsonResponse({
                'saved_count': saved_count,
                'updated_count': updated_count,
                'skipped_count': skipped_count,
                'saved_items': all_items,
                'saved_indices': saved_indices,
                'total_amount': int(total_amount),
                'year': year,
                'month': month,
                'is_confirmed': is_confirmed,
                'confirmed_at': confirmed_at,
            })

        if 'card_items' in request.session:
            del request.session['card_items']

        total_amount = sum(item['amount'] for item in saved_items)
        context = {
            **self.admin_site.each_context(request),
            'title': '카드사용내역 저장 결과',
            'saved_count': saved_count,
            'updated_count': updated_count,
            'skipped_count': skipped_count,
            'saved_items': saved_items,
            'total_amount': total_amount,
        }
        return render(request, 'admin/card_upload_result.html', context)

    def card_delete_items(self, request):
        """카드 내역 선택 삭제"""
        if request.method != 'POST':
            return JsonResponse({'success': False, 'error': 'POST 요청만 허용됩니다.'}, status=405)

        try:
            txn_ids_str = request.POST.get('txn_ids', '[]')
            txn_ids = json.loads(txn_ids_str)

            if not txn_ids:
                return JsonResponse({'success': False, 'error': '삭제할 내역이 없습니다.'}, status=400)

            # 삭제 실행
            deleted_count = 0
            with transaction.atomic():
                for txn_id in txn_ids:
                    try:
                        txn = Transaction.objects.get(pk=txn_id)
                        txn.delete()
                        deleted_count += 1
                    except Transaction.DoesNotExist:
                        pass

            return JsonResponse({
                'success': True,
                'message': f'{deleted_count}건이 삭제되었습니다.',
                'deleted_count': deleted_count,
            })

        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': '잘못된 요청 형식입니다.'}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'삭제 중 오류: {e}'}, status=500)

    def card_query(self, request):
        """카드사용내역 조회 API"""
        try:
            year = int(request.GET.get('year', 0))
            month = int(request.GET.get('month', 0))
            account_id = request.GET.get('account_id', '')

            if not year or not month:
                return JsonResponse({'error': '연도와 월을 지정해주세요.'}, status=400)

            # 해당 월의 카드사용내역 조회
            card_items = Transaction.objects.filter(
                date__year=year,
                date__month=month,
                transaction_type='EXPENSE',
                payment_method='CARD'
            )

            # 계정과목 필터 적용
            if account_id:
                card_items = card_items.filter(account_id=account_id)

            card_items = card_items.select_related('account').order_by('date')

            items = []
            total_amount = Decimal('0')
            for txn in card_items:
                items.append({
                    'id': txn.id,
                    'day': txn.date.day,
                    'account_name': txn.account.account_name if txn.account else '',
                    'amount': int(txn.amount),
                    'description': txn.description or '',
                })
                total_amount += txn.amount

            # 확정 여부 확인
            snapshot = MonthlySnapshot.objects.filter(
                fiscal_year=year,
                month=month,
                snapshot_type='CARD_EXPENSE',
                is_confirmed=True
            ).first()

            is_confirmed = snapshot is not None
            confirmed_at = snapshot.confirmed_at.strftime('%Y-%m-%d %H:%M') if snapshot and snapshot.confirmed_at else None

            return JsonResponse({
                'items': items,
                'total_amount': int(total_amount),
                'item_count': len(items),
                'is_confirmed': is_confirmed,
                'confirmed_at': confirmed_at,
            })

        except ValueError:
            return JsonResponse({'error': '잘못된 연도 또는 월입니다.'}, status=400)
        except Exception as e:
            return JsonResponse({'error': f'조회 중 오류: {e}'}, status=500)
