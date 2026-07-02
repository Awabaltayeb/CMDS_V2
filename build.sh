#!/usr/bin/env bash
# إيقاف التثبيت الفوري في حال حدوث أي مشكلة طارئة
set -o errexit

# تثبيت متطلبات بايثون الأساسية
pip install -r requirements.txt

# جمع الملفات الساكنة بكفاءة باستخدام WhiteNoise
python manage.py collectstatic --no-input

# تحديث بنية الجداول وقواعد البيانات
python manage.py migrate

# إنشاء مستخدم مسؤول تلقائياً في حال لم يكن موجوداً مسبقاً
python manage.py shell -c "from django.contrib.auth.models import User; User.objects.filter(username='admin').exists() or User.objects.create_superuser('admin', 'admin@college.edu', 'AdminPass123!')"
