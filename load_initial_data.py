#!/usr/bin/env python
"""
초기 데이터 로드 스크립트
finance_setup_template.xlsx 파일에서 데이터를 읽어 DB에 적재합니다.

사용법:
    .venv/Scripts/python.exe load_initial_data.py
"""
import os
import sys
import django

# Django 설정
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

import pandas as pd
from datetime import datetime
from decimal import Decimal
from django.db import transaction
from finance.models import Account, Member, FixedAsset, Budget


EXCEL_FILE = 'finance_setup_template.xlsx'


def load_accounts(df):
    """
    Sheet1: 계정과목 로드
    컬럼: 분류(대분류), 분류(소분류), 계정명, 성격, 결산서위치, 비고
    """
    count = 0
    code_counter = 1

    for _, row in df.iterrows():
        category_large = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ''
        category_medium = str(row.iloc[1]) if pd.notna(row.iloc[1]) else ''
        account_name = str(row.iloc[2]) if pd.notna(row.iloc[2]) else ''
        account_type = str(row.iloc[3]) if pd.notna(row.iloc[3]) else 'EXPENSE'
        report_position = str(row.iloc[4]) if pd.notna(row.iloc[4]) else ''

        if not account_name:
            continue

        # 계정코드 자동 생성 (A001, A002, ...)
        code = f"A{code_counter:03d}"

        Account.objects.update_or_create(
            code=code,
            defaults={
                'category_large': category_large,
                'category_medium': category_medium,
                'category_small': account_name,
                'account_type': account_type,
                'report_position': report_position,
            }
        )
        count += 1
        code_counter += 1

    print(f"  - 계정과목: {count}건 로드 완료")


def load_members(df):
    """
    Sheet2: 회원사 로드
    컬럼: 회원사명, 사업자번호, 대표명, 연락처
    """
    count = 0
    for _, row in df.iterrows():
        name = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ''
        if not name:
            continue

        business_number = str(row.iloc[1]) if len(row) > 1 and pd.notna(row.iloc[1]) else ''
        contact_person = str(row.iloc[2]) if len(row) > 2 and pd.notna(row.iloc[2]) else ''

        Member.objects.update_or_create(
            name=name,
            defaults={
                'business_number': business_number,
                'partner_type': 'MEMBER',
                'contact_person': contact_person,
            }
        )
        count += 1

    print(f"  - 회원사: {count}건 로드 완료")


def load_fixed_assets(df):
    """
    Sheet3: 고정자산 로드
    컬럼: 자산명, 취득일자, 취득가액, 내용연수(년), 비고
    """
    count = 0
    for _, row in df.iterrows():
        asset_name = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ''
        if not asset_name:
            continue

        acquisition_date = row.iloc[1]
        if isinstance(acquisition_date, str):
            acquisition_date = datetime.strptime(acquisition_date, '%Y-%m-%d').date()
        elif hasattr(acquisition_date, 'date'):
            acquisition_date = acquisition_date.date()

        acquisition_cost = Decimal(str(row.iloc[2])) if pd.notna(row.iloc[2]) else Decimal('0')
        useful_life = int(row.iloc[3]) if pd.notna(row.iloc[3]) else 5

        FixedAsset.objects.update_or_create(
            name=asset_name,
            defaults={
                'acquisition_date': acquisition_date,
                'acquisition_cost': acquisition_cost,
                'useful_life': useful_life,
                'depreciation_method': 'STRAIGHT',
                'salvage_value': Decimal('0'),
                'current_value': acquisition_cost,
            }
        )
        count += 1

    print(f"  - 고정자산: {count}건 로드 완료")


def load_budgets(df):
    """
    Sheet4: 예산 로드
    컬럼: 분류(대분류), 분류(소분류), 계정명, 연간예산액, 비고
    """
    count = 0
    fiscal_year = 2025

    for _, row in df.iterrows():
        account_name = str(row.iloc[2]) if pd.notna(row.iloc[2]) else ''
        if not account_name:
            continue

        annual_amount = Decimal(str(row.iloc[3])) if pd.notna(row.iloc[3]) else Decimal('0')

        # 계정과목 찾기 (category_small로 매칭)
        try:
            account = Account.objects.get(category_small=account_name)
        except Account.DoesNotExist:
            print(f"    [경고] 계정 '{account_name}' 미존재, 건너뜀")
            continue
        except Account.MultipleObjectsReturned:
            account = Account.objects.filter(category_small=account_name).first()

        Budget.objects.update_or_create(
            fiscal_year=fiscal_year,
            account=account,
            defaults={
                'annual_amount': annual_amount,
                'supplementary_amount': Decimal('0'),
            }
        )
        count += 1

    print(f"  - 예산: {count}건 로드 완료")


@transaction.atomic
def main():
    print(f"\n{'='*50}")
    print(f"  초기 데이터 로드 시작")
    print(f"  파일: {EXCEL_FILE}")
    print(f"{'='*50}\n")

    if not os.path.exists(EXCEL_FILE):
        print(f"[오류] 파일을 찾을 수 없습니다: {EXCEL_FILE}")
        return

    # 기존 데이터 삭제
    print("기존 데이터 삭제 중...")
    Budget.objects.all().delete()
    FixedAsset.objects.all().delete()
    Member.objects.all().delete()
    Account.objects.all().delete()
    print("  - 기존 데이터 삭제 완료\n")

    # 엑셀 파일 로드
    xlsx = pd.ExcelFile(EXCEL_FILE)
    sheet_names = xlsx.sheet_names
    print(f"발견된 시트: {len(sheet_names)}개\n")

    # Sheet1: 계정과목
    if len(sheet_names) >= 1:
        df = pd.read_excel(xlsx, sheet_name=0)
        load_accounts(df)

    # Sheet2: 회원사
    if len(sheet_names) >= 2:
        df = pd.read_excel(xlsx, sheet_name=1)
        load_members(df)

    # Sheet3: 고정자산
    if len(sheet_names) >= 3:
        df = pd.read_excel(xlsx, sheet_name=2)
        load_fixed_assets(df)

    # Sheet4: 예산
    if len(sheet_names) >= 4:
        df = pd.read_excel(xlsx, sheet_name=3)
        load_budgets(df)

    print(f"\n{'='*50}")
    print(f"  초기 데이터 로드 완료!")
    print(f"{'='*50}\n")

    # 로드된 데이터 요약
    print("로드된 데이터 요약:")
    print(f"  - 계정과목: {Account.objects.count()}건")
    print(f"  - 회원사: {Member.objects.count()}건")
    print(f"  - 고정자산: {FixedAsset.objects.count()}건")
    print(f"  - 예산: {Budget.objects.count()}건")


if __name__ == '__main__':
    main()
