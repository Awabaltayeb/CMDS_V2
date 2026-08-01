from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),  # الرئيسية
    path('upload/', views.upload_document, name='upload_document'),  # شاشة الرفع
    path('document/<int:pk>/', views.document_detail, name='document_detail'),  # شاشة التفاصيل والتوجيه
    path('document/<int:pk>/edit/', views.edit_document, name='edit_document'),  # شاشة تعديل المرتجع (ميزة الفكرة 3)
    path('backup/download/', views.download_backup, name='download_backup'),  # تحميل نسخة احتياطية فورية
    
    # مسار زرع البيانات وتصفية الجداول وتجاوز قيد الـ Shell
    path('setup-system-data/', views.create_admin_bypass, name='create_admin_bypass'),
    
    # مسار تعليم الإشعار كـ مقروء والتحويل التلقائي لصفحة تفاصيل المعاملة (ميزة الفكرة 2)
    path('notification/<int:pk>/read/', views.mark_notification_read, name='mark_notification_read'),
    
    path('logout/', views.user_logout, name='user_logout'),  # تسجيل الخروج المضمون
]
