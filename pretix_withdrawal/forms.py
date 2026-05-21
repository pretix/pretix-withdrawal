from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from i18nfield.forms import I18nFormField, I18nTextarea, I18nTextInput
from pretix.base.forms import (
    I18nMarkdownTextarea,
    I18nModelForm,
    PlaceholderValidator,
    SettingsForm,
)
from pretix.base.validators import multimail_validate
from pretix.control.forms.filter import FilterForm

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


class OrganizerSettingsForm(SettingsForm):
    withdrawal_contact_mail = forms.CharField(
        label=_("Email address"),
        required=True,
        validators=[multimail_validate],
        help_text=_(
            "If we receive a withdrawal, we will notify you on this email address. You can specify multiple recipients separated by commas."
        ),
    )
    withdrawal_received_success_msg = I18nFormField(
        label=_(
            "Message shown to the user after submitting the form to withdraw from an order"
        ),
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
        kwargs.pop("request")
        super().__init__(*args, **kwargs)

    def filter_qs(self, qs):
        fdata = self.cleaned_data
        qs = super().filter_qs(qs)
        if fdata.get("query"):
            u = fdata.get("query")
            qs = qs.filter(
                Q(order_code=u)
                | Q(order__code=u)
                | Q(email__icontains=u)
                | Q(name__icontains=u)
            )
        if fdata.get("status"):
            s = fdata.get("status")
            if s == "settled":
                qs = qs.filter(settled__isnull=False)
        else:
            qs = qs.filter(settled__isnull=True)

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
