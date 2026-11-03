from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from .models import User

admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    ordering = ["-date_joined"]
    list_display = ["email", "email_verified", "gamertag", "full_name", "phone", "credit", "is_staff", "date_joined"]
    list_filter = ["email_verified", "is_staff", "is_active"]
    search_fields = ["email", "gamertag", "full_name", "phone"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Player", {"fields": ("gamertag", "full_name", "phone", "email_verified", "credit")}),
        ("Staff access", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
                          "description": "Tick “staff” to let someone log in to this desk. "
                                         "Give non-owners a role under Staff roles instead of superuser."}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",),
                             "fields": ("email", "gamertag", "full_name", "phone", "password1", "password2", "is_staff")}),)
