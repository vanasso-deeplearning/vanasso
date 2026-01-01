#!/usr/bin/env python
"""
데이터베이스 백업 스크립트
SQLite 파일을 backups/ 폴더에 날짜별로 백업합니다.

사용법:
    .venv\Scripts\python.exe backup_db.py

자동 실행 (Windows 작업 스케줄러):
    1. 작업 스케줄러 실행
    2. 새 작업 만들기
    3. 트리거: 매일 특정 시간
    4. 동작: 프로그램 시작
       - 프로그램: .venv/Scripts/python.exe
       - 인수: backup_db.py
       - 시작 위치: 프로젝트 폴더
"""
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

# 설정
BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / 'db.sqlite3'
BACKUP_DIR = BASE_DIR / 'backups'
RETENTION_DAYS = 30


def create_backup():
    """DB 백업 생성"""
    if not DB_FILE.exists():
        print(f"[오류] DB 파일이 존재하지 않습니다: {DB_FILE}")
        return False

    # 백업 폴더 생성
    BACKUP_DIR.mkdir(exist_ok=True)

    # 백업 파일명 생성
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"db_backup_{timestamp}.sqlite3"
    backup_path = BACKUP_DIR / backup_filename

    # 파일 복사
    shutil.copy2(DB_FILE, backup_path)
    print(f"[성공] 백업 생성: {backup_filename}")

    return True


def cleanup_old_backups():
    """오래된 백업 파일 삭제 (RETENTION_DAYS일 이상)"""
    if not BACKUP_DIR.exists():
        return

    cutoff_date = datetime.now() - timedelta(days=RETENTION_DAYS)
    deleted_count = 0

    for backup_file in BACKUP_DIR.glob('db_backup_*.sqlite3'):
        # 파일명에서 날짜 추출
        try:
            filename = backup_file.stem
            date_str = filename.replace('db_backup_', '').split('_')[0]
            file_date = datetime.strptime(date_str, '%Y%m%d')

            if file_date < cutoff_date:
                backup_file.unlink()
                deleted_count += 1
                print(f"[삭제] 오래된 백업 삭제: {backup_file.name}")
        except (ValueError, IndexError):
            continue

    if deleted_count > 0:
        print(f"[정리] {deleted_count}개 오래된 백업 삭제 완료")


def list_backups():
    """현재 백업 목록 표시"""
    if not BACKUP_DIR.exists():
        print("백업 폴더가 없습니다.")
        return

    backups = sorted(BACKUP_DIR.glob('db_backup_*.sqlite3'), reverse=True)

    if not backups:
        print("백업 파일이 없습니다.")
        return

    print(f"\n현재 백업 목록 (총 {len(backups)}개):")
    print("-" * 50)
    for backup in backups[:10]:
        size_mb = backup.stat().st_size / (1024 * 1024)
        print(f"  {backup.name} ({size_mb:.2f} MB)")

    if len(backups) > 10:
        print(f"  ... 외 {len(backups) - 10}개")


def main():
    print(f"\n{'='*50}")
    print(f"  DB 백업 스크립트")
    print(f"  실행 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    # 백업 생성
    if create_backup():
        # 오래된 백업 정리
        cleanup_old_backups()

    # 백업 목록 표시
    list_backups()

    print(f"\n{'='*50}")
    print(f"  백업 완료!")
    print(f"{'='*50}\n")


if __name__ == '__main__':
    main()
