import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.mail import send_mail
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
import uuid
from accounts.managers import CustomUserManager


class CustomGroup(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField("name", blank=False, null=False)
    created = models.DateTimeField(null=False, auto_now_add=True)
    updated = models.DateTimeField(null=False, auto_now=True)
    description = models.TextField(null=True, blank=True, default="")

    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="children_groups",
        null=True,
        blank=True,
        default=None,
    )
    hidden = models.BooleanField(default=False, null=False)

    @property
    def children(self):
        return self.children_groups

    def __str__(self):
        return f"{self.name}"


class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField("name", blank=False, null=False)
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)
    root = models.ForeignKey(
        CustomGroup, null=True, blank=False, on_delete=models.SET_NULL
    )

    def __str__(self):
        return f"{self.name}"


class CustomUser(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField("email address", unique=True)
    first_name = models.CharField("first name", max_length=30, blank=True)
    last_name = models.CharField("last name", max_length=30, blank=True)
    date_joined = models.DateTimeField("date joined", default=timezone.now)
    is_active = models.BooleanField("active", default=True)
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)
    is_staff = models.BooleanField("is staff", default=True)
    groups = models.ManyToManyField(
        CustomGroup,
        blank=False,
        related_name="members",
    )
    # user_permissions = models.ManyToManyField(
    #     to="auth.Permission",
    #     related_name="custom_users",
    #     blank=True,
    # )

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"
        ordering = ["email"]

    def get_full_name(self):
        """
        Returns the first_name plus the last_name, with a space in between.
        """
        full_name = "%s %s" % (self.first_name, self.last_name)
        return full_name.strip()

    def get_short_name(self):
        """
        Returns the short name for the user.
        """
        return self.first_name

    def email_user(self, subject, message, from_email=None, **kwargs):
        """
        Sends an email to this User.
        """
        send_mail(subject, message, from_email, [self.email], **kwargs)
