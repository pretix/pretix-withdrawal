from django import forms
from django.db.models import Q
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from i18nfield.forms import I18nFormField, I18nTextarea, I18nTextInput
from pretix.base.forms import (
    I18nMarkdownTextarea,
    I18nModelForm,
    PlaceholderValidator,
    SettingsForm,
)
from pretix.base.models.organizer import TeamQuerySet
from pretix.base.validators import multimail_validate
from pretix.control.forms import ModelChoiceFieldWithNone
from pretix.control.forms.filter import FilterForm
from pretix.control.forms.widgets import Select2
from pretix.helpers.database import get_deterministic_ordering

from .models import Withdrawal


class CreateForm(I18nModelForm):
    required_css_class = "required"

    class Meta:
        model = Withdrawal
        fields = ("email", "name", "order_code", "message")
        widgets = {
            "email": forms.EmailInput(
                attrs={
                    "autocomplete": "email",
                }
            ),
            "name": forms.TextInput(
                attrs={
                    "autocomplete": "name",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        organizer = kwargs.pop("organizer")
        super().__init__(*args, **kwargs)
        self.fields["message"].help_text = (
            organizer.settings.withdrawal_form_message_help_text
        )


class OrganizerSettingsForm(SettingsForm):
    withdrawal_contact_mail = forms.CharField(
        label=_("Email address"),
        required=True,
        validators=[multimail_validate],
        help_text=_(
            "If we receive a withdrawal, we will notify you on this email address. You can specify multiple recipients separated by commas."
        ),
    )

    withdrawal_label = I18nFormField(
        label=_("Label"),
        required=True,
        widget=I18nTextInput,
        help_text=_(
            "Used for the link in the footer and as the headline on the withdrawal form."
        ),
    )
    withdrawal_form_above_msg = I18nFormField(
        label=_("Message shown above the form"),
        required=True,
        widget=I18nTextarea,
        widget_kwargs={"attrs": {"rows": "3"}},
    )
    withdrawal_form_message_help_text = I18nFormField(
        label=_("Help-text shown below the message input field"),
        required=True,
        widget=I18nTextarea,
        widget_kwargs={"attrs": {"rows": "2"}},
    )
    withdrawal_submit_label = I18nFormField(
        label=_("Label of the submit button"),
        required=True,
        widget=I18nTextInput,
    )
    withdrawal_received_success_msg = I18nFormField(
        label=_("Message shown after successful submission"),
        required=True,
        widget=I18nTextarea,
        widget_kwargs={"attrs": {"rows": "3"}},
    )
    withdrawal_received_mail_subject = I18nFormField(
        label=_("Subject"),
        max_length=250,
        required=True,
        widget=I18nTextInput,
    )
    withdrawal_received_mail_body = I18nFormField(
        label=_("Body"),
        required=True,
        widget=I18nMarkdownTextarea,
        widget_kwargs={"attrs": {"rows": "12"}},
    )
    withdrawal_warn_mail_subject = I18nFormField(
        label=_("Subject"),
        max_length=250,
        required=True,
        widget=I18nTextInput,
    )
    withdrawal_warn_mail_body = I18nFormField(
        label=_("Body"),
        required=True,
        widget=I18nTextarea,
        widget_kwargs={"attrs": {"rows": "12"}},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.event = kwargs.pop("obj")

        phs = ["{email}", "{code}"]
        phs_str = ", ".join(phs)
        self.fields["withdrawal_received_success_msg"].validators = [
            PlaceholderValidator(phs)
        ]
        self.fields["withdrawal_received_success_msg"].help_text = _(
            "Available placeholders: {list}"
        ).format(list=phs_str)

        phs_empty = "{name}"
        phs = ["{code}", "{name}", "{created}", "{organizer}"]
        phs_str = ", ".join(phs)
        self.fields["withdrawal_received_mail_subject"].validators = self.fields[
            "withdrawal_received_mail_body"
        ].validators = [PlaceholderValidator(phs)]
        self.fields["withdrawal_received_mail_subject"].help_text = self.fields[
            "withdrawal_received_mail_body"
        ].help_text = _(
            "Available placeholders: {list}. Note that {empty} can be empty."
        ).format(
            list=phs_str, empty=phs_empty
        )

        phs = ["{code}", "{event}", "{organizer}"]
        phs_str = ", ".join(phs)
        self.fields["withdrawal_warn_mail_subject"].validators = self.fields[
            "withdrawal_warn_mail_body"
        ].validators = [PlaceholderValidator(phs)]
        self.fields["withdrawal_warn_mail_subject"].help_text = self.fields[
            "withdrawal_warn_mail_body"
        ].help_text = _("Available placeholders: {list}").format(list=phs_str)


class WithdrawalFilterForm(FilterForm):
    orders = {"code": "order_code", "created": "created"}

    query = forms.CharField(
        label=_("Search for…"),
        widget=forms.TextInput(
            attrs={
                "placeholder": _("Search for…"),
            }
        ),
        required=False,
    )
    status = forms.ChoiceField(
        label=_("Status"),
        choices=(
            ("all", _("All withdrawals")),
            ("settled", _("settled")),
            ("", _("not settled")),
        ),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

    def filter_qs(self, qs):
        fdata = self.cleaned_data
        qs = super().filter_qs(qs)
        if fdata.get("query"):
            u = fdata.get("query")
            qs = qs.filter(
                Q(order_code__icontains=u)
                | Q(order__code__icontains=u)
                | Q(email__icontains=u)
                | Q(name__icontains=u)
            )
        if fdata.get("status"):
            s = fdata.get("status")
            if s == "settled":
                qs = qs.filter(settled__isnull=False)
        else:
            qs = qs.filter(settled__isnull=True)

        if fdata.get("ordering"):
            qs = qs.order_by(
                *get_deterministic_ordering(Withdrawal, self.get_order_by())
            )

        return qs


class OrganizerWithdrawalFilterForm(WithdrawalFilterForm):
    orders = {"code": "order_code", "created": "created", "event": "event"}

    @staticmethod
    def event_filter_queryset(user, session, organizer):
        if user.has_active_staff_session(session.session_key):
            return organizer.events.all()
        return organizer.events.filter(
            Q(
                organizer_id__in=user.teams.filter(
                    TeamQuerySet.event_permission_q("event.orders:read"),
                    all_events=True,
                ).values_list("organizer", flat=True)
            )
            | Q(
                id__in=user.teams.filter(
                    TeamQuerySet.event_permission_q("event.orders:read"),
                ).values_list("limit_events__id", flat=True)
            )
        )

    def __init__(self, *args, **kwargs):
        events_include_none = kwargs.pop("events_include_none", False)
        super().__init__(*args, **kwargs)

        self.fields["event"] = ModelChoiceFieldWithNone(
            label=_("Event"),
            queryset=OrganizerWithdrawalFilterForm.event_filter_queryset(
                self.request.user, self.request.session, self.request.organizer
            ),
            widget=Select2(
                attrs={
                    "data-model-select2": "event",
                    "data-select2-url": reverse("control:events.typeahead")
                    + "?organizer="
                    + self.request.organizer.slug
                    + "&permission=event.orders:read"
                    + ("&include_none" if events_include_none else ""),
                    "data-placeholder": _("All events"),
                }
            ),
            empty_label=_("All events"),
            none_label=_("No event"),
            required=False,
        )
        self.fields["event"].widget.choices = self.fields["event"].choices

    def filter_qs(self, qs):
        fdata = self.cleaned_data
        qs = super().filter_qs(qs)

        if fdata.get("event") == "_none":
            qs = qs.filter(event__isnull=True)
        elif fdata.get("event"):
            qs = qs.filter(event=fdata.get("event"))

        return qs


class CommentForm(I18nModelForm):
    class Meta:
        model = Withdrawal
        fields = ["internal_notes"]
        widgets = {
            "internal_notes": forms.Textarea(
                attrs={
                    "rows": 6,
                    "class": "helper-width-100",
                }
            ),
        }
