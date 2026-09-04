import io
import json
from decouple import config
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_drive_service_with_status():
    """إنشاء اتصال Google Drive باستخدام OAuth 2.0 من متغير البيئة"""
    token_json = config("GDRIVE_OAUTH_TOKEN_JSON", default="").strip()

    if not token_json:
        return None, "لم يتم تعيين GDRIVE_OAUTH_TOKEN_JSON في Render"

    try:
        token_info = json.loads(token_json)
    except json.JSONDecodeError:
        return None, "GDRIVE_OAUTH_TOKEN_JSON غير صالح كـ JSON"

    try:
        creds = Credentials.from_authorized_user_info(
            token_info,
            SCOPES
        )

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())

        if not creds.valid:
            return None, "بيانات OAuth غير صالحة أو لا تحتوي على refresh_token."

        service = build(
            "drive",
            "v3",
            credentials=creds,
            cache_discovery=False
        )

        return service, "OK"

    except Exception as e:
        print(f"Google OAuth authentication error: {e}")
        return None, f"خطأ أثناء مصادقة Google OAuth: {str(e)}"


def _escape_drive_query_value(value):
    """حماية قيمة البحث داخل Google Drive query"""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
    )


def get_or_create_folder(service, folder_name, parent_folder_id):
    """البحث عن مجلد داخل parent وإنشاؤه إن لم يوجد"""
    safe_name = _escape_drive_query_value(folder_name)

    query = (
        "mimeType = 'application/vnd.google-apps.folder' "
        "and trashed = false "
        f"and name = '{safe_name}' "
        f"and '{parent_folder_id}' in parents"
    )

    results = (
        service.files()
        .list(
            q=query,
            spaces="drive",
            fields="files(id,name)",
            pageSize=10,
        )
        .execute()
    )

    files = results.get("files", [])

    if files:
        return files[0]["id"]

    folder_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_folder_id],
    }

    folder = (
        service.files()
        .create(
            body=folder_metadata,
            fields="id",
        )
        .execute()
    )

    return folder.get("id")


def _find_existing_file(service, file_name, parent_folder_id):
    """التأكد من عدم تكرار رفع الملف"""
    safe_name = _escape_drive_query_value(file_name)

    query = (
        f"name = '{safe_name}' "
        f"and '{parent_folder_id}' in parents "
        "and trashed = false"
    )

    results = (
        service.files()
        .list(
            q=query,
            spaces="drive",
            fields="files(id,name,webViewLink)",
            pageSize=10,
        )
        .execute()
    )

    files = results.get("files", [])
    return files[0] if files else None


def generate_html_letter(correspondence):
    """إنشاء نسخة HTML من المعاملة الإدارية إذا لم يكن لها ملف PDF"""
    sender_name = correspondence.created_by.username if correspondence.created_by else "غير محدد"
    sender_role = ""
    try:
        if correspondence.created_by and hasattr(correspondence.created_by, "profile"):
            sender_role = correspondence.created_by.profile.get_role_display()
    except Exception:
        sender_role = ""

    body = correspondence.body_text or correspondence.subject

    html_content = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>{correspondence.reference_number} - {correspondence.subject}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #ffffff; color: #111111; padding: 30px; margin: 0; }}
        .letter-box {{ border: 3px double #1a252f; border-radius: 6px; padding: 35px 30px; max-width: 800px; margin: auto; }}
        .header {{ text-align: center; border-bottom: 2px solid #1a252f; padding-bottom: 15px; margin-bottom: 25px; }}
        .meta-info {{ display: flex; justify-content: space-between; margin-bottom: 20px; font-size: 0.95rem; color: #555; border-bottom: 1px dashed #ddd; padding-bottom: 10px; }}
        .subject {{ text-align: center; font-size: 1.2rem; font-weight: bold; margin: 25px 0; text-decoration: underline; }}
        .body-text {{ font-size: 1.1rem; line-height: 2; white-space: pre-line; text-align: justify; min-height: 250px; }}
        .footer {{ margin-top: 40px; border-top: 1px dashed #ccc; padding-top: 20px; text-align: left; }}
        .signature-block {{ display: inline-block; text-align: center; }}
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
    <div class="subject">الموضوع: {correspondence.subject}</div>
    <div class="body-text">{body}</div>
    <div class="footer">
        <div class="signature-block">
            <p style="font-weight:bold; margin:0;">{sender_name}</p>
            <span style="font-size:0.9rem; color:#555;">{sender_role}</span>
            <p style="font-size:0.8rem; color:green; margin-top:5px;">التوقيع معتمد إلكترونياً ✓</p>
        </div>
    </div>
</div>
</body>
</html>"""
    stream = io.BytesIO(html_content.encode("utf-8"))
    stream.seek(0)
    return stream


def sync_correspondence_to_gdrive(correspondence_id):
    """رفع معاملة إدارية مؤرشفة إلى شجرة مجلدات الخطابات في Google Drive"""
    from .models import Correspondence

    try:
        correspondence = Correspondence.objects.get(pk=correspondence_id)
    except Correspondence.DoesNotExist:
        return "المعاملة غير موجودة"

    if correspondence.is_confidential:
        return "خطاب سري - تم الاستثناء"

    root_folder_id = config("GDRIVE_ROOT_FOLDER_ID", default="").strip()
    if not root_folder_id:
        return "لم يتم تعيين GDRIVE_ROOT_FOLDER_ID في Render"

    service, status_msg = get_drive_service_with_status()
    if not service:
        return status_msg

    file_stream = None
    try:
        year_str = str(correspondence.document_date.year)
        year_folder_id = get_or_create_folder(service, year_str, root_folder_id)

        dir_name = "الوارد (Incoming)" if correspondence.direction == "incoming" else "الصادر (Outgoing)"
        dir_folder_id = get_or_create_folder(service, dir_name, year_folder_id)

        scope_name = correspondence.get_scope_display()
        target_folder_id = get_or_create_folder(service, scope_name, dir_folder_id)

        subject = correspondence.subject or "document"
        clean_subj = "".join(c for c in subject if c.isalnum() or c in (" ", "_", "-")).strip()[:50]

        has_file = False
        if correspondence.file:
            try:
                correspondence.file.open("rb")
                file_bytes = correspondence.file.read()
                file_stream = io.BytesIO(file_bytes)
                file_name = f"{correspondence.reference_number}.pdf"
                mime_type = "application/pdf"
                has_file = True
            except Exception as e:
                print(f"Could not read file: {e}")
                has_file = False
            finally:
                try:
                    correspondence.file.close()
                except Exception:
                    pass

        if not has_file:
            file_name = f"{correspondence.reference_number}_{clean_subj}.html"
            mime_type = "text/html"
            file_stream = generate_html_letter(correspondence)

        file_stream.seek(0)

        existing = _find_existing_file(service, file_name, target_folder_id)
        if existing:
            return f"موجود مسبقاً: {existing.get('name', file_name)} (ID: {existing.get('id', '')})"

        media = MediaIoBaseUpload(file_stream, mimetype=mime_type, resumable=False)
        file_metadata = {
            "name": file_name,
            "parents": [target_folder_id],
        }

        uploaded_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id,name,webViewLink",
        ).execute()

        uploaded_name = uploaded_file.get("name", file_name)
        uploaded_id = uploaded_file.get("id", "")
        return f"تم الرفع بنجاح: {uploaded_name} (ID: {uploaded_id})"

    except Exception as e:
        error_message = f"خطأ أثناء الرفع إلى Google Drive: {str(e)}"
        print(f"Google Drive: {error_message}")
        return error_message
    finally:
        if file_stream:
            try:
                file_stream.close()
            except Exception:
                pass


def sync_to_gdrive_async(correspondence):
    return sync_correspondence_to_gdrive(correspondence.id)


# =========================================================
# 🏛️ أرشفة وثائق المؤتمرات إلى مجلد المؤتمرات المنفصل في Drive
# =========================================================

def sync_conference_doc_to_gdrive(document_id):
    """
    رفع وثيقة مؤتمر إلى مجلد المؤتمرات المنفصل في Google Drive:
    Root
     └── أرشيف المؤتمرات والفعاليات (Conferences)
          └── [السنة] - [اسم المؤتمر]
               └── [نوع المستند]
                    └── [الملف.pdf]
    """
    from .models import ConferenceDocument

    try:
        doc = ConferenceDocument.objects.get(pk=document_id)
    except ConferenceDocument.DoesNotExist:
        return "المستند غير موجود"

    if not doc.file:
        return "لا يوجد ملف PDF مرفق"

    root_folder_id = config("GDRIVE_ROOT_FOLDER_ID", default="").strip()
    if not root_folder_id:
        return "لم يتم تعيين GDRIVE_ROOT_FOLDER_ID في Render"

    service, status_msg = get_drive_service_with_status()
    if not service:
        return status_msg

    file_stream = None
    try:
        # 1. إنشاء أو جلب المجلد الرئيسي للمؤتمرات
        conf_main_folder_id = get_or_create_folder(service, "أرشيف المؤتمرات والفعاليات (Conferences)", root_folder_id)

        # 2. مجلد المؤتمر المحدد مع سنته
        conf_folder_name = f"{doc.conference.year} - {doc.conference.title}"
        conf_folder_id = get_or_create_folder(service, conf_folder_name, conf_main_folder_id)

        # 3. مجلد تصنيف الملف (مثال: الأوراق العلمية / التوصيات...)
        type_folder_name = doc.get_document_type_display()
        type_folder_id = get_or_create_folder(service, type_folder_name, conf_folder_id)

        # 4. تجهيز اسم الملف وقراءته
        clean_title = "".join(c for c in doc.title if c.isalnum() or c in (" ", "_", "-")).strip()[:60]
        file_name = f"{clean_title}.pdf"

        doc.file.open("rb")
        file_bytes = doc.file.read()
        file_stream = io.BytesIO(file_bytes)
        file_stream.seek(0)

        # منع التكرار
        existing = _find_existing_file(service, file_name, type_folder_id)
        if existing:
            return f"موجود مسبقاً في Drive: {file_name} (ID: {existing.get('id', '')})"

        media = MediaIoBaseUpload(file_stream, mimetype="application/pdf", resumable=False)
        file_metadata = {
            "name": file_name,
            "parents": [type_folder_id],
        }

        uploaded_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id,name,webViewLink",
        ).execute()

        return f"تم الرفع بنجاح إلى Drive: {uploaded_file.get('name')} (ID: {uploaded_file.get('id')})"

    except Exception as e:
        error_msg = f"خطأ أثناء رفع ملف المؤتمر إلى Google Drive: {str(e)}"
        print(error_msg)
        return error_msg
    finally:
        if file_stream:
            try:
                file_stream.close()
            except Exception:
                pass
        try:
            doc.file.close()
        except Exception:
            pass
