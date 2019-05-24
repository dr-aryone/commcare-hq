from __future__ import absolute_import
from __future__ import unicode_literals

from couchdbkit import ResourceNotFound
from django.contrib import messages
from django.http import Http404
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import ugettext_lazy
from memoized import memoized

from corehq.apps.domain.decorators import login_and_domain_required
from corehq.apps.export.const import FORM_EXPORT, CASE_EXPORT
from corehq.apps.export.views.new import BaseModifyNewCustomView
from corehq.apps.export.views.utils import DailySavedExportMixin, DashboardFeedMixin


class BaseEditNewCustomExportView(BaseModifyNewCustomView):

    @property
    def export_id(self):
        return self.kwargs.get('export_id')

    @property
    @memoized
    def new_export_instance(self):
        return self.export_instance_cls.get(self.export_id)

    @property
    def page_url(self):
        return reverse(self.urlname, args=[self.domain, self.export_id])

    def get(self, request, *args, **kwargs):
        try:
            export_instance = self.new_export_instance
        except ResourceNotFound:
            raise Http404()

        schema = self.get_export_schema(
            self.domain,
            self.request.GET.get('app_id') or getattr(export_instance, 'app_id'),
            export_instance.identifier
        )
        self.export_instance = self.export_instance_cls.generate_instance_from_schema(
            schema,
            saved_export=export_instance,
            # The export exists - we don't want to automatically select new columns
            auto_select=False,
        )
        for message in self.export_instance.error_messages():
            messages.error(request, message)
        return super(BaseEditNewCustomExportView, self).get(request, *args, **kwargs)

    @method_decorator(login_and_domain_required)
    def post(self, request, *args, **kwargs):
        try:
            new_export_instance = self.new_export_instance
        except ResourceNotFound:
            new_export_instance = None
        if (
            new_export_instance
            and not new_export_instance.can_edit(request.couch_user)
        ):
            raise Http404
        return super(BaseEditNewCustomExportView, self).post(request, *args, **kwargs)


class EditNewCustomFormExportView(BaseEditNewCustomExportView):
    urlname = 'edit_new_custom_export_form'
    page_title = ugettext_lazy("Edit Form Data Export")
    export_type = FORM_EXPORT


class EditNewCustomCaseExportView(BaseEditNewCustomExportView):
    urlname = 'edit_new_custom_export_case'
    page_title = ugettext_lazy("Edit Case Data Export")
    export_type = CASE_EXPORT


class EditCaseFeedView(DashboardFeedMixin, EditNewCustomCaseExportView):
    urlname = 'edit_case_feed_export'
    page_title = ugettext_lazy("Edit Case Feed")


class EditFormFeedView(DashboardFeedMixin, EditNewCustomFormExportView):
    urlname = 'edit_form_feed_export'
    page_title = ugettext_lazy("Edit Form Feed")


class EditCaseDailySavedExportView(DailySavedExportMixin, EditNewCustomCaseExportView):
    urlname = 'edit_case_daily_saved_export'


class EditFormDailySavedExportView(DailySavedExportMixin, EditNewCustomFormExportView):
    urlname = 'edit_form_daily_saved_export'


class EditODataCaseFeedView(EditNewCustomCaseExportView):
    urlname = 'edit_odata_case_feed'
    page_title = ugettext_lazy("Edit OData Case Feed")
