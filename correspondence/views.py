from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth import logout
from django.contrib import messages
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db import transaction
from django.http import FileResponse
from django.utils import timezone
from django.core.mail import send_mail
from .models import Correspondence, ExternalEntity, Directive
from .backup_utils import create_backup, apply_retention_policy

UPLOAD_ALLOWED_ROLES = ['secretary', 'dean', 'vice_dean', 'registrar', 'admin_supervisor', 'faculty_member']
DIRECTIVE_ALLOWED_ROLES = ['dean', 'vice_dean']

@login_required
def dashboard(request):
    user_profile = request.user.profile
    role = user_profile.role
    
    # 1. فلترة الخطابات بناءً على الهرمية والأدوار لسرية البيانات
    if role == 'secretary':
        correspondences = Correspondence.objects.all().order_by('-created_at')
    elif role in ['dean', 'vice_dean']:
        # العميد يرى كل الخطابات باستثناء المعاملات التي لا تزال في انتظار توصية رئيس القسم
        correspondences = Correspondence.objects.exclude(status='pending_hod').order_by('-created_at')
    elif role == 'department_head':
        # رئيس القسم يرى الخطابات الموجهة له + خطابات أساتذة قسمه التي تحتاج توصيته
        correspondences = Correspondence.objects.filter(
            Q(directives__assigned_to=request.user) |
            Q(status='pending_hod', created_by__profile__department=user_profile.department)
        ).distinct().order_by('-created_at')
    else:
        # الأستاذ والمسجل يريان فقط المعاملات الموجهة لهما
        correspondences = Correspondence.objects.filter(
            directives__assigned_to=request.user
        ).distinct().order_by('-created_at')

    # --- المجلدات الذكية (Smart Virtual Folders) ---
    folder = request.GET.get('folder', '')
    if folder:
        if folder in ['cs', 'it', 'is']:
            # مجلدات تصفية الأقسام الأكاديمية
            correspondences = correspondences.filter(created_by__profile__department=folder)
        elif folder == 'central_admin':
            # مجلد معاملات الإدارات المركزية
            correspondences = correspondences.filter(scope='central_admin')
        elif folder == 'inter_faculty':
            # مجلد المراسلات بين الكليات
            correspondences = correspondences.filter(scope='inter_faculty')
        elif folder == 'internal':
            # مجلد المراسلات الداخلية للكلية
            correspondences = correspondences.filter(scope='internal')

    # --- البحث والفلترة ---
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

        if not all([subject, direction, scope, addressed_to_type, document_file]):
            messages.error(request, 'يرجى تعبئة جميع الحقول المطلوبة وإرفاق الملف.')
            return redirect('upload_document')

        correspondence = Correspondence(
            subject=subject,
            direction=direction,
            scope=scope,
            addressed_to_type=addressed_to_type,
            file=document_file,
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


@login_required
def document_detail(request, pk):
    user_profile = request.user.profile
    correspondence = get_object_or_404(Correspondence, pk=pk)
    existing_directive = correspondence.directives.first()
    
    if request.method == 'POST':
        # أ. منطق أرشفة الموظف المعتاد
        if 'archive_document' in request.POST:
            if existing_directive and existing_directive.assigned_to == request.user:
                correspondence.status = 'archived'
                correspondence.save()
                messages.success(request, 'تم تنفيذ المعاملة وأرشفتها بنجاح.')
            else:
                messages.error(request, 'لا تملك صلاحية أرشفة هذه المعاملة.')
            return redirect('dashboard')

        # ب. منطق الأرشفة المباشرة للعميد دون إحالة
        elif 'direct_archive' in request.POST:
            if user_profile.role in DIRECTIVE_ALLOWED_ROLES:
                correspondence.status = 'archived'
                correspondence.handled_by = request.user
                correspondence.handled_at = timezone.now()
                correspondence.save()
                messages.success(request, 'تمت أرشفة المعاملة مباشرة دون توجيه بنجاح.')
            else:
                messages.error(request, 'لا تملك صلاحية أرشفة هذه المعاملة.')
            return redirect('dashboard')

        # ج. منطق التوصية والاعتماد لرئيس القسم (المسار الهرمي للأستاذ)
        elif 'hod_endorse' in request.POST:
            if user_profile.role == 'department_head' and correspondence.status == 'pending_hod':
                hod_note = request.POST.get('hod_note', '').strip()
                # البحث عن حساب العميد النشط في النظام لتوصية المعاملة له
                dean_user = User.objects.filter(profile__role='dean').first()
                
                if dean_user and hod_note:
                    with transaction.atomic():
                        # تسجيل توصية رئيس القسم في جدول التوجيهات
                        Directive.objects.create(
                            correspondence=correspondence,
                            issued_by=request.user,
                            assigned_to=dean_user,
                            directive_text="[توصية رئيس القسم]: " + hod_note
                        )
                        # تحويل الحالة لتذهب لصندوق وارد العميد
                        correspondence.status = 'pending_dean'
                        correspondence.save()
                    messages.success(request, 'تمت كتابة التوصية وإحالة المعاملة بنجاح إلى السيد العميد.')
                    return redirect('dashboard')
                else:
                    messages.error(request, 'يرجى كتابة نص التوصية.')

        # د. منطق توجيه العميد المعتاد
        else:
            if user_profile.role not in DIRECTIVE_ALLOWED_ROLES:
                messages.error(request, 'ليست لديك صلاحية إصدار توجيه رقمي على هذه المعاملة.')
                return redirect('dashboard')

            if correspondence.handled_by or correspondence.directives.exists():
                messages.error(request, 'تم التعامل مع هذه المعاملة مسبقاً.')
                return redirect('dashboard')
            
            assigned_to_id = request.POST.get('assigned_to')
            directive_text = request.POST.get('directive_text')
            
            if assigned_to_id and directive_text:
                assigned_to_user = get_object_or_404(User, pk=assigned_to_id)
                
                with transaction.atomic():
                    Directive.objects.create(
                        correspondence=correspondence,
                        issued_by=request.user,
                        assigned_to=assigned_to_user,
                        directive_text=directive_text
                    )
                    correspondence.status = 'assigned'
                    correspondence.handled_by = request.user
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

    staff_users = User.objects.exclude(profile__role__in=['secretary', 'dean', 'vice_dean'])
    context = {
        'correspondence': correspondence,
        'existing_directive': existing_directive,
        'staff_users': staff_users,
        'user_profile': user_profile,
    }
    return render(request, 'correspondence/document_detail.html', context)


def user_logout(request):
    logout(request)
    return redirect('login')
