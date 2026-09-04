import correspondence.models
import datetime
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('correspondence', '0006_directive_one_directive_per_correspondence'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='correspondence',
                    name='body_text',
                    field=models.TextField(blank=True, null=True, verbose_name='محتوى الخطاب النصي'),
                ),
                migrations.AddField(
                    model_name='correspondence',
                    name='is_confidential',
                    field=models.BooleanField(default=False, verbose_name='سري للغاية'),
                ),
                migrations.AddField(
                    model_name='correspondence',
                    name='return_reason',
                    field=models.TextField(blank=True, null=True, verbose_name='سبب الإرجاع لتصحيح البيانات'),
                ),
                migrations.CreateModel(
                    name='Notification',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('text', models.TextField(verbose_name='نص الإشعار')),
                        ('is_read', models.BooleanField(default=False, verbose_name='هل قُرِئ؟')),
                        ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإشعار')),
                        ('correspondence', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to='correspondence.correspondence', verbose_name='المعاملة المرتبطة')),
                        ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to=settings.AUTH_USER_MODEL, verbose_name='المستلم')),
                    ],
                    options={
                        'verbose_name': 'إشعار داخل النظام',
                        'verbose_name_plural': 'الإشعارات داخل النظام',
                    },
                ),
                migrations.CreateModel(
                    name='Conference',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('title', models.CharField(max_length=255, verbose_name='اسم المؤتمر / الفعالية')),
                        ('year', models.IntegerField(default=datetime.date.today().year, verbose_name='سنة المؤتمر')),
                        ('start_date', models.DateField(blank=True, null=True, verbose_name='تاريخ الانعقاد / البداية')),
                        ('end_date', models.DateField(blank=True, null=True, verbose_name='تاريخ الختام')),
                        ('location', models.CharField(default='كلية علوم الحاسوب وتقانة المعلومات - جامعة البطانة', max_length=200, verbose_name='مكان الانعقاد')),
                        ('description', models.TextField(blank=True, null=True, verbose_name='نبذة عن المؤتمر وأهدافه')),
                        ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='تاريخ التسجيل')),
                        ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_conferences', to=settings.AUTH_USER_MODEL, verbose_name='أنشئ بواسطة')),
                    ],
                    options={
                        'verbose_name': 'مؤتمر / فعالية',
                        'verbose_name_plural': 'المؤتمرات والفعاليات العلمية',
                        'ordering': ['-year', '-created_at'],
                    },
                ),
                migrations.CreateModel(
                    name='ConferenceDocument',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('title', models.CharField(max_length=255, verbose_name='عنوان الوثيقة / الورقة')),
                        ('document_type', models.CharField(choices=[('research_paper', 'ورقة علمية / بحث'), ('schedule', 'جدول الجلسات والبرنامج'), ('recommendations', 'التوصيات الختامية والقرارات'), ('speech', 'كلمة افتتاحية / ختامية'), ('presentation', 'عرض تقديمي (Slide/Presentation)'), ('report', 'تقرير إداري / مالي'), ('certificate', 'شهادة / تكريم'), ('other', 'مستند آخر')], default='research_paper', max_length=30, verbose_name='تصنيف الملف')),
                        ('author_or_presenter', models.CharField(blank=True, max_length=150, null=True, verbose_name='اسم الباحث / المتحدث / المعد')),
                        ('file', models.FileField(upload_to='conference_files/', validators=[django.core.validators.FileExtensionValidator(allowed_extensions=['pdf']), correspondence.models.validate_file_size], verbose_name='ملف المستند (PDF)')),
                        ('notes', models.TextField(blank=True, null=True, verbose_name='ملاحظات / نبذة')),
                        ('uploaded_at', models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الأرشفة')),
                        ('conference', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='documents', to='correspondence.conference', verbose_name='المؤتمر المرتبط')),
                        ('uploaded_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='conference_docs', to=settings.AUTH_USER_MODEL, verbose_name='تم الرفع بواسطة')),
                    ],
                    options={
                        'verbose_name': 'وثيقة مؤتمر',
                        'verbose_name_plural': 'وثائق وملفات المؤتمرات',
                        'ordering': ['-uploaded_at'],
                    },
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                    ALTER TABLE correspondence_correspondence ADD COLUMN IF NOT EXISTS body_text text;
                    ALTER TABLE correspondence_correspondence ADD COLUMN IF NOT EXISTS is_confidential boolean DEFAULT false;
                    ALTER TABLE correspondence_correspondence ADD COLUMN IF NOT EXISTS return_reason text;

                    CREATE TABLE IF NOT EXISTS correspondence_notification (
                        id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                        text text NOT NULL,
                        is_read boolean NOT NULL DEFAULT false,
                        created_at timestamp with time zone NOT NULL,
                        correspondence_id bigint NULL REFERENCES correspondence_correspondence(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
                        recipient_id integer NOT NULL REFERENCES auth_user(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
                    );

                    CREATE TABLE IF NOT EXISTS correspondence_conference (
                        id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                        title varchar(255) NOT NULL,
                        year integer NOT NULL,
                        start_date date NULL,
                        end_date date NULL,
                        location varchar(200) NOT NULL,
                        description text NULL,
                        created_at timestamp with time zone NOT NULL,
                        created_by_id integer NULL REFERENCES auth_user(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED
                    );

                    CREATE TABLE IF NOT EXISTS correspondence_conferencedocument (
                        id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                        title varchar(255) NOT NULL,
                        document_type varchar(30) NOT NULL,
                        author_or_presenter varchar(150) NULL,
                        file varchar(100) NOT NULL,
                        notes text NULL,
                        uploaded_at timestamp with time zone NOT NULL,
                        conference_id bigint NOT NULL REFERENCES correspondence_conference(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
                        uploaded_by_id integer NOT NULL REFERENCES auth_user(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
                    );
                    """,
                    reverse_sql="""
                    DROP TABLE IF EXISTS correspondence_conferencedocument;
                    DROP TABLE IF EXISTS correspondence_conference;
                    DROP TABLE IF EXISTS correspondence_notification;
                    """
                ),
            ]
        )
    ]
