from django.contrib import admin
from django.contrib.auth.models import Group  # استدعاء موديل المجموعات الافتراضي
from .models import UserProfile, ExternalEntity

# إلغاء تسجيل جدول "المجموعات" الافتراضي لإخفائه من لوحة التحكم ومنع تشتيت موظف الـ IT
try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:
    pass

# تسجيل الجداول المصرح لمهندس الـ IT إدارتها فقط (المستخدمون والجهات الخارجية)
admin.site.register(UserProfile)
admin.site.register(ExternalEntity)
