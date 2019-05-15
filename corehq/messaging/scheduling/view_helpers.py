from __future__ import absolute_import
from __future__ import unicode_literals

from django.contrib import messages
from django.utils.translation import ugettext as _

from corehq.apps.data_interfaces.models import AutomaticUpdateRule
from corehq.messaging.scheduling.forms import (
    ContentForm,
    ConditionalAlertCriteriaForm,
    ConditionalAlertScheduleForm,
    save_schedule,
)
from corehq.messaging.scheduling.models.content import SMSContent
from corehq import toggles


def get_conditional_alerts_queryset_by_domain(domain, query_string=''):
    query = (
        AutomaticUpdateRule
        .objects
        .filter(domain=domain, workflow=AutomaticUpdateRule.WORKFLOW_SCHEDULING, deleted=False)
    )
    if query_string:
        query = query.filter(name__icontains=query_string)
    query = query.order_by('case_type', 'name', 'id')
    return query

def get_conditional_alert_rows(domain, langs):
    translated_rows = []
    untranslated_rows = []

    for rule in get_conditional_alerts_queryset_by_domain(domain):
        if not isinstance(_get_rule_content(rule), SMSContent):
            continue
        common_columns = [rule.pk, rule.name, rule.case_type]
        message = ContentForm.compute_initial(
            rule.get_messaging_rule_schedule().memoized_events[0].content
        ).get('message', {})
        if '*' in message or len(message) == 0:
            untranslated_rows.append(common_columns + [message.get('*', '')])
        else:
            translated_rows.append(common_columns + [message.get(lang, '') for lang in langs])

    return (translated_rows, untranslated_rows)


def upload_conditional_alert_workbook(domain, langs, workbook, is_system_admin=False, can_use_inbound_sms=False):
    args = [domain, langs]
    kwargs = {
        'is_system_admin': is_system_admin,
        'can_use_inbound_sms': can_use_inbound_sms,
    }
    translated_uploader = TranslatedConditionalAlertUploader(*args, **kwargs)
    untranslated_uploader = UntranslatedConditionalAlertUploader(*args, **kwargs)
    return translated_uploader.upload(workbook) + untranslated_uploader.upload(workbook)


class ConditionalAlertUploader(object):
    sheet_name = None

    def __init__(self, domain, langs, is_system_admin=False, can_use_inbound_sms=False):
        super(ConditionalAlertUploader, self).__init__()
        self.domain = domain
        self.langs = langs
        self.is_system_admin = is_system_admin
        self.can_use_inbound_sms = can_use_inbound_sms
        self.msgs = []

    def applies_to_rule(self, rule):
        return True

    def rule_message(self, rule):
        return ContentForm.compute_initial(
            rule.get_messaging_rule_schedule().memoized_events[0].content
        ).get('message', {})

    def upload(self, workbook):
        self.msgs = []
        success_count = 0
        rows = workbook.get_worksheet(title=self.sheet_name)

        for index, row in enumerate(rows, start=2):    # one-indexed, plus header row
            rule = None
            try:
                rule = AutomaticUpdateRule.objects.get(
                    pk=row['id'],
                    domain=self.domain,
                    workflow=AutomaticUpdateRule.WORKFLOW_SCHEDULING,
                    deleted=False,
                )
            except AutomaticUpdateRule.DoesNotExist:
                self.msgs.append((messages.error,
                                 _("""Could not find rule for row {index} in '{sheet_name}' sheet, """
                                   """with id {id}""").format(index=index,
                                                              id=row['id'],
                                                              sheet_name=self.sheet_name)))

            if rule:
                if not isinstance(_get_rule_content(rule), SMSContent):
                    self.msgs.append((messages.error, _("Row {index} in '{sheet_name}' sheet, with rule id {id}, "
                                      "does not use SMS content.").format(index=index, id=row['id'],
                                                                          sheet_name=self.sheet_name)))
                elif self.applies_to_rule(rule):
                    dirty = self.update_rule(rule, row)
                    if dirty:
                        rule.save()
                        success_count += 1
                else:
                    self.msgs.append((messages.error, _("Rule in row {index} with id {id} does not belong in " \
                        "'{sheet_name}' sheet.".format(index=index, id=row['id'], sheet_name=self.sheet_name))))

        self.msgs.append((messages.success, _("Updated {count} rule(s) in '{sheet_name}' sheet").format(
            count=success_count, sheet_name=self.sheet_name)))

        return self.msgs

    def update_rule(self, rule, row):
        dirty = False
        if rule.name != row['name']:
            dirty = True
            rule.name = row['name']
        if rule.case_type != row['case_type']:
            dirty = True
            rule.case_type = row['case_type']
        return dirty

    def update_rule_message(self, rule, message):
        criteria_form = ConditionalAlertCriteriaForm(self.domain, rule=rule, is_system_admin=self.is_system_admin)
        schedule_form = ConditionalAlertScheduleForm(
            self.domain,
            rule.get_messaging_rule_schedule(),
            self.can_use_inbound_sms,
            rule,
            criteria_form,
            {'message': message},
            is_system_admin=self.is_system_admin,
        )
        initial_schedule = schedule_form.compute_initial()
        if schedule_form.is_valid():
            save_schedule(self.domain, initial_schedule['send_frequency'],
                          schedule_form.cleaned_data, {'message': message},
                          schedule_form.distiller, schedule_form.standalone_content_form.distiller,
                          initial_schedule=initial_schedule)
        else:
            # TODO: pass back an error
            pass


class TranslatedConditionalAlertUploader(ConditionalAlertUploader):
    sheet_name = 'translated'

    def applies_to_rule(self, rule):
        message = self.rule_message(rule)
        return message and '*' not in message

    def update_rule(self, rule, row):
        dirty = super(TranslatedConditionalAlertUploader, self).update_rule(rule, row)
        message = self.rule_message(rule)
        message_dirty = False
        for lang in self.langs:
            if message.get(lang, '') != row['message_' + lang]:
                message.update({lang: row['message_' + lang]})
                message_dirty = True
        if message_dirty:
            self.update_rule_message(rule, message)
        return dirty or message_dirty


class UntranslatedConditionalAlertUploader(ConditionalAlertUploader):
    sheet_name = 'not translated'

    def applies_to_rule(self, rule):
        message = self.rule_message(rule)
        return not message or '*' in message

    def update_rule(self, rule, row):
        dirty = super(UntranslatedConditionalAlertUploader, self).update_rule(rule, row)
        message = self.rule_message(rule)
        if message.get('*', '') != row['message']:
            self.update_rule_message(rule, message)
            dirty = True
        return dirty


def _get_rule_content(rule):
    return rule.get_messaging_rule_schedule().memoized_events[0].content
