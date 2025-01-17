import logging
import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

from assets.models import Asset, Account
from common.db.models import UnionQuerySet
from common.utils import date_expired_default
from orgs.mixins.models import OrgManager
from orgs.mixins.models import OrgModelMixin
from perms.const import ActionChoices

__all__ = ['AssetPermission', 'ActionChoices']

# 使用场景
logger = logging.getLogger(__name__)


class AssetPermissionQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def valid(self):
        return self.active().filter(date_start__lt=timezone.now()) \
            .filter(date_expired__gt=timezone.now())

    def inactive(self):
        return self.filter(is_active=False)

    def invalid(self):
        now = timezone.now()
        q = (Q(is_active=False) | Q(date_start__gt=now) | Q(date_expired__lt=now))
        return self.filter(q)

    def filter_by_accounts(self, accounts):
        q = Q(accounts__contains=list(accounts)) | \
            Q(accounts__contains=Account.AliasAccount.ALL.value)
        return self.filter(q)


class AssetPermissionManager(OrgManager):
    def valid(self):
        return self.get_queryset().valid()


class AssetPermission(OrgModelMixin):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    users = models.ManyToManyField(
        'users.User', related_name='%(class)ss', blank=True, verbose_name=_("User")
    )
    user_groups = models.ManyToManyField(
        'users.UserGroup', related_name='%(class)ss', blank=True, verbose_name=_("User group")
    )
    assets = models.ManyToManyField(
        'assets.Asset', related_name='granted_by_permissions', blank=True, verbose_name=_("Asset")
    )
    nodes = models.ManyToManyField(
        'assets.Node', related_name='granted_by_permissions', blank=True, verbose_name=_("Nodes")
    )
    # 特殊的账号: @ALL, @INPUT @USER 默认包含，将来在全局设置中进行控制.
    accounts = models.JSONField(default=list, verbose_name=_("Accounts"))
    actions = models.IntegerField(default=ActionChoices.connect, verbose_name=_("Actions"))
    date_start = models.DateTimeField(default=timezone.now, db_index=True, verbose_name=_("Date start"))
    date_expired = models.DateTimeField(
        default=date_expired_default, db_index=True, verbose_name=_('Date expired')
    )
    comment = models.TextField(verbose_name=_('Comment'), blank=True)
    is_active = models.BooleanField(default=True, verbose_name=_('Active'))
    from_ticket = models.BooleanField(default=False, verbose_name=_('From ticket'))
    date_created = models.DateTimeField(auto_now_add=True, verbose_name=_('Date created'))
    created_by = models.CharField(max_length=128, blank=True, verbose_name=_('Created by'))

    objects = AssetPermissionManager.from_queryset(AssetPermissionQuerySet)()

    class Meta:
        unique_together = [('org_id', 'name')]
        verbose_name = _("Asset permission")
        ordering = ('name',)
        permissions = []

    def __str__(self):
        return self.name

    @property
    def is_expired(self):
        if self.date_expired > timezone.now() > self.date_start:
            return False
        return True

    @property
    def is_valid(self):
        if not self.is_expired and self.is_active:
            return True
        return False

    def get_all_users(self):
        from users.models import User
        user_ids = self.users.all().values_list('id', flat=True)
        group_ids = self.user_groups.all().values_list('id', flat=True)
        user_ids = list(user_ids)
        group_ids = list(group_ids)
        qs1 = User.objects.filter(id__in=user_ids).distinct()
        qs2 = User.objects.filter(groups__id__in=group_ids).distinct()
        qs = UnionQuerySet(qs1, qs2)
        return qs

    def get_all_assets(self, flat=False):
        from assets.models import Node
        nodes_keys = self.nodes.all().values_list('key', flat=True)
        asset_ids = set(self.assets.all().values_list('id', flat=True))
        nodes_asset_ids = Node.get_nodes_all_asset_ids_by_keys(nodes_keys)
        asset_ids.update(nodes_asset_ids)
        if flat:
            return asset_ids
        assets = Asset.objects.filter(id__in=asset_ids)
        return assets

    def get_all_accounts(self, flat=False):
        """
         :return: 返回授权的所有账号对象 Account
        """
        asset_ids = self.get_all_assets(flat=True)
        q = Q(asset_id__in=asset_ids)
        if Account.AliasAccount.ALL not in self.accounts:
            q &= Q(username__in=self.accounts)
        accounts = Account.objects.filter(q).order_by('asset__name', 'name', 'username')
        if not flat:
            return accounts
        return accounts.values_list('id', flat=True)
