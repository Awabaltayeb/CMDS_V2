import os
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth import logout
from django.contrib import messages
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db import transaction
from django.http import FileResponse, Http404
from django.utils import timezone
from django.core.mail import send_mail
from .models import Correspondence, ExternalEntity, Directive
from .backup_utils import create_backup, apply_retention_policy

# الأدوار المسموح لها برفع خطاب جديد إلى النظام
UPLOAD_ALLOWED_ROLES = ['secretary', 'dean', 'vice_dean', 'general_registrar', 'student_registrar', 'exams_registrar', 'faculty_member']
# الأدوار المسموح لها بإصدار توجيه رقمي (إحالة الخطاب لموظف)
DIRECTIVE_ALLOWED_ROLES = ['dean', 'vice_dean']


# 1. لوحة التحكم الرئيسية مع البحث والفلترة ومصفوفة الخصوصية الفائقة
@login_required
def dashboard(request):
    user_profile = request.user.profile
    role = user_profile.role
    user = request.user
    
    # قيد السرية الفائقة: العميد الفعلي يرى كل شيء. نائب العميد وبقية الموظفين لا يرون السري إلا لو كانوا هم المنشئون له.
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

    # مصفوفة الرؤية والفرز الهرمي بالتمام والكمال
    if role == 'secretary':
        correspondences = base_query.filter(
            Q(created_by=user) | Q(directives__assigned_to=user)
        ).distinct().order_by('-created_at')
        
    elif role in ['dean', 'vice_dean']:
        # الإدارة العليا ترى كل المعاملات الجاهزة لمراجعتها وتستبعد التي لا تزال عند رئيس القسم أو المسجل العام
        correspondences = base_query.exclude(
            status__in=['pending_hod', 'pending_g_registrar']
        ).order_by('-created_at')
        
    elif role == 'department_head':
        # يرى خطابات قسمه (سواء سرية أو عادية) التي بحاجة لتوصيته لتوجيهها
        department_professors_letters = Correspondence.objects.filter(
            status='pending_hod', 
            created_by__profile__department=user_profile.department
        )
        correspondences = (base_query.filter(
            Q(created_by=user) | Q(directives__assigned_to=user)
        ) | department_professors_letters).distinct().order_by('-created_at')
        
    elif role == 'general_registrar':
        # يرى خطابات مسجلي الطلاب والامتحانات قيد المراجعة لاعتمادها
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

    # مجلدات الأرشيف الديناميكية الذكية
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
    }
    return render(request, 'correspondence/dashboard.html', context)


# 1-ب. تحميل نسخة احتياطية فورية (للعميد والنائب فقط)
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


# 2. واجهة رفع الخطابات الرسمية
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
        is_confidential = request.POST.get('is_confidential') == 'on'

        if not all([subject, direction, scope, addressed_to_type, document_file]):
            messages.error(request, 'يرجى تعبئة جميع الحقول المطلوبة وإرفاق الملف.')
            return redirect('upload_document')

        correspondence = Correspondence(
            subject=subject,
            direction=direction,
            scope=scope,
            addressed_to_type=addressed_to_type,
            file=document_file,
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

        correspondence.save()
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


# 3. واجهة عرض التفاصيل والتوجيه الرقمي والأرشفة (سد ثغرة IDOR)
@login_required
def document_detail(request, pk):
    user_profile = request.user.profile
    role = user_profile.role
    user = request.user
    
    # سد ثغرة IDOR: جلب المعاملة فقط وحصرياً من نطاق رؤية الموظف المصرح له برمجياً لمنع التخمين العشوائي للروابط!
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
    
    # قيد السرية الفائقة: يمنع نائب العميد والجميع من الاطلاع على الخطاب السري، مسموح فقط للعميد الفعلي والمنشئ والمسؤول المستهدف بالتنفيذ
    if correspondence.is_confidential and role != 'dean' and correspondence.created_by != user:
        is_assigned = existing_directive and existing_directive.assigned_to == user
        if not is_assigned:
            messages.error(request, 'هذا الخطاب سري للغاية وغير مصرح لك بالاطلاع عليه.')
            return redirect('dashboard')

    if request.method == 'POST':
        # أ. منطق أرشفة الموظف الموجه إليه الخطاب
        if 'archive_document' in request.POST:
            if existing_directive and existing_directive.assigned_to == user:
                correspondence.status = 'archived'
                correspondence.save()
                messages.success(request, 'تم تنفيذ المعاملة وأرشفتها بنجاح.')
            else:
                messages.error(request, 'لا تملك صلاحية أرشفة هذه المعاملة.')
            return redirect('dashboard')

        # ب. منطق الأرشفة المباشرة للعميد/النائب دون توجيه
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

        # ج. منطق توصية رئيس القسم (مسار الأستاذ)
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
                    messages.success(request, 'تمت كتابة التوصية وإحالة المعاملة بنجاح إلى السيد العميد.')
                    return redirect('dashboard')
                else:
                    messages.error(request, 'يرجى كتابة نص التوصية.')

        # د. منطق اعتماد المسجل العام (مسار المسجلين الفرعيين)
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
                    messages.success(request, 'تم تدقيق واعتماد الخطاب وإحالته بنجاح إلى السيد العميد.')
                    return redirect('dashboard')
                else:
                    messages.error(request, 'يرجى كتابة ملاحظة الاعتماد والتدقيق.')

        # هـ. منطق التوجيه الرقمي للعميد/النائب
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

    staff_users = User.objects.exclude(profile__role__in=['secretary', 'dean', 'vice_dean'])
    
    context = {
        'correspondence': correspondence,
        'hod_directive': hod_directive,
        'reg_directive': reg_directive,
        'dean_directive': dean_directive,
        'staff_users': staff_users,
        'user_profile': user_profile,
    }
    return render(request, 'correspondence/document_detail.html', context)


# فيو مخصص ومحمي لمنع تسريب وتحميل ملفات الـ PDF بشكل غير مصرح (سد ثغرة الميديا العامة!)
@login_required
def serve_protected_media(request, filename):
    file_relative_path = f"correspondence_files/{filename}"
    correspondence = get_object_or_404(Correspondence, file=file_relative_path)
    
    user_profile = request.user.profile
    role = user_profile.role
    user = request.user
    
    # أ. فحص السرية الفائقة: إذا كان الخطاب سرياً، لا يفتح ملف الـ PDF إلا للعميد الفعلي والمنشئ والمسؤول المستهدف بالتنفيذ فقط
    if correspondence.is_confidential:
        existing_directive = correspondence.directives.first()
        is_assigned = existing_directive and existing_directive.assigned_to == user
        if role != 'dean' and correspondence.created_by != user and not is_assigned:
            raise Http404("غير مصرح لك بتحميل أو فتح هذا المستند السري.")

    # ب. فحص مصفوفة الرؤية والخصوصية العامة للموظفين لمنع أي تخطٍّ للملفات غير السرية
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


def user_logout(request):
    logout(request)
    return redirect('login')
