import re
from django.db import migrations


def seed_counters(apps, schema_editor):
    """
    يمر على كل المراسلات الموجودة فعلياً، ويستخرج آخر رقم تسلسلي استُخدم
    لكل تركيبة (اتجاه + نطاق + سنة)، ثم يهيّئ ReferenceCounter ليبدأ من بعدها
    مباشرة بدل الصفر — حتى لا يتصادم مع أرقام مرجعية سابقة تم توليدها
    بالطريقة القديمة (count()) قبل هذا التحديث.
    """
    Correspondence = apps.get_model('correspondence', 'Correspondence')
    ReferenceCounter = apps.get_model('correspondence', 'ReferenceCounter')

    max_numbers = {}  # key: (direction, scope, year) -> أعلى رقم مستخدم

    for c in Correspondence.objects.all():
        match = re.search(r'-(\d+)$', c.reference_number or '')
        if not match:
            continue
        number = int(match.group(1))
        year = c.created_at.year if c.created_at else c.document_date.year
        key = (c.direction, c.scope, year)
        max_numbers[key] = max(max_numbers.get(key, 0), number)

    for (direction, scope, year), last_number in max_numbers.items():
        ReferenceCounter.objects.update_or_create(
            direction=direction, scope=scope, year=year,
            defaults={'last_number': last_number},
        )


def reverse_noop(apps, schema_editor):
    # لا حاجة لعكس هذه العملية؛ حذف السجلات المؤقتة غير ضروري
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('correspondence', '0003_alter_correspondence_file_referencecounter'),
    ]

    operations = [
        migrations.RunPython(seed_counters, reverse_noop),
    ]
