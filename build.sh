#!/usr/bin/env bash
# exit on error
set -o errexit

# 1. تثبيت المكتبات
pip install -r requirements.txt

# 2. السطر السحري الجديد لتوليد ملفات ترحيل قاعدة البيانات تلقائياً على السيرفر
python manage.py makemigrations --no-input

# 3. تجميع التنسيقات
python manage.py collectstatic --no-input

# 4. تطبيق التحديثات وبناء الجداول على السيرفر
python manage.py migrate
