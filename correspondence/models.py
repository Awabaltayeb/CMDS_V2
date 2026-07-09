import datetime
from django.db import models, transaction
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db.models.signals import post_save
from django.dispatch import receiver

MAX_UPLOAD_SIZE_MB = 5

def validate_file_size(file):
    limit_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file.size > limit_bytes:
        raise ValidationError(f'حجم الملف يتجاوز الحد الأقصى المسموح ({MAX_UPLOAD_SIZE_MB} ميجابايت).')

class UserProfile(models.Model):
    # إضافة الأدوار التفصيلية المعتمدة للمسجلين والكلية
    ROLE_CHOICES = [
        ('secretary', 'سكرتير'),
        ('dean', 'عميد الكلية'),
        ('vice_dean', 'نائب عميد الكلية'),
        ('general_registrar', 'المسجل العام للكلية'),
        ('student_registrar', 'مسجل شؤون الطلاب'),
        ('exams_registrar', 'مسجل الامتحانات'),
        ('department_head', 'رئيس قسم بالكلية'),
        ('faculty_member', 'أستاذ/أستاذة'),
    ]
    DEPT_CHOICES = [
        ('cs', 'علوم الحاسوب'),
        ('it', 'تقانة المعلومات'),
        ('is', 'نظم المعلومات'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile', verbose_name="المستخدم")
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default='faculty_member', verbose_name="الدور / الوظيفة")
    department = models.CharField(max_length=10, choices=DEPT_CHOICES, null=True, blank=True, verbose_name="القسم الأكاديمي")

    class Meta:
        verbose_name = "ملف شخصي"
        verbose_name_plural = "ملفات المستخدمين الشخصية"

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        UserProfile.objects.create(user=instance)
    instance.profile.save()

class ExternalEntity(models.Model):
    CAT_CHOICES = [
        ('other_faculty', 'كلية أخرى'),
        ('central_admin', 'إدارة مركزية'),
    ]
    name = models.CharField(max_length=100, verbose_name="اسم الجهة")
    category = models.CharField(max_length=20, choices=CAT_CHOICES, verbose_name="تصنيف الجهة")

    class Meta:
        verbose_name = "جهة خارجية"
        verbose_name_plural = "الجهات الخارجية"

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"

class ReferenceCounter(models.Model):
    direction = models.CharField(max_length=15)
    scope = models.CharField(max_length=15)
    year = models.IntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('direction', 'scope', 'year')

    @classmethod
    def get_next_number(cls, direction, scope, year):
        with transaction.atomic():
            counter, _ = cls.objects.select_for_update().get_or_create(
                direction=direction, scope=scope, year=year
            )
            counter.last_number += 1
            counter.save()
            return counter.last_number

class Correspondence(models.Model):
    DIR_CHOICES = [
        ('incoming', 'وارد'),
        ('outgoing', 'صادر'),
    ]
    SCOPE_CHOICES = [
        ('internal', 'داخلي'),
        ('inter_faculty', 'بين الكليات'),
        ('central_admin', 'إدارات مركزية'),
    ]
    ADDRESSED_CHOICES = [
        ('dean', 'العميد شخصياً'),
        ('faculty', 'الكلية (شخص محدد)'),
    ]
    STATUS_CHOICES = [
        ('uploaded', 'مرفوع'),
        ('pending_hod', 'قيد توصية رئيس القسم'),
        ('pending_g_registrar', 'قيد مراجعة المسجل العام'),
        ('pending_dean', 'قيد المراجعة عند العميد/نائبه'),
        ('assigned', 'موجه'),
        ('archived', 'منفذ / مؤرشف'),
    ]

    reference_number = models.CharField(max_length=50, unique=True, blank=True, verbose_name="الرقم المرجعي")
    direction = models.CharField(max_length=15, choices=DIR_CHOICES, verbose_name="الاتجاه")
    scope = models.CharField(max_length=15, choices=SCOPE_CHOICES, verbose_name="النطاق")
    addressed_to_type = models.CharField(max_length=10, choices=ADDRESSED_CHOICES, verbose_name="المخاطب الفعلي")
    subject = models.CharField(max_length=255, verbose_name="عنوان الخطاب / الموضوع")
    is_confidential = models.BooleanField(default=False, verbose_name="سري للغاية")  # حقل السرية الجديد
    
    sender_internal = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_correspondences', verbose_name="المرسل الداخلي")
    sender_external = models.ForeignKey(ExternalEntity, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_correspondences', verbose_name="المرسل الخارجي")
    
    recipient_internal = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_correspondences', verbose_name="المستلم الداخلي")
    recipient_external = models.ForeignKey(ExternalEntity, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_correspondences', verbose_name="المستلم الخارجي")
    
    file = models.FileField(
        upload_to='correspondence_files/',
        verbose_name="ملف الخطاب (PDF)",
        validators=[
            FileExtensionValidator(allowed_extensions=['pdf']),
            validate_file_size,
        ],
    )
    document_date = models.DateField(default=datetime.date.today, verbose_name="تاريخ الخطاب")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='uploaded', verbose_name="الحالة")
    
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_correspondences', verbose_name="أنشئ بواسطة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء في النظام")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")
    
    related_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies', verbose_name="مرتبط بخطاب سابق (رد)")
    handled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='handled_correspondences', verbose_name="تمت معالجته بواسطة")
    handled_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ المعالجة")

    class Meta:
        verbose_name = "مراسلة / خطاب"
        verbose_name_plural = "الخطابات والمراسلات"

    def save(self, *args, **kwargs):
        if not self.reference_number:
            dir_code = 'INC' if self.direction == 'incoming' else 'OUT'
            scope_code = 'INT' if self.scope == 'internal' else ('FAC' if self.scope == 'inter_faculty' else 'ADM')
            year = datetime.date.today().year
            count = ReferenceCounter.get_next_number(self.direction, self.scope, year)
            self.reference_number = f"{dir_code}-{scope_code}-{year}-{count:05d}"
        
        # التوجيه التلقائي الهرمي المطور لسرية مسارات الكلية:
        if self.status == 'uploaded':
            role = self.created_by.profile.role
            if role == 'faculty_member':
                self.status = 'pending_hod'  # يذهب أولاً لرئيس القسم
            elif role in ['student_registrar', 'exams_registrar']:
                self.status = 'pending_g_registrar'  # يذهب أولاً للمسجل العام
            else:
                self.status = 'pending_dean'  # يذهب للعميد مباشرة
                
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference_number} - {self.subject}"

class Directive(models.Model):
    correspondence = models.ForeignKey(Correspondence, on_delete=models.CASCADE, related_name='directives', verbose_name="الخطاب المرتبط")
    issued_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='issued_directives', verbose_name="أصدر بواسطة (العميد/النائب)")
    assigned_to = models.ForeignKey(User, on_delete=models.CASCADE, related_name='assigned_directives', verbose_name="موجه إلى (الموظف المستهدف)")
    directive_text = models.TextField(verbose_name="نص التوجيه الرقمي")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ صدور التوجيه")

    class Meta:
        verbose_name = "توجيه رقمي"
        verbose_name_plural = "التوجيهات الرقمية"
        constraints = [
            models.UniqueConstraint(fields=['correspondence'], name='one_directive_per_correspondence')
        ]

    def __str__(self):
        return f"توجيه على {self.correspondence.reference_number} إلى {self.assigned_to.username}"
