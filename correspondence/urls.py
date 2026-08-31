from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('upload/', views.upload_document, name='upload_document'),
    path('document/<int:pk>/', views.document_detail, name='document_detail'),
    path('document/<int:pk>/edit/', views.edit_document, name='edit_document'),
    path('backup/download/', views.download_backup, name='download_backup'),
    path('generate-ai-letter/', views.generate_ai_letter, name='generate_ai_letter'),
    path('setup-system-data/', views.create_admin_bypass, name='create_admin_bypass'),
    path('notification/<int:pk>/read/', views.mark_notification_read, name='mark_notification_read'),
    path('sync-gdrive-all/', views.sync_all_archived_view, name='sync_all_archived_view'),
    path('logout/', views.user_logout, name='user_logout'),
]
