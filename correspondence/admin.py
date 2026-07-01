from django.contrib import admin
from .models import UserProfile, ExternalEntity, Correspondence, Directive, ReferenceCounter

admin.site.register(UserProfile)
admin.site.register(ExternalEntity)
admin.site.register(Correspondence)
admin.site.register(Directive)
admin.site.register(ReferenceCounter)