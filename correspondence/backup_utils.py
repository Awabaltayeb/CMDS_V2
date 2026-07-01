"""
منطق النسخ الاحتياطي المشترك — يُستخدم من الأمر المجدول (backup_data)
ومن زر التحميل الفوري بلوحة التحكم (dashboard) في آن واحد، حتى لا يتكرر الكود.

كل نسخة احتياطية عبارة عن ملف zip واحد يحتوي على:
  1. data.json — تفريغ كامل لبيانات قاعدة البيانات (بصيغة مستقلة عن نوع
     القاعدة، تشتغل مع SQLite أو PostgreSQL بدون فرق).
  2. media/ — كل ملفات الخطابات (PDF) المرفوعة فعلياً.

نستثني من التفريغ الجداول التقنية البحتة (الجلسات وأنواع المحتوى) لأنها
تُعاد بناؤها تلقائياً من Django ولا فائدة من نسخها.
"""

import io
import os
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management import call_command


EXCLUDED_APPS = ['contenttypes', 'sessions.session', 'admin.logentry']


def get_backup_dir():
    backup_dir = Path(getattr(settings, 'BACKUP_ROOT', settings.BASE_DIR / 'backups'))
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def create_backup():
    """
    ينشئ نسخة احتياطية جديدة ويحفظها في مجلد backups/ بالمشروع،
    ثم يرجّع مسار الملف الناتج (Path).
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = get_backup_dir()
    zip_path = backup_dir / f'cdms_backup_{timestamp}.zip'

    # 1. تفريغ بيانات قاعدة البيانات إلى JSON في الذاكرة
    json_buffer = io.StringIO()
    call_command(
        'dumpdata',
        exclude=EXCLUDED_APPS,
        indent=2,
        stdout=json_buffer,
    )
    json_buffer.seek(0)

    # 2. تجميع كل شيء داخل ملف zip واحد
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('data.json', json_buffer.read())

        media_root = Path(settings.MEDIA_ROOT)
        if media_root.exists():
            for root, _, files in os.walk(media_root):
                for filename in files:
                    file_path = Path(root) / filename
                    arcname = Path('media') / file_path.relative_to(media_root)
                    zf.write(file_path, arcname)

    return zip_path


def apply_retention_policy():
    """
    يحتفظ فقط بآخر BACKUP_RETENTION_COUNT نسخة احتياطية ويحذف الأقدم،
    حتى لا يمتلئ التخزين بمرور الوقت مع النسخ اليومية المجدولة.
    """
    retention_count = getattr(settings, 'BACKUP_RETENTION_COUNT', 30)
    backup_dir = get_backup_dir()

    backups = sorted(
        backup_dir.glob('cdms_backup_*.zip'),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    removed = []
    for old_backup in backups[retention_count:]:
        old_backup.unlink()
        removed.append(old_backup.name)

    return removed
