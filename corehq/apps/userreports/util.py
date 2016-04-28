import collections
from corehq import privileges, toggles
from corehq.apps.hqwebapp.templatetags.hq_shared_tags import toggle_enabled
from corehq.apps.userreports.const import REPORT_BUILDER_EVENTS_KEY
from django_prbac.utils import has_privilege


def localize(value, lang):
    """
    Localize the given value.

    This function is intended to be used within UCR to localize user supplied
    translations.

    :param value: A dict-like object or string
    :param lang: A language code.
    """
    if isinstance(value, collections.Mapping) and len(value):
        return (
            value.get(lang, None) or
            value.get(default_language(), None) or
            value[sorted(value.keys())[0]]
        )
    return value


def default_language():
    return "en"


def has_report_builder_add_on_privilege(request):
    return any(
        has_privilege(request, p) for p in privileges.REPORT_BUILDER_ADD_ON_PRIVS
    )

def has_report_builder_access(request):

    builder_enabled = toggle_enabled(request, toggles.REPORT_BUILDER)
    legacy_builder_priv = has_privilege(request, privileges.REPORT_BUILDER)
    beta_group_enabled = toggle_enabled(request, toggles.REPORT_BUILDER_BETA_GROUP)
    has_add_on_priv = has_report_builder_add_on_privilege(request)

    return (builder_enabled and legacy_builder_priv) or beta_group_enabled or has_add_on_priv


def add_event(request, event):
    events = request.session.get(REPORT_BUILDER_EVENTS_KEY, [])
    request.session[REPORT_BUILDER_EVENTS_KEY] = events + [event]


def has_report_builder_trial(request):
    return has_privilege(request, privileges.REPORT_BUILDER_TRIAL)


def can_edit_report(request, report):
    ucr_toggle = toggle_enabled(request, toggles.USER_CONFIGURABLE_REPORTS)
    report_builder_toggle = toggle_enabled(request, toggles.REPORT_BUILDER)
    report_builder_beta_toggle = toggle_enabled(request, toggles.REPORT_BUILDER_BETA_GROUP)
    add_on_priv = has_report_builder_add_on_privilege(request)
    created_by_builder = report.spec.report_meta.created_by_builder

    if created_by_builder:
        return report_builder_toggle or report_builder_beta_toggle or add_on_priv
    else:
        return ucr_toggle
