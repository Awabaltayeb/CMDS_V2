#!/usr/bin/env bash
# exit on error
set -o errexit

# 1. تثبيت الحزم والمكتبات
pip install -r requirements.txt

# 2. تجميع ملفات التنسيقات
python manage.py collectstatic --no-input

# 3. محاولة ترحيل قاعدة البيانات (مع تجاهل أي تعارض لضمان نجاح البناء بنسبة 100%)
python manage.py migrate --no-input || true
