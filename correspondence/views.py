import os
import google.generativeai as genai
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth import logout
from django.contrib import messages
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.utils import timezone
from django.core.mail import send_mail

from .models import Correspondence, ExternalEntity, Directive, Comment, Notification
from .backup_utils import create_backup, apply_retention_policy

# الأدوار المسموح لها بالرفع 
UPLOAD_ALLOWED_ROLES = ['secretary', 'dean', 'vice_dean', 'general_registrar', 'student_registrar', 'exams_registrar', 'faculty_member']
# الأدوار المسموح لها بإصدار توجيه رقمي 
DIRECTIVE_ALLOWED_ROLES = ['dean', 'vice_dean']


@login_required
def dashboard(request):
    user_profile = request.user.profile
    role = user_profile.role
    user = request.user
    
    if role == 'dean':
        base_query = Correspondence.objects.all()
    elif role == 'vice_dean':
        base_query = Correspondence.objects.filter(
            Q(is_confidential=False) | Q(created_by=user)
        )
    else:
        base_query = Correspondence.objects.filter(
            Q(is_confidential=False) | Q(created_by=user)
        )

    if role == 'secretary':
        correspondences = base_query.filter(
            Q(created_by=user) | Q(directives__assigned_to=user)
        ).distinct().order_by('-created_at')
        
    elif role in ['dean', 'vice_dean']:
        correspondences = base_query.exclude(
            status__in=['pending_hod', 'pending_g_registrar']
        ).order_by('-created_at')
        
    elif role == 'department_head':
        department_professors_letters = Correspondence.objects.filter(
            status='pending_hod', 
            created_by__profile__department=user_profile.department
        )
        correspondences = (base_query.filter(
            Q(created_by=user) | Q(directives__assigned_to=user)
        ) | department_professors_letters).distinct().order_by('-created_at')
        
    elif role == 'general_registrar':
        sub_registrars_letters = Correspondence.objects.filter(
            status='pending_g_registrar',
            created_by__profile__role__in=['student_registrar', 'exams_registrar']
        )
        correspondences = (base_query.filter(
            Q(created_by=user) | Q(directives__assigned_to=user)
        ) | sub_registrars_letters).distinct().order_by('-created_at')
        
    else:
        correspondences = base_query.filter(
            Q(created_by=user) | Q(directives__assigned_to=user)
        ).distinct().order_by('-created_at')

    # مجلدات الأرشيف
    folder = request.GET.get('folder', '')
    if folder:
        if folder in ['cs', 'it', 'is']:
            correspondences = correspondences.filter(created_by__profile__department=folder)
        elif folder == 'central_admin':
            correspondences = correspondences.filter(scope='central_admin')
        elif folder == 'inter_faculty':
            correspondences = correspondences.filter(scope='inter_faculty')
        elif folder == 'internal':
            correspondences = correspondences.filter(scope='internal')

    # محرك البحث والفلترة
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '')
    direction_filter = request.GET.get('direction', '')
    scope_filter = request.GET.get('scope', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    if search_query:
        correspondences = correspondences.filter(
            Q(subject__icontains=search_query) |
            Q(reference_number__icontains=search_query) |
            Q(directives__directive_text__icontains=search_query)
        ).distinct()

    if status_filter:
        correspondences = correspondences.filter(status=status_filter)
    if direction_filter:
        correspondences = correspondences.filter(direction=direction_filter)
    if scope_filter:
        correspondences = correspondences.filter(scope=scope_filter)
    if date_from:
        correspondences = correspondences.filter(document_date__gte=date_from)
    if date_to:
        correspondences = correspondences.filter(document_date__lte=date_to)

    total_count = correspondences.count()
    pending_count = correspondences.filter(status__in=['pending_hod', 'pending_g_registrar', 'pending_dean']).count()
    archived_count = correspondences.filter(status='archived').count()

    active_notifications = user.notifications.filter(is_read=False).order_by('-created_at')[:5]
    unread_notifications_count = user.notifications.filter(is_read=False).count()

    context = {
        'correspondences': correspondences,
        'user_profile': user_profile,
        'upload_allowed_roles': UPLOAD_ALLOWED_ROLES,
        'backup_allowed_roles': settings.BACKUP_ALLOWED_ROLES,
        'status_choices': Correspondence.STATUS_CHOICES,
        'direction_choices': Correspondence.DIR_CHOICES,
        'scope_choices': Correspondence.SCOPE_CHOICES,
        'search_query': search_query,
        'status_filter': status_filter,
        'direction_filter': direction_filter,
        'scope_filter': scope_filter,
        'date_from': date_from,
        'date_to': date_to,
        'active_folder': folder,
        'total_count': total_count,
        'pending_count': pending_count,
        'archived_count': archived_count,
        'active_notifications': active_notifications,
        'unread_notifications_count': unread_notifications_count,
    }
    return render(request, 'correspondence/dashboard.html', context)


@login_required
def download_backup(request):
    user_profile = request.user.profile
    if user_profile.role not in settings.BACKUP_ALLOWED_ROLES:
        messages.error(request, 'ليست لديك صلاحية تحميل نسخة احتياطية من النظام.')
        return redirect('dashboard')
    zip_path = create_backup()
    apply_retention_policy()
    return FileResponse(
        open(zip_path, 'rb'),
        as_attachment=True,
        filename=zip_path.name,
        content_type='application/zip',
    )


@login_required
def upload_document(request):
    user_profile = request.user.profile
    if user_profile.role not in UPLOAD_ALLOWED_ROLES:
        messages.error(request, 'ليست لديك صلاحية رفع خطابات جديدة إلى النظام.')
        return redirect('dashboard')

    if request.method == 'POST':
        subject = request.POST.get('subject')
        direction = request.POST.get('direction')
        scope = request.POST.get('scope')
        addressed_to_type = request.POST.get('addressed_to_type')
        document_file = request.FILES.get('file')
        body_text = request.POST.get('body_text')
        is_confidential = request.POST.get('is_confidential') == 'on'

        if not all([subject, direction, scope, addressed_to_type]):
            messages.error(request, 'يرجى تعبئة جميع الحقول المطلوبة.')
            return redirect('upload_document')

        correspondence = Correspondence(
            subject=subject,
            direction=direction,
            scope=scope,
            addressed_to_type=addressed_to_type,
            file=document_file,
            body_text=body_text,
            is_confidential=is_confidential,
            created_by=request.user,
            status='uploaded'
        )
        
        sender_internal_id = request.POST.get('sender_internal')
        if sender_internal_id:
            correspondence.sender_internal_id = sender_internal_id
        sender_external_id = request.POST.get('sender_external')
        if sender_external_id:
            correspondence.sender_external_id = sender_external_id
        recipient_internal_id = request.POST.get('recipient_internal')
        if recipient_internal_id:
            correspondence.recipient_internal_id = recipient_internal_id
        recipient_external_id = request.POST.get('recipient_external')
        if recipient_external_id:
            correspondence.recipient_external_id = recipient_external_id

        try:
            correspondence.full_clean()
        except ValidationError as e:
            messages.error(request, ' '.join(sum(e.message_dict.values(), [])))
            return redirect('upload_document')

        with transaction.atomic():
            correspondence.save()
            
            # إرسال إشعار للمستوى الإداري الأعلى
            notify_user = None
            role = user_profile.role
            if role == 'faculty_member':
                notify_user = User.objects.filter(profile__role='department_head', profile__department=user_profile.department).first()
                text_msg = f"📥 قام الأستاذ {request.user.username} برفع معاملة جديدة بانتظار توصيتك: '{correspondence.subject}'."
            elif role in ['student_registrar', 'exams_registrar']:
                notify_user = User.objects.filter(profile__role='general_registrar').first()
                text_msg = f"📥 قام مسجل الفرع {request.user.username} برفع خطاب جديد بانتظار اعتمادك: '{correspondence.subject}'."
            else:
                notify_user = User.objects.filter(profile__role='dean').first()
                text_msg = f"📥 تم رفع خطاب جديد بانتظار مراجعتكم: '{correspondence.subject}'."
            
            if notify_user:
                Notification.objects.create(recipient=notify_user, text=text_msg, correspondence=correspondence)

        messages.success(request, f'تم رفع الخطاب بنجاح برقم مرجعي: {correspondence.reference_number}')
        return redirect('dashboard')
    
    users = User.objects.all()
    external_entities = ExternalEntity.objects.all()
    context = {
        'users': users,
        'external_entities': external_entities,
        'user_profile': user_profile,
    }
    return render(request, 'correspondence/upload_document.html', context)


@login_required
def edit_document(request, pk):
    """تعديل وإعادة إرسال الخطاب المرتجع لتصحيح البيانات"""
    correspondence = get_object_or_404(Correspondence, pk=pk)
    user_profile = request.user.profile

    # التحقق من أن المستخدم هو صاحب الخطاب الأصلي وأن الخطاب في حالة 'returned'
    if correspondence.created_by != request.user or correspondence.status != 'returned':
        messages.error(request, 'لا تملك صلاحية تعديل هذه المعاملة أو أنها ليست في حالة ارتجاع.')
        return redirect('dashboard')

    if request.method == 'POST':
        subject = request.POST.get('subject')
        direction = request.POST.get('direction')
        scope = request.POST.get('scope')
        addressed_to_type = request.POST.get('addressed_to_type')
        document_file = request.FILES.get('file')
        body_text = request.POST.get('body_text')

        if not all([subject, direction, scope, addressed_to_type]):
            messages.error(request, 'يرجى تعبئة الحقول الأساسية المطلوبة.')
            return redirect('edit_document', pk=pk)

        correspondence.subject = subject
        correspondence.direction = direction
        correspondence.scope = scope
        correspondence.addressed_to_type = addressed_to_type
        
        if document_file:
            correspondence.file = document_file
            correspondence.body_text = None
        elif body_text:
            correspondence.body_text = body_text

        correspondence.sender_internal_id = request.POST.get('sender_internal') or None
        correspondence.sender_external_id = request.POST.get('sender_external') or None
        correspondence.recipient_internal_id = request.POST.get('recipient_internal') or None
        correspondence.recipient_external_id = request.POST.get('recipient_external') or None

        # إعادة ضبط الحالة لمسار التدقيق من جديد
        role = user_profile.role
        if role == 'faculty_member':
            correspondence.status = 'pending_hod'
        elif role in ['student_registrar', 'exams_registrar']:
            correspondence.status = 'pending_g_registrar'
        else:
            correspondence.status = 'pending_dean'

        correspondence.return_reason = None  # تصفير سبب الإرجاع بعد المعالجة

        try:
            correspondence.full_clean()
        except ValidationError as e:
            messages.error(request, ' '.join(sum(e.message_dict.values(), [])))
            return redirect('edit_document', pk=pk)

        with transaction.atomic():
            correspondence.save()

            # إشعار المسؤول الأعلى بإعادة الرفع بعد التصحيح
            notify_user = None
            if role == 'faculty_member':
                notify_user = User.objects.filter(profile__role='department_head', profile__department=user_profile.department).first()
                text_msg = f"🔄 قام الأستاذ {request.user.username} بتصحيح وإعادة إرسال المعاملة: '{correspondence.subject}'."
            elif role in ['student_registrar', 'exams_registrar']:
                notify_user = User.objects.filter(profile__role='general_registrar').first()
                text_msg = f"🔄 قام المسجل {request.user.username} بتصحيح وإعادة إرسال المعاملة: '{correspondence.subject}'."
            else:
                notify_user = User.objects.filter(profile__role='dean').first()
                text_msg = f"🔄 تمت إعادة تقديم المعاملة المصححة للعمادة: '{correspondence.subject}'."

            if notify_user:
                Notification.objects.create(recipient=notify_user, text=text_msg, correspondence=correspondence)

        messages.success(request, 'تم تعديل وإعادة إرسال المعاملة بنجاح إلى مسار التدقيق.')
        return redirect('dashboard')

    users = User.objects.all()
    external_entities = ExternalEntity.objects.all()
    context = {
        'correspondence': correspondence,
        'users': users,
        'external_entities': external_entities,
        'user_profile': user_profile,
    }
    return render(request, 'correspondence/edit_document.html', context)


@login_required
def generate_ai_letter(request):
    """توليد صياغة رسمية للخطاب باستخدام Google Gemini AI"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'طلب غير مصرح به.'}, status=405)

    prompt = request.POST.get('prompt', '').strip()
    if not prompt:
        return JsonResponse({'success': False, 'error': 'يرجى تقديم فكرة أو موضوع الخطاب.'})

    api_key = getattr(settings, 'GOOGLE_API_KEY', '')
    if not api_key:
        return JsonResponse({'success': False, 'error': 'مفتاح GOOGLE_API_KEY غير مهيأ في إعدادات النظام.'})

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        system_instruction = (
            "أنت مساعد إداري محترف في كلية علوم الحاسوب وتقانة المعلومات. "
            "قم بصياغة خطاب إداري رسمي باللغة العربية الفصحى الرصينة، "
            "يتضمن: البسملة، التحية الرسمية، متن الخطاب بأسلوب إداري دقيق، "
            "والخاتمة الرسمية، بناءً على المعطيات التالية:\n"
        )
        
        response = model.generate_content(system_instruction + prompt)
        generated_text = response.text.strip()
        return JsonResponse({'success': True, 'text': generated_text})
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'فشل توليد الخطاب: {str(e)}'})


@login_required
def document_detail(request, pk):
    user_profile = request.user.profile
    role = user_profile.role
    user = request.user
    
    # حماية IDOR: استرجاع المعاملة من نطاق الرؤية المسموح به فقط
    if role == 'dean':
        allowed_queryset = Correspondence.objects.all()
    elif role == 'vice_dean':
        allowed_queryset = Correspondence.objects.filter(Q(is_confidential=False) | Q(created_by=user))
    elif role == 'secretary':
        allowed_queryset = Correspondence.objects.filter(Q(is_confidential=False) | Q(created_by=user) | Q(directives__assigned_to=user))
    elif role == 'department_head':
        allowed_queryset = Correspondence.objects.filter(
            Q(created_by=user) |
            Q(directives__assigned_to=user) |
            Q(created_by__profile__role='faculty_member', created_by__profile__department=user_profile.department)
        )
    elif role == 'general_registrar':
        allowed_queryset = Correspondence.objects.filter(
            Q(created_by=user) |
            Q(directives__assigned_to=user) |
            Q(created_by__profile__role__in=['student_registrar', 'exams_registrar'])
        )
    else:
        allowed_queryset = Correspondence.objects.filter(Q(created_by=user) | Q(directives__assigned_to=user))
        
    correspondence = get_object_or_404(allowed_queryset.distinct(), pk=pk)
    existing_directive = correspondence.directives.first()
    
    if correspondence.is_confidential and role != 'dean' and correspondence.created_by != user:
        is_assigned = existing_directive and existing_directive.assigned_to == user
        if not is_assigned:
            messages.error(request, 'هذا الخطاب سري للغاية وغير مصرح لك بالاطلاع عليه.')
            return redirect('dashboard')

    if request.method == 'POST':
        if 'add_comment' in request.POST:
            comment_text = request.POST.get('comment_text', '').strip()
            if comment_text:
                Comment.objects.create(
                    correspondence=correspondence,
                    author=user,
                    text=comment_text
                )
                messages.success(request, 'تم إضافة التعليق والتنسيق الداخلي بنجاح.')
            return redirect('document_detail', pk=pk)

        elif 'archive_document' in request.POST:
            if existing_directive and existing_directive.assigned_to == user:
                correspondence.status = 'archived'
                correspondence.save()
                messages.success(request, 'تم تنفيذ المعاملة وأرشفتها بنجاح.')
            else:
                messages.error(request, 'لا تملك صلاحية أرشفة هذه المعاملة.')
            return redirect('dashboard')

        elif 'direct_archive' in request.POST:
            if role in DIRECTIVE_ALLOWED_ROLES:
                correspondence.status = 'archived'
                correspondence.handled_by = user
                correspondence.handled_at = timezone.now()
                correspondence.save()
                messages.success(request, 'تمت أرشفة المعاملة مباشرة دون توجيه بنجاح.')
            else:
                messages.error(request, 'لا تملك صلاحية أرشفة هذه المعاملة.')
            return redirect('dashboard')

        elif 'return_document' in request.POST:
            return_reason = request.POST.get('return_reason', '').strip()
            if return_reason:
                with transaction.atomic():
                    correspondence.status = 'returned'
                    correspondence.return_reason = return_reason
                    correspondence.save()
                    
                    Notification.objects.create(
                        recipient=correspondence.created_by,
                        text=f"⚠️ تم إرجاع خطابك '{correspondence.subject}' من قِبل {request.user.username} لتصحيح البيانات. السبب: {return_reason}",
                        correspondence=correspondence
                    )
                messages.success(request, 'تم إرجاع المعاملة لتصحيح البيانات وإرسال إشعار لصاحب الخطاب.')
                return redirect('dashboard')
            else:
                messages.error(request, 'يرجى كتابة سبب الإرجاع بالتفصيل.')

        elif 'hod_endorse' in request.POST:
            if role == 'department_head' and correspondence.status == 'pending_hod':
                hod_note = request.POST.get('hod_note', '').strip()
                dean_user = User.objects.filter(profile__role='dean').first()
                
                if dean_user and hod_note:
                    with transaction.atomic():
                        Directive.objects.create(
                            correspondence=correspondence,
                            issued_by=user,
                            assigned_to=dean_user,
                            directive_text="[توصية رئيس القسم]: " + hod_note
                        )
                        correspondence.status = 'pending_dean'
                        correspondence.save()
                        
                        Notification.objects.create(
                            recipient=dean_user,
                            text=f"📨 تم اعتماد خطاب الأستاذ وإحالته إليكم بتوصية رئيس القسم: '{correspondence.subject}'.",
                            correspondence=correspondence
                        )
                    messages.success(request, 'تمت كتابة التوصية وإحالة المعاملة بنجاح إلى السيد العميد.')
                    return redirect('dashboard')
                else:
                    messages.error(request, 'يرجى كتابة نص التوصية.')

        elif 'registrar_approve' in request.POST:
            if role == 'general_registrar' and correspondence.status == 'pending_g_registrar':
                reg_note = request.POST.get('reg_note', '').strip()
                dean_user = User.objects.filter(profile__role='dean').first()
                
                if dean_user and reg_note:
                    with transaction.atomic():
                        Directive.objects.create(
                            correspondence=correspondence,
                            issued_by=user,
                            assigned_to=dean_user,
                            directive_text="[اعتماد المسجل العام للكلية]: " + reg_note
                        )
                        correspondence.status = 'pending_dean'
                        correspondence.save()
                        
                        Notification.objects.create(
                            recipient=dean_user,
                            text=f"📨 تم اعتماد خطاب المسجل الفرعي وإحالته إليكم بعد تدقيق المسجل العام: '{correspondence.subject}'.",
                            correspondence=correspondence
                        )
                    messages.success(request, 'تم تدقيق واعتماد الخطاب وإحالته بنجاح إلى السيد العميد.')
                    return redirect('dashboard')
                else:
                    messages.error(request, 'يرجى كتابة ملاحظة الاعتماد والتدقيق.')

        else:
            if role not in DIRECTIVE_ALLOWED_ROLES:
                messages.error(request, 'ليست لديك صلاحية إصدار توجيه رقمي على هذه المعاملة.')
                return redirect('dashboard')

            if correspondence.handled_by:
                messages.error(request, 'تم التعامل مع هذه المعاملة مسبقاً.')
                return redirect('dashboard')
            
            assigned_to_id = request.POST.get('assigned_to')
            directive_text = request.POST.get('directive_text')
            
            if assigned_to_id and directive_text:
                assigned_to_user = get_object_or_404(User, pk=assigned_to_id)
                
                with transaction.atomic():
                    Directive.objects.create(
                        correspondence=correspondence,
                        issued_by=user,
                        assigned_to=assigned_to_user,
                        directive_text=directive_text
                    )
                    correspondence.status = 'assigned'
                    correspondence.handled_by = user
                    correspondence.handled_at = timezone.now()
                    correspondence.save()
                    
                    Notification.objects.create(
                        recipient=assigned_to_user,
                        text=f"📨 تم توجيه معاملة جديدة إليك من قِبل السيد العميد: '{correspondence.subject}'.",
                        correspondence=correspondence
                    )
                
                try:
                    send_mail(
                        subject='توجيه جديد بخصوص خطاب: ' + correspondence.subject,
                        message=f'مرحباً {assigned_to_user.username}، تم توجيه معاملة جديدة إليك من قِبل العميد. نص التوجيه: {directive_text}.',
                        from_email='archive-system@college.edu',
                        recipient_list=[assigned_to_user.email],
                        fail_silently=True,
                    )
                except Exception:
                    pass
                
                messages.success(request, 'تم اعتماد التوجيه وإحالة المعاملة بنجاح.')
                return redirect('dashboard')
            else:
                messages.error(request, 'يرجى اختيار الموظف المستهدف وكتابة نص التوجيه.')

    hod_directive = correspondence.directives.filter(issued_by__profile__role='department_head').first()
    reg_directive = correspondence.directives.filter(issued_by__profile__role='general_registrar').first()
    dean_directive = correspondence.directives.filter(issued_by__profile__role__in=['dean', 'vice_dean']).first()
    comments = correspondence.comments.all().order_by('created_at')

    active_notifications = user.notifications.filter(is_read=False).order_by('-created_at')[:5]
    unread_notifications_count = user.notifications.filter(is_read=False).count()

    staff_users = User.objects.exclude(profile__role__in=['secretary', 'dean', 'vice_dean'])
    
    context = {
        'correspondence': correspondence,
        'hod_directive': hod_directive,
        'reg_directive': reg_directive,
        'dean_directive': dean_directive,
        'comments': comments,
        'staff_users': staff_users,
        'user_profile': user_profile,
        'active_notifications': active_notifications,
        'unread_notifications_count': unread_notifications_count,
    }
    return render(request, 'correspondence/document_detail.html', context)


@login_required
def serve_protected_media(request, filename):
    file_relative_path = f"correspondence_files/{filename}"
    correspondence = get_object_or_404(Correspondence, file=file_relative_path)
    
    user_profile = request.user.profile
    role = user_profile.role
    user = request.user
    
    if correspondence.is_confidential:
        existing_directive = correspondence.directives.first()
        is_assigned = existing_directive and existing_directive.assigned_to == user
        if role != 'dean' and correspondence.created_by != user and not is_assigned:
            raise Http404("غير مصرح لك بتحميل أو فتح هذا المستند السري.")

    is_authorized = False
    if role in ['dean', 'vice_dean', 'secretary']:
        is_authorized = True
    elif role == 'department_head':
        if (correspondence.created_by == user or 
            correspondence.directives.filter(assigned_to=user).exists() or 
            (correspondence.created_by.profile.role == 'faculty_member' and correspondence.created_by.profile.department == user_profile.department)):
            is_authorized = True
    elif role == 'general_registrar':
        if (correspondence.created_by == user or 
            correspondence.directives.filter(assigned_to=user).exists() or 
            (correspondence.created_by.profile.role in ['student_registrar', 'exams_registrar'])):
            is_authorized = True
    else:
        if correspondence.created_by == user or correspondence.directives.filter(assigned_to=user).exists():
            is_authorized = True
            
    if not is_authorized:
        raise Http404("غير مصرح لك بالاطلاع على ملف هذا الخطاب.")
        
    file_path = os.path.join(settings.MEDIA_ROOT, file_relative_path)
    if os.path.exists(file_path):
        return FileResponse(open(file_path, 'rb'), content_type='application/pdf')
    raise Http404("المستند غير موجود على السيرفر.")


@login_required
def mark_notification_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.is_read = True
    notification.save()
    return redirect('document_detail', pk=notification.correspondence.id)


def create_admin_bypass(request):
    """
    دالة آمنة لزرع الحسابات التجريبية فقط إذا لم تكن موجودة.
    """
    if not User.objects.filter(username='awab').exists():
        user = User.objects.create_superuser('awab', 'awab@mail.com', '123')
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = 'dean'
        profile.save()
        
    if not User.objects.filter(username='secretary_user').exists():
        user = User.objects.create_user('secretary_user', 'sec@mail.com', '123')
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = 'secretary'
        profile.save()

    if not User.objects.filter(username='registrar_user').exists():
        user = User.objects.create_user('registrar_user', 'reg@mail.com', '123')
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = 'general_registrar'
        profile.save()

    if not User.objects.filter(username='prof_asma').exists():
        user = User.objects.create_user('prof_asma', 'asma@mail.com', '123')
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = 'faculty_member'
        profile.save()
        
    ExternalEntity.objects.get_or_create(name='الشؤون العلمية بالجامعة', category='central_admin')
    ExternalEntity.objects.get_or_create(name='كلية الاقتصاد والعلوم الإدارية', category='other_faculty')
    ExternalEntity.objects.get_or_create(name='عمادة المكتبات المركزية', category='central_admin')

    return render(request, 'registration/login.html', {
        'form': {},
        'message_success': '✓ تم تجهيز الحسابات الأولية بنجاح! حساب العميد هو awab وكلمة المرور 123.'
    })


def user_logout(request):
    logout(request)
    return redirect('login')
