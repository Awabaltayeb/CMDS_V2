from django.apps import AppConfig

class CorrespondenceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'correspondence'
    verbose_name = 'إدارة المراسلات والأرشيف'  # تعريب الاسم الرئيسي في لوحة التحكم الإدارية
