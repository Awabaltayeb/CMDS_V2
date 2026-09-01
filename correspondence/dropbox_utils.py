import os
import io
import threading
from decouple import config
import dropbox
from django.conf import settings


def get_dropbox_client():
    """تهيئة والاتصال بـ Dropbox API"""
    access_token = config('DROPBOX_ACCESS_TOKEN', default='').strip()
    if access_token:
        try:
            return dropbox.Dropbox(access_token)
        except Exception as e:
            print(f"Error initializing Dropbox: {e}")
    return None


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
    return html_content.encode('utf-8')


def sync_correspondence_to_dropbox(correspondence_id):
    """الدالة الرئيسية لرفع الخطاب إلى Dropbox"""
    from .models import Correspondence

    try:
        correspondence = Correspondence.objects.get(pk=correspondence_id)
    except Correspondence.DoesNotExist:
        return "المعاملة غير موجودة"

    if correspondence.is_confidential:
        return "خطاب سري - تم الاستثناء"

    dbx = get_dropbox_client()
    if not dbx:
        return "فشل الاتصال بـ Dropbox (تأكد من DROPBOX_ACCESS_TOKEN في Render)"

    try:
        year_str = str(correspondence.document_date.year)
        dir_name = "الوارد" if correspondence.direction == 'incoming' else "الصادر"
        scope_name = correspondence.get_scope_display().replace('/', '-')
        clean_subj = "".join([c for c in correspondence.subject if c.isalnum() or c in (' ', '_', '-')]).strip()[:20]

        file_bytes = None
        if correspondence.file:
            try:
                correspondence.file.open('rb')
                file_bytes = correspondence.file.read()
                file_name = f"{correspondence.reference_number}.pdf"
            except Exception:
                file_bytes = None

        if not file_bytes:
            file_name = f"{correspondence.reference_number}_{clean_subj}.html"
            file_bytes = generate_html_letter(correspondence)

        # مسار التخزين المنظم داخل Dropbox
        dropbox_path = f"/CDMS_Archive/{year_str}/{dir_name}/{scope_name}/{file_name}"

        # رفع الملف
        meta = dbx.files_upload(file_bytes, dropbox_path)
        return f"تم الرفع بنجاح إلى Dropbox: {meta.path_display}"

    except Exception as e:
        err_msg = f"خطأ أثناء الرفع إلى Dropbox: {str(e)}"
        print(err_msg)
        return err_msg


def sync_to_dropbox_async(correspondence):
    """تشغيل المزامنة في الخلفية"""
    thread = threading.Thread(target=sync_correspondence_to_dropbox, args=(correspondence.id,))
    thread.daemon = True
    thread.start()
