import io
import json
from decouple import config
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload


# Google Drive OAuth 2.0
# الملفات سترفع إلى Google Drive الخاص بالحساب الذي وافق على OAuth.
SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_drive_service_with_status():
    """
    إنشاء اتصال Google Drive باستخدام OAuth 2.0.

    يتم تخزين OAuth token داخل Render Environment Variable:
        GDRIVE_OAUTH_TOKEN_JSON
    """

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

        # تجديد Access Token تلقائياً عند انتهاء صلاحيته.
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())

        if not creds.valid:
            return None, (
                "بيانات OAuth غير صالحة أو لا تحتوي على refresh_token. "
                "قم بإعادة إنشاء OAuth token."
            )

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
    """
    حماية قيمة البحث داخل Google Drive query.
    """
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
    )


def get_or_create_folder(service, folder_name, parent_folder_id):
    """
    البحث عن مجلد داخل parent.
    إذا لم يكن موجوداً يتم إنشاؤه.
    """

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


def generate_html_letter(correspondence):
    """
    إنشاء نسخة HTML من المعاملة إذا لم يكن لها ملف PDF.
    """

    sender_name = (
        correspondence.created_by.username
        if correspondence.created_by
        else "غير محدد"
    )

    sender_role = ""

    try:
        if correspondence.created_by and hasattr(
            correspondence.created_by,
            "profile"
        ):
            sender_role = (
                correspondence.created_by.profile.get_role_display()
            )
    except Exception:
        sender_role = ""

    body = correspondence.body_text or correspondence.subject

    html_content = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">

<head>
    <meta charset="UTF-8">

    <title>
        {correspondence.reference_number} -
        {correspondence.subject}
    </title>

    <style>

        body {{
            font-family:
                'Segoe UI',
                Tahoma,
                Geneva,
                Verdana,
                sans-serif;

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

        .header h3 {{
            margin: 0 0 5px 0;
            color: #333;
        }}

        .header h4 {{
            margin: 0 0 5px 0;
            color: #0d6efd;
        }}

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

            line-height: 2;

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

        <p style="margin:0; font-size:0.9rem; color:#666;">
            جمهورية السودان
        </p>

        <h3>
            جامعة البطانة
        </h3>

        <h4>
            كلية علوم الحاسوب وتقانة المعلومات
        </h4>

        <p style="margin:5px 0 0 0; font-size:0.9rem;">
            نظام الأرشيف والمراسلات الإلكتروني (CDMS)
        </p>

    </div>


    <div class="meta-info">

        <div>
            <strong>الرقم المرجعي:</strong>
            {correspondence.reference_number}
        </div>

        <div>
            <strong>التاريخ:</strong>
            {correspondence.document_date}
        </div>

        <div>
            <strong>الاتجاه:</strong>
            {correspondence.get_direction_display()}
            ({correspondence.get_scope_display()})
        </div>

    </div>


    <div class="subject">

        الموضوع:
        {correspondence.subject}

    </div>


    <div class="body-text">

{body}

    </div>


    <div class="footer">

        <div class="signature-block">

            <p style="font-weight:bold; margin:0;">
                {sender_name}
            </p>

            <span style="font-size:0.9rem; color:#555;">
                {sender_role}
            </span>

            <p style="font-size:0.8rem; color:green; margin-top:5px;">
                التوقيع معتمد إلكترونياً ✓
            </p>

        </div>

    </div>

</div>

</body>

</html>
"""

    stream = io.BytesIO(
        html_content.encode("utf-8")
    )

    stream.seek(0)

    return stream


def _find_existing_file(service, file_name, parent_folder_id):
    """
    التأكد من أن الملف غير موجود مسبقاً
    قبل رفع نسخة جديدة.
    """

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


def sync_correspondence_to_gdrive(correspondence_id):
    """
    رفع معاملة مؤرشفة إلى Google Drive.

    الهيكل:

    Root
    └── السنة
        ├── الوارد (Incoming)
        │   └── المجال
        │       └── الملف
        │
        └── الصادر (Outgoing)
            └── المجال
                └── الملف
    """

    from .models import Correspondence

    # ---------------------------------------------------------
    # الحصول على المعاملة
    # ---------------------------------------------------------

    try:
        correspondence = Correspondence.objects.get(
            pk=correspondence_id
        )

    except Correspondence.DoesNotExist:
        return "المعاملة غير موجودة"


    # ---------------------------------------------------------
    # عدم رفع المعاملات السرية
    # ---------------------------------------------------------

    if correspondence.is_confidential:
        return "خطاب سري - تم الاستثناء"


    # ---------------------------------------------------------
    # الحصول على Root Folder
    # ---------------------------------------------------------

    root_folder_id = config(
        "GDRIVE_ROOT_FOLDER_ID",
        default=""
    ).strip()

    if not root_folder_id:
        return (
            "لم يتم تعيين GDRIVE_ROOT_FOLDER_ID في Render"
        )


    # ---------------------------------------------------------
    # الاتصال بـ Google Drive
    # ---------------------------------------------------------

    service, status_msg = get_drive_service_with_status()

    if not service:
        return status_msg


    file_stream = None

    try:

        # -----------------------------------------------------
        # إنشاء مجلد السنة
        # -----------------------------------------------------

        year_str = str(
            correspondence.document_date.year
        )

        year_folder_id = get_or_create_folder(
            service,
            year_str,
            root_folder_id
        )


        # -----------------------------------------------------
        # إنشاء مجلد الوارد / الصادر
        # -----------------------------------------------------

        if correspondence.direction == "incoming":

            dir_name = "الوارد (Incoming)"

        else:

            dir_name = "الصادر (Outgoing)"


        dir_folder_id = get_or_create_folder(
            service,
            dir_name,
            year_folder_id
        )


        # -----------------------------------------------------
        # إنشاء مجلد المجال
        # -----------------------------------------------------

        scope_name = (
            correspondence.get_scope_display()
        )

        target_folder_id = get_or_create_folder(
            service,
            scope_name,
            dir_folder_id
        )


        # -----------------------------------------------------
        # تجهيز اسم الملف
        # -----------------------------------------------------

        subject = correspondence.subject or "document"

        clean_subj = "".join(
            c
            for c in subject
            if c.isalnum()
            or c in (" ", "_", "-")
        ).strip()[:50]


        # -----------------------------------------------------
        # إذا كان هناك PDF فعلي
        # -----------------------------------------------------

        has_file = False

        if correspondence.file:

            try:

                correspondence.file.open("rb")

                file_bytes = correspondence.file.read()

                file_stream = io.BytesIO(
                    file_bytes
                )

                file_name = (
                    f"{correspondence.reference_number}.pdf"
                )

                mime_type = "application/pdf"

                has_file = True

            except Exception as e:

                print(
                    f"Could not read correspondence file: {e}"
                )

                has_file = False

            finally:

                try:
                    correspondence.file.close()
                except Exception:
                    pass


        # -----------------------------------------------------
        # إذا لم يوجد PDF
        # -----------------------------------------------------

        if not has_file:

            file_name = (
                f"{correspondence.reference_number}_"
                f"{clean_subj}.html"
            )

            mime_type = "text/html"

            file_stream = generate_html_letter(
                correspondence
            )


        file_stream.seek(0)


        # -----------------------------------------------------
        # منع التكرار
        # -----------------------------------------------------

        existing = _find_existing_file(
            service,
            file_name,
            target_folder_id
        )

        if existing:

            existing_name = existing.get(
                "name",
                file_name
            )

            existing_id = existing.get(
                "id",
                ""
            )

            return (
                f"موجود مسبقاً: {existing_name} "
                f"(ID: {existing_id})"
            )


        # -----------------------------------------------------
        # رفع الملف
        # -----------------------------------------------------

        media = MediaIoBaseUpload(
            file_stream,
            mimetype=mime_type,
            resumable=False
        )


        file_metadata = {
            "name": file_name,
            "parents": [target_folder_id],
        }


        uploaded_file = (
            service.files()
            .create(
                body=file_metadata,
                media_body=media,
                fields="id,name,webViewLink",
            )
            .execute()
        )


        uploaded_name = uploaded_file.get(
            "name",
            file_name
        )

        uploaded_id = uploaded_file.get(
            "id",
            ""
        )

        web_link = uploaded_file.get(
            "webViewLink"
        )


        if web_link:

            return (
                f"تم الرفع بنجاح: {uploaded_name} "
                f"(ID: {uploaded_id}) - {web_link}"
            )

        return (
            f"تم الرفع بنجاح: {uploaded_name} "
            f"(ID: {uploaded_id})"
        )


    except Exception as e:

        error_message = (
            f"خطأ أثناء الرفع إلى Google Drive: {str(e)}"
        )

        print(
            f"Google Drive: {error_message}"
        )

        return error_message


    finally:

        if file_stream:

            try:
                file_stream.close()
            except Exception:
                pass


def sync_to_gdrive_async(correspondence):
    """
    توافق مع الكود القديم.

    ملاحظة:
    لا يُنصح باستخدام Thread daemon للأرشفة
    على Render إذا كان المطلوب ضمان اكتمال الرفع.

    لذلك سيتم تنفيذ المزامنة بشكل مباشر من views.py.
    """

    return sync_correspondence_to_gdrive(
        correspondence.id
    )
