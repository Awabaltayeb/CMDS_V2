from django.contrib import admin
from django.urls import path, include
from correspondence import views as correspondence_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),  # مسارات تسجيل الدخول والخروج الافتراضية
    path('', include('correspondence.urls')),  # مسارات تطبيق المراسلات الخاص بنا
    
    # حماية وتأمين ملفات الـ PDF وسد ثغرة تسريب الميديا العامة برابط مباشر!
    path('media/correspondence_files/<str:filename>', correspondence_views.serve_protected_media, name='serve_protected_media'),
]
