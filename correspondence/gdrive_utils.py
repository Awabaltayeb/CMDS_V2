import os
import io
import json
import threading
from decouple import config
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from django.conf import settings

SCOPES = ['https://www.googleapis.com/auth/drive']


def get_drive_service():
    """تهيئة والاتصال بـ Google Drive API باستخدام حساب الخدمة"""
    credentials_raw = config('GDRIVE_CREDENTIALS_JSON', default='')
    if not credentials_raw:
        return None
    try:
        service_account_info = json.loads(credentials_raw)
        creds = service_account.Credentials.from_service_account_info(
            service_account_info, scopes=SCOPES
        )
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Error initializing Google Drive Service: {e}")
        return None


def get_or_create_folder(service, folder_name, parent_folder_id):
    """البحث عن مجلد داخل مجلد أب، أو إنشاؤه إن لم يكن موجوداً"""
    query = (
        f"mimeType = 'application/vnd.google-apps.folder' and "
        f"name = '{folder_name}' and "
        f"'{parent_folder_id}' in parents and trashed = false"
    )
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    else:
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_folder_id]
        }
        folder = service.files().create(body=folder_metadata, fields='id').execute()
        return folder.get('id')


def generate_html_letter(correspondence):
    """توليد مستند HTML رسمي ومبروز يدعم اللغة العربية بالكامل"""
    sender_name = correspondence.created_by.username if correspondence.created_by else "غير محدد"
    sender_role = correspondence.created_by.profile.get_role_display() if hasattr(correspondence.created_by, 'profile') else ""
    body = correspondence.body_text or correspondence.subject

    html_content = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>{correspondence.reference_number} - {correspondence.subject}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #ffffff;
            color: #111111;
            padding: 30px;
            margin: 0;
        }}
        .letter-box {{
            border: 3px double #1a252f;
            border-radius: 6px;
            padding: 35px 30px;
            max-width: 800px;
            margin: auto;
        }}
        .header {{
            text-align: center;
            border-bottom: 2px solid #1a252f;
            padding-bottom: 15px;
            margin-bottom: 25px;
        }}
        .header h3 {{ margin: 0 0 5px 0; color: #333; }}
        .header h4 {{ margin: 0 0 5px 0; color: #0d6efd; }}
        .meta-info {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 20px;
            font-size: 0.95rem;
            color: #555;
            border-bottom: 1px dashed #ddd;
            padding-bottom: 10px;
        }}
        .subject {{
            text-align: center;
            font-size: 1.2rem;
            font-weight: bold;
            margin: 25px 0;
            text-decoration: underline;
        }}
        .body-text {{
            font-size: 1.1rem;
            line-height: 2.0;
            white-space: pre-line;
            text-align: justify;
            min-height: 250px;
        }}
        .footer {{
            margin-top: 40px;
            border-top: 1px dashed #ccc;
            padding-top: 20px;
            text-align: left;
        }}
        .signature-block {{
            display: inline-block;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="letter-box">
        <div class="header">
            <p style="margin:0; font-size:0.9rem; color:#666;">جمهورية السودان</p>
            <h3>جامعة البطانة</h3>
            <h4>كلية علوم الحاسوب وتقانة المعلومات</h4>
            <p style="margin:5px 0 0 0; font-size:0.9rem;">نظام الأرشيف والمراسلات الإلكتروني (CDMS)</p>
        </div>

        <div class="meta-info">
            <div><strong>الرقم المرجعي:</strong> {correspondence.reference_number}</div>
            <div><strong>التاريخ:</strong> {correspondence.document_date}</div>
            <div><strong>الاتجاه:</strong> {correspondence.get_direction_display()} ({correspondence.get_scope_display()})</div>
        </div>

        <div class="subject">
            الموضوع: {correspondence.subject}
        </div>

        <div class="body-text">
{body}
        </div>

        <div class="footer">
            <div class="signature-block">
                <p style="font-weight: bold; margin: 0;">{sender_name}</p>
                <span style="font-size: 0.9rem; color: #555;">{sender_role}</span>
                <p style="font-size: 0.8rem; color: green; margin-top: 5px;">التوقيع معتمد إلكترونياً ✓</p>
            </div>
        </div>
    </div>
</body>
</html>"""
    return io.BytesIO(html_content.encode('utf-8'))


def sync_correspondence_to_gdrive(correspondence_id):
    """الدالة الرئيسية لمزامنة الخطاب إلى Google Drive بالهيكلية المعتمدة"""
    from .models import Correspondence

    try:
        correspondence = Correspondence.objects.get(pk=correspondence_id)
    except Correspondence.DoesNotExist:
        return

    # استثناء الخطابات السرية تماماً
    if correspondence.is_confidential:
        return

    root_folder_id = config('GDRIVE_ROOT_FOLDER_ID', default='')
    if not root_folder_id:
        return

    service = get_drive_service()
    if not service:
        return

    try:
        # 1. إنشاء / جلب مجلد السنة (مثلاً: 2026)
        year_str = str(correspondence.document_date.year)
        year_folder_id = get_or_create_folder(service, year_str, root_folder_id)

        # 2. إنشاء / جلب مجلد الاتجاه (الوارد / الصادر)
        dir_name = "الوارد (Incoming)" if correspondence.direction == 'incoming' else "الصادر (Outgoing)"
        dir_folder_id = get_or_create_folder(service, dir_name, year_folder_id)

        # 3. إنشاء / جلب مجلد النطاق
        scope_name = correspondence.get_scope_display()
        target_folder_id = get_or_create_folder(service, scope_name, dir_folder_id)

        # 4. رفع الملف الفعلي
        if correspondence.file:
            file_name = f"{correspondence.reference_number}.pdf"
            mime_type = 'application/pdf'
            try:
                correspondence.file.open('rb')
                file_stream = io.BytesIO(correspondence.file.read())
            except Exception:
                file_path = os.path.join(settings.MEDIA_ROOT, correspondence.file.name)
                with open(file_path, 'rb') as f:
                    file_stream = io.BytesIO(f.read())
        else:
            file_name = f"{correspondence.reference_number}_{correspondence.subject[:25]}.html"
            mime_type = 'text/html'
            file_stream = generate_html_letter(correspondence)

        media = MediaIoBaseUpload(file_stream, mimetype=mime_type, resumable=True)
        file_metadata = {
            'name': file_name,
            'parents': [target_folder_id]
        }
        service.files().create(body=file_metadata, media_body=media, fields='id').execute()

    except Exception as e:
        print(f"Error syncing to Google Drive: {e}")


def sync_to_gdrive_async(correspondence):
    """تشغيل المزامنة في الخلفية دون تعطيل واجهة المستخدم"""
    thread = threading.Thread(target=sync_correspondence_to_gdrive, args=(correspondence.id,))
    thread.daemon = True
    thread.start()
