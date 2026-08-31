import os
import io
import json
import threading
from decouple import config
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from django.conf import settings
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

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


def generate_text_letter_pdf(correspondence):
    """توليد ملف PDF في الذاكرة للخطابات النصية"""
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    p.setFont("Helvetica-Bold", 14)
    p.drawCentredString(width / 2.0, height - 50, "University of El Butana - Faculty of CS & IT")
    p.setFont("Helvetica", 10)
    p.drawString(50, height - 70, f"Ref: {correspondence.reference_number}")
    p.drawString(width - 150, height - 70, f"Date: {correspondence.document_date}")
    
    p.line(50, height - 80, width - 50, height - 80)
    
    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, height - 110, f"Subject: {correspondence.subject}")
    
    p.setFont("Helvetica", 11)
    text_object = p.beginText(50, height - 140)
    body = correspondence.body_text or correspondence.subject
    for line in body.split('\n'):
        text_object.textLine(line)
    p.drawText(text_object)
    
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer


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

        # 4. تحضير ملف الـ PDF للرفع
        file_name = f"{correspondence.reference_number}_{correspondence.subject[:30]}.pdf"
        
        if correspondence.file:
            file_path = os.path.join(settings.MEDIA_ROOT, correspondence.file.name)
            if os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    file_stream = io.BytesIO(f.read())
            else:
                file_stream = generate_text_letter_pdf(correspondence)
        else:
            file_stream = generate_text_letter_pdf(correspondence)

        media = MediaIoBaseUpload(file_stream, mimetype='application/pdf', resumable=True)
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
