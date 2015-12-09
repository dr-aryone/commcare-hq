import copy
from couchdbkit.exceptions import ResourceNotFound
from django.conf import settings
from django.utils.safestring import mark_safe
import re
from corehq.apps.app_manager.models import Application
from corehq.apps.reports.analytics.couchaccessors import guess_form_name_from_submissions_using_xmlns
from corehq.apps.reports.filters.base import BaseDrilldownOptionFilter, BaseSingleOptionFilter, BaseTagsFilter
from couchforms.analytics import get_all_xmlns_app_id_pairs_submitted_to_in_domain
from dimagi.utils.decorators.memoized import memoized

# For translations
from django.utils.translation import ugettext as _
from django.utils.translation import ugettext_noop, ugettext_lazy

MISSING_APP_ID = "_MISSING_APP_ID"

PARAM_SLUG_STATUS = 'status'
PARAM_SLUG_APP_ID = 'app_id'
PARAM_SLUG_MODULE = 'module'
PARAM_SLUG_XMLNS = 'xmlns'

PARAM_VALUE_STATUS_ACTIVE = 'active'
PARAM_VALUE_STATUS_DELETED = 'deleted'


class FormsByApplicationFilterParams(object):
    def __init__(self, params):
        self.app_id = self.status = self.module = self.xmlns = self.most_granular_filter = None
        for param in params:
            slug = param['slug']
            value = param['value']
            if slug == PARAM_SLUG_STATUS:
                self.status = value
            elif slug == PARAM_SLUG_APP_ID:
                self.app_id = value
            elif slug == PARAM_SLUG_MODULE:
                self.module = value
            elif slug == PARAM_SLUG_XMLNS:
                self.xmlns = value
            # we rely on the fact that the filters come in order of granularity
            # some logic depends on this
            self.most_granular_filter = slug

    @property
    def show_active(self):
        return self.status == PARAM_VALUE_STATUS_ACTIVE


class FormsByApplicationFilter(BaseDrilldownOptionFilter):
    """
        Use this filter to drill down by
        (Active Applications or Deleted Applications >) Application > Module > Form

        You may also select Unknown Forms for forms that can't be matched to any known Application or
        Application-Deleted for this domain. Form submissions for remote apps will also show up
        in Unknown Forms

        You may also hide/show fuzzy results (where fuzzy means you can't match that XMLNS to exactly one
        Application or Application-Deleted).
    """
    slug = "form"
    label = ugettext_lazy("Filter Forms")
    css_class = "span5"
    drilldown_empty_text = ugettext_lazy("You don't have any applications set up, so there are no forms "
                                         "to choose from. Please create an application!")
    template = "reports/filters/form_app_module_drilldown.html"
    unknown_slug = "unknown"
    fuzzy_slug = "@@FUZZY"
    show_global_hide_fuzzy_checkbox = True
    display_app_type = False # whether we're displaying the application type select box in the filter

    @property
    def display_lang(self):
        """
            This should return the lang code of the language being used to view this form.
        """
        return hasattr(self.request, 'couch_user') and self.request.couch_user.language or 'en'

    @property
    def rendered_labels(self):
        """
            Here we determine whether to extend the drilldown to allow the user to choose application types.
            Current supported types are:
            - Active Application (Application)
            - Deleted Application (Application-Deleted)
        """
        labels = self.get_labels()
        if self.drilldown_map and self.drilldown_map[0]['val'] == PARAM_VALUE_STATUS_ACTIVE:
            labels = [
                 (_('Application Type'),
                  _("Select an Application Type") if self.use_only_last else _("Show all Application Types"),
                  'status'),
                 (_('Application'),
                  _("Select Application...") if self.use_only_last else _("Show all Forms of this Application Type..."),
                  PARAM_SLUG_APP_ID),
             ] + labels[1:]
        return labels

    @property
    def filter_context(self):
        context = super(FormsByApplicationFilter, self).filter_context
        context.update({
            'unknown_available': bool(self._unknown_forms),
            'unknown': {
                'show': self._show_unknown,
                'slug': self.unknown_slug,
                'selected': self._selected_unknown_xmlns,
                'options': self._unknown_forms_options,
                'default_text': "Select an Unknown Form..." if self.use_only_last else "Show All Unknown Forms...",
            },
            'hide_fuzzy': {
                'show': not self._show_unknown and self.show_global_hide_fuzzy_checkbox and self._fuzzy_forms,
                'slug': '%s_%s' % (self.slug, self.fuzzy_slug),
                'checked': self._hide_fuzzy_results,
            },
            'display_app_type': self.display_app_type,
            'support_email': settings.SUPPORT_EMAIL,
        })

        if self.display_app_type and not context['selected']:
            context['selected'] = [PARAM_VALUE_STATUS_ACTIVE]
        context["show_advanced"] = (
            self.request.GET.get('show_advanced') == 'on'
            or context["unknown"]["show"]
            or context["hide_fuzzy"]["checked"]
            or (len(context['selected']) > 0
                and context['selected'][0] != PARAM_VALUE_STATUS_ACTIVE)
        )
        return context

    @property
    @memoized
    def drilldown_map(self):
        final_map = []
        map_active = []
        map_deleted = []

        all_forms = self._application_forms_info.copy()

        for app_map in all_forms.values():
            app_langs = app_map['app']['langs']
            is_deleted = app_map['is_deleted']

            app_name = self.get_translated_value(self.display_lang, app_langs, app_map['app']['names'])
            if is_deleted:
                app_name = "%s [Deleted Application]" % app_name
            app = self._map_structure(app_map['app']['id'], app_name)

            for module_map in app_map['modules']:
                if module_map['module'] is not None:
                    module_name = self.get_translated_value(
                        self.display_lang, app_langs, module_map['module']['names'])
                    module = self._map_structure(module_map['module']['id'], module_name)
                    for form_map in module_map['forms']:
                        form_name = self.get_translated_value(
                            self.display_lang, app_langs, form_map['form']['names'])
                        module['next'].append(self._map_structure(form_map['xmlns'], form_name))
                    app['next'].append(module)

            if is_deleted:
                map_deleted.append(app)
            else:
                map_active.append(app)

        if (bool(map_deleted) + bool(map_active)) > 1:
            self.display_app_type = True
            if map_active:
                final_map.append(
                    self._map_structure(PARAM_VALUE_STATUS_ACTIVE, _('Active CommCare Applications'), map_active)
                )
            if map_deleted:
                final_map.append(
                    self._map_structure(PARAM_VALUE_STATUS_DELETED, _('Deleted CommCare Applications'),
                                        map_deleted)
                )
        else:
            final_map.extend(map_active or map_deleted)

        return final_map

    @property
    @memoized
    def _all_forms(self):
        """
            Here we grab all forms ever submitted to this domain on CommCare HQ or all forms that the Applications
            for this domain know about.
        """
        form_buckets = get_all_xmlns_app_id_pairs_submitted_to_in_domain(self.domain)
        all_submitted = {self.make_xmlns_app_key(xmlns, app_id)
                         for xmlns, app_id in form_buckets}
        from_apps = set(self._application_forms)
        return list(all_submitted.union(from_apps))

    @property
    @memoized
    def _application_forms(self):
        """
            These are forms with an xmlns that can be matched to an Application or Application-Deleted
            id with certainty.
        """
        data = self._raw_data(["xmlns app", self.domain], group=True)
        all_forms = self.get_xmlns_app_keys(data)
        return all_forms

    @property
    @memoized
    def _application_forms_info(self):
        """
            This is the data used for creating the drilldown_map. This returns the following type of structure:
            {
                'app_id': {
                    'app': {
                        'names': [<foo>] or '<foo>',
                        'id': '<foo>',
                        'langs': [<foo>]
                    },
                    'is_user_registration': (True or False),
                    'is_deleted': (True or False),
                    'modules' : [
                        {
                            'module': {
                                'names': [<foo>] or '<foo>',
                                'id': index,
                                'forms': [
                                    {
                                        'form': {
                                            'names': [<foo>] or '<foo>',
                                            'xmlns': <xmlns>
                                        }
                                ]
                            }
                        },
                        {...}
                    ]
                },
                'next_app_id': {...},
            }
        """
        data = self._raw_data(["app module form", self.domain])
        default_module = lambda num: {'module': None, 'forms': []}
        app_forms = {}
        for line in data:
            app_info = line.get('value')
            if not app_info:
                continue

            index_offset = 1 if app_info.get('is_user_registration', False) else 0

            app_id = app_info['app']['id']

            if not app_id in app_forms:
                app_forms[app_id] = {
                    'app': app_info['app'],
                    'is_user_registration': app_info.get('is_user_registration', False),
                    'is_deleted': app_info['is_deleted'],
                    'modules': []
                }

            module_id = app_info['module']['id'] + index_offset

            new_modules = module_id - len(app_forms[app_id]['modules']) + 1
            if new_modules > 0:
                # takes care of filler modules (modules in the app with no form submissions.
                # these 'filler modules' are eventually ignored when rendering the drilldown map.
                app_forms[app_id]['modules'].extend([default_module(module_id - m) for m in range(0, new_modules)])

            if not app_info.get('is_user_registration'):
                app_forms[app_id]['modules'][module_id]['module'] = app_info['module']
                app_forms[app_id]['modules'][module_id]['forms'].append({
                    'form': app_info['form'],
                    'xmlns': app_info['xmlns'],
                })
        return app_forms

    @property
    @memoized
    def _nonmatching_app_forms(self):
        """
        These are forms that we could not find exact matches for in known or deleted apps
        (including remote apps)
        """
        all_forms = set(self._all_forms)
        std_app_forms = set(self._application_forms)
        nonmatching = all_forms.difference(std_app_forms)
        return list(nonmatching)

    @property
    @memoized
    def _fuzzy_forms(self):
        matches = {}
        app_data = self._raw_data(["xmlns app", self.domain], group=True)
        app_xmlns = [d['key'][-2] for d in app_data]
        for form in self._nonmatching_app_forms:
            xmlns = self.split_xmlns_app_key(form, only_xmlns=True)
            if xmlns in app_xmlns:
                matches[form] = {
                    'app_ids': [d['key'][-1] for d in app_data if d['key'][-2] == xmlns],
                    'xmlns': xmlns,
                    }
        return matches

    @property
    @memoized
    def _fuzzy_form_data(self):
        fuzzy = {}
        for form in self._fuzzy_forms:
            xmlns, unknown_id = self.split_xmlns_app_key(form)
            key = ["xmlns", self.domain, xmlns]
            info = self._raw_data(key)
            fuzzy[xmlns] = {
                'apps': [i['value'] for i in info],
                'unknown_id': unknown_id,
            }
        return fuzzy

    @property
    def _hide_fuzzy_results(self):
        return self.request.GET.get('%s_%s' % (self.slug, self.fuzzy_slug)) == 'yes'

    @property
    @memoized
    def _unknown_forms(self):
        nonmatching = set(self._nonmatching_app_forms)
        fuzzy_forms = set(self._fuzzy_forms.keys())

        unknown = list(nonmatching.difference(fuzzy_forms))
        return [u for u in unknown if u is not None]

    @property
    @memoized
    def _unknown_xmlns(self):
        return list(set([self.split_xmlns_app_key(x, only_xmlns=True) for x in self._unknown_forms]))

    @property
    def _show_unknown(self):
        return self.request.GET.get('%s_%s' % (self.slug, self.unknown_slug))

    @property
    @memoized
    def _unknown_forms_options(self):
        return [dict(val=x, text="%s; ID: %s" % (self.get_unknown_form_name(x), x)) for x in self._unknown_xmlns]

    @property
    def _selected_unknown_xmlns(self):
        if self._show_unknown:
            return self.request.GET.get('%s_%s_xmlns' % (self.slug, self.unknown_slug), '')
        return ''

    @memoized
    def get_unknown_form_name(self, xmlns, app_id=None, none_if_not_found=False):
        if app_id is not None and app_id != '_MISSING_APP_ID':
            try:
                app = Application.get_db().get(app_id)
            except ResourceNotFound:
                # must have been a weird app id, don't fail hard
                pass
            else:
                for module in app.get('modules', []):
                    for form in module['forms']:
                        if form['xmlns'] == xmlns:
                            return form['name'].values()[0]

        guessed_name = guess_form_name_from_submissions_using_xmlns(self.domain, xmlns)
        return guessed_name or (None if none_if_not_found else _("Name Unknown"))

    @staticmethod
    def get_translated_value(display_lang, app_langs, obj):
        """
        Given a list of lang codes and a dictionary of lang codes to strings, output
        the value of the current display lang or the first lang available.

        If obj is a string, just output that string.
        """
        if isinstance(obj, basestring):
            return obj
        val = obj.get(display_lang)
        if val:
            return val
        for lang in app_langs:
            val = obj.get(lang)
            if val:
                return val
        return obj.get(obj.keys()[0], _('Untitled'))

    @staticmethod
    def _formatted_name_from_app(display_lang, app):
        langs = app['app']['langs']
        app_name = FormsByApplicationFilter.get_translated_value(display_lang, langs, app['app']['names'])
        module_name = FormsByApplicationFilter.get_translated_value(display_lang, langs, app['module']['names'])
        form_name = FormsByApplicationFilter.get_translated_value(display_lang, langs, app['form']['names'])
        is_deleted = app.get('is_deleted', False)
        if is_deleted:
            app_name = "%s [Deleted]" % app_name
        return "%s > %s > %s" % (app_name, module_name, form_name)

    @classmethod
    def has_selections(cls, request):
        params, instance = super(cls, cls).get_value(request, request.domain)
        if instance._show_unknown:
            return True
        for param in params:
            if param['slug'] == PARAM_SLUG_APP_ID:
                return True
        return False

    def _get_filtered_data(self, filter_results):
        """
        Returns the raw form data based on the current filter selection.
        """
        if not filter_results:
            data = []
            if self._application_forms:
                key = ["app module form", self.domain]
                data.extend(self._raw_data(key))
            return data

        parsed_params = FormsByApplicationFilterParams(filter_results)
        if parsed_params.xmlns:
            status = parsed_params.status or PARAM_VALUE_STATUS_ACTIVE
            key = ["status xmlns app", self.domain, status, parsed_params.xmlns, parsed_params.app_id]
            return self._raw_data(key)
        else:
            if self._application_forms:
                prefix = "app module form"
                key = [self.domain]
                if parsed_params.status:
                    prefix = "%s %s" % ("status", prefix)
                for f in filter_results:
                    val = f['value']
                    if f['slug'] == 'module':
                        try:
                            val = int(val)
                        except Exception:
                            break
                    key.append(val)
                return self._raw_data([prefix] + key)
            else:
                return []

    def _get_selected_forms(self, filter_results):
        """
            Returns the appropriate form information based on the current filter selection.
        """
        if self._show_unknown:
            return self._get_selected_forms_for_unknown_apps()
        else:
            result = {}
            data = self._get_filtered_data(filter_results)
            for line in data:
                app = line['value']
                app_id = app['app']['id']
                xmlns_app = self.make_xmlns_app_key(app['xmlns'], app_id)
                if xmlns_app not in result:
                    result[xmlns_app] = self._generate_report_app_info(
                        app['xmlns'],
                        app_id,
                        self._formatted_name_from_app(self.display_lang, app),
                    )

            if not self._hide_fuzzy_results and self._fuzzy_forms:
                selected_xmlns = [r['xmlns'] for r in result.values()]
                selected_apps = [r['app_id'] for r in result.values()]
                for xmlns, info in self._fuzzy_form_data.items():
                    for app_map in info['apps']:
                        if xmlns in selected_xmlns and app_map['app']['id'] in selected_apps:
                            result["%s %s" % (xmlns, self.fuzzy_slug)] = self._generate_report_app_info(
                                xmlns,
                                info['unknown_id'],
                                "%s [Fuzzy Submissions]" % self._formatted_name_from_app(
                                    self.display_lang, app_map),
                                is_fuzzy=True,
                            )
            return result

    @staticmethod
    def _generate_report_app_info(xmlns, app_id, name, is_fuzzy=False):
        return {
            'xmlns': xmlns,
            'app_id': app_id,
            'name': name,
            'is_fuzzy': is_fuzzy,
        }

    def _get_selected_forms_for_unknown_apps(self):
        result = {}
        all_unknown = [self._selected_unknown_xmlns] if self._selected_unknown_xmlns else self._unknown_forms
        for form in all_unknown:
            xmlns, app_id = self.split_xmlns_app_key(form)
            if form not in result:
                result[xmlns] = self._generate_report_app_info(
                    xmlns,
                    None if self._selected_unknown_xmlns else app_id,
                    "%s; ID: %s" % (self.get_unknown_form_name(xmlns), xmlns)
                )
        return result

    def _raw_data(self, startkey, endkey=None, group=False):
        if endkey is None:
            endkey = startkey
        kwargs = dict(group=group) if group else dict(reduce=False)
        return Application.get_db().view('reports_forms/by_app_info',
            startkey=startkey,
            endkey=endkey+[{}],
            **kwargs
        ).all()

    @classmethod
    def get_xmlns_app_keys(cls, data):
        return [cls.make_xmlns_app_key(d['key'][-2], d['key'][-1]) for d in data]

    @classmethod
    def make_xmlns_app_key(cls, xmlns, app_id):
        """
            Uniquely identify a form with an xmlns+app_id pairing so that we can split fuzzy-matched data from
            non-fuzzy data.
        """
        if app_id == MISSING_APP_ID:
            return xmlns
        return "%s %s" % (xmlns, app_id)

    @classmethod
    def split_xmlns_app_key(cls, key, only_xmlns=False):
        """
            Takes an unique xmlns+app_id key generated by make_xmlns_app_key and spits out the xmlns and app_id.
        """
        if key is None:
            return key
        identify = key.split(' ')
        xmlns = identify[0]
        if only_xmlns:
            return xmlns
        app_id = identify[1] if len(identify) > 1 else MISSING_APP_ID
        return xmlns, app_id

    @classmethod
    def get_labels(cls):
        return [
            (_('Application'),
             _("Select an Application") if cls.use_only_last
             else _("Show Forms in all Applications"), PARAM_SLUG_APP_ID),
            (_('Module'),
             _("Select a Module") if cls.use_only_last
             else _("Show Forms from all Modules in selected Application"), PARAM_SLUG_MODULE),
            (_('Form'),
             _("Select a Form") if cls.use_only_last
             else _("Show all Forms in selected Module"), PARAM_SLUG_XMLNS),
        ]

    @classmethod
    def get_value(cls, request, domain):
        """
            Gets the value of this filter---to be used by the relevant report.
        """
        filter_results, instance = super(FormsByApplicationFilter, cls).get_value(request, domain)
        return instance._get_selected_forms(filter_results)


class SingleFormByApplicationFilter(FormsByApplicationFilter):
    """
        Same as its superclass, except you _must_ select one form by the end of it.
    """
    label = ugettext_noop("Choose a Form")
    use_only_last = True
    show_global_hide_fuzzy_checkbox = False


class CompletionOrSubmissionTimeFilter(BaseSingleOptionFilter):
    slug = "sub_time"
    label = ugettext_noop("Filter Dates By")
    css_class = "span2"
    help_text = mark_safe("%s<br />%s" % (ugettext_noop("<strong>Completion</strong> time is when the form is completed on the phone."),
                                          ugettext_noop("<strong>Submission</strong> time is when CommCare HQ receives the form.")))
    default_text = ugettext_noop("Completion Time")

    @property
    def options(self):
        return [
            ('submission', _('Submission Time')),
        ]


class FormDataFilter(BaseTagsFilter):
    slug = 'form_data'
    label = "Form Data"
    advanced = True
    help_text = "Filter by the value of a question in the form. Exact matches only."
    placeholder = ugettext_noop("question id:value")


class CustomFieldFilter(BaseTagsFilter):
    slug = 'custom_field'
    label = "Columns"
    advanced = True
    help_text = "Question ids entered here will appear as additonal columns in the report."
    placeholder = ugettext_noop("question id")
