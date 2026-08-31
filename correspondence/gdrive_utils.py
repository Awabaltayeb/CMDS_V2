import os
import io
import threading
from decouple import config
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from django.conf import settings

SCOPES = ['https://www.googleapis.com/auth/drive']


def get_drive_service():
    """تهيئة والاتصال بـ Google Drive API باستخدام حسابك الشخصي (OAuth2)"""
    client_id = config('GDRIVE_CLIENT_ID', default='')
    client_secret = config('GDRIVE_CLIENT_SECRET', default='')
    refresh_token = config('GDRIVE_REFRESH_TOKEN', default='')

    if not all([client_id, client_secret, refresh_token]):
        return None

    try:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES
        )
        creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Error initializing OAuth Drive Service: {e}")
        return None


def get_or_create_folder(service, folder_name, parent_folder_id):
    """البحث عن مجلد داخل مجلد أب، أو إنشاؤه إن لم يكن موجوداً"""
    query = (
        f"mimeType = 'application/vnd.google-apps.folder' and "
        f"name = '{folder_name}' and "
        f"'{parent_folder_id}' in parents and trashed = false"
    )
    results = service.files().list(
        q=query, 
        spaces='drive', 
        fields='files(id, name)'
    ).execute()
    
    files = results.get('files', [])
    if files:
        return files[0]['id']
    else:
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_folder_id]
        }
        folder = service.files().create(
            body=folder_metadata, 
            fields='id'
        ).execute()
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
    stream = io.BytesIO(html_content.encode('utf-8'))
    stream.seek(0)
    return stream


def sync_correspondence_to_gdrive(correspondence_id):
    """الدالة الرئيسية لمزامنة الخطاب إلى Google Drive لحسابك الشخصي مباشرة"""
    from .models import Correspondence

    try:
        correspondence = Correspondence.objects.get(pk=correspondence_id)
    except Correspondence.DoesNotExist:
        return "المعاملة غير موجودة"

    if correspondence.is_confidential:
        return "خطاب سري - تم الاستثناء"

    root_folder_id = config('GDRIVE_ROOT_FOLDER_ID', default='')
    if not root_folder_id:
        return "لم يتم تعيين GDRIVE_ROOT_FOLDER_ID"

    service = get_drive_service()
    if not service:
        return "فشل الاتصال بـ Google Drive عبر OAuth"

    try:
        # 1. جلب مجلد السنة
        year_str = str(correspondence.document_date.year)
        year_folder_id = get_or_create_folder(service, year_str, root_folder_id)

        # 2. مجلد الاتجاه
        dir_name = "الوارد (Incoming)" if correspondence.direction == 'incoming' else "الصادر (Outgoing)"
        dir_folder_id = get_or_create_folder(service, dir_name, year_folder_id)

        # 3. مجلد النطاق
        scope_name = correspondence.get_scope_display()
        target_folder_id = get_or_create_folder(service, scope_name, dir_folder_id)

        # 4. تجهيز اسم وملف الرفع
        clean_subj = "".join([c for c in correspondence.subject if c.isalnum() or c in (' ', '_', '-')]).strip()[:20]
        
        has_file = False
        if correspondence.file:
            try:
                correspondence.file.open('rb')
                file_stream = io.BytesIO(correspondence.file.read())
                file_name = f"{correspondence.reference_number}.pdf"
                mime_type = 'application/pdf'
                has_file = True
            except Exception:
                has_file = False

        if not has_file:
            file_name = f"{correspondence.reference_number}_{clean_subj}.html"
            mime_type = 'text/html'
            file_stream = generate_html_letter(correspondence)

        file_stream.seek(0)
        media = MediaIoBaseUpload(file_stream, mimetype=mime_type, resumable=False)
        file_metadata = {
            'name': file_name,
            'parents': [target_folder_id]
        }
        
        uploaded_file = service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, name'
        ).execute()
        
        return f"تم الرفع بنجاح: {uploaded_file.get('name')} (ID: {uploaded_file.get('id')})"

    except Exception as e:
        err_msg = f"خطأ أثناء الرفع: {str(e)}"
        print(err_msg)
        return err_msg


def sync_to_gdrive_async(correspondence):
    """تشغيل المزامنة في الخلفية"""
    thread = threading.Thread(target=sync_correspondence_to_gdrive, args=(correspondence.id,))
    thread.daemon = True
    thread.start()
