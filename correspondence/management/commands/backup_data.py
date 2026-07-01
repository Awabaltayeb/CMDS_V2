from django.core.management.base import BaseCommand
from correspondence.backup_utils import create_backup, apply_retention_policy


class Command(BaseCommand):
    help = 'ينشئ نسخة احتياطية كاملة (قاعدة البيانات + ملفات الخطابات) ويطبّق سياسة الاحتفاظ بآخر النسخ فقط.'

    def handle(self, *args, **options):
        zip_path = create_backup()
        size_mb = zip_path.stat().st_size / (1024 * 1024)
        self.stdout.write(self.style.SUCCESS(
            f'تم إنشاء نسخة احتياطية بنجاح: {zip_path.name} ({size_mb:.2f} ميجابايت)'
        ))

        removed = apply_retention_policy()
        if removed:
            self.stdout.write(f'تم حذف {len(removed)} نسخة قديمة تجاوزت حد الاحتفاظ: {", ".join(removed)}')
