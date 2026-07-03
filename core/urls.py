from django.contrib import admin
from django.urls import path, include, re_path # أضفنا re_path هنا
from django.conf import settings
from django.views.static import serve # استدعاء دالة الخدمة الثابتة لتشغيل الميديا في الإنتاج

urlpatterns = [
path('admin/', admin.site.urls),
path('accounts/', include('django.contrib.auth.urls')), # مسارات تسجيل الدخول والخروج الافتراضية
path('', include('correspondence.urls')), # مسارات تطبيق المراسلات الخاص بنا
]

#كود إجبار دجانغو على قراءة وعرض ملفات الـ PDF المرفوعة على سيرفر Render حتى لو كان 
DEBUG=False
urlpatterns += [
re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]
