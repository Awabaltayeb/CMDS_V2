from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),  # الرئيسية
    path('upload/', views.upload_document, name='upload_document'),  # شاشة الرفع
    path('document/<int:pk>/', views.document_detail, name='document_detail'),  # شاشة التفاصيل والتوجيه
    path('backup/download/', views.download_backup, name='download_backup'),  # تحميل نسخة احتياطية فورية
    path('logout/', views.user_logout, name='user_logout'),  # تسجيل الخروج المضمون
]
