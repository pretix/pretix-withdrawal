import urllib.parse
from django.dispatch import receiver
from django.http import QueryDict
from django.template.loader import get_template
from django.urls import resolve, reverse
from django.utils.translation import gettext_lazy as _, gettext_noop
from i18nfield.strings import LazyI18nString
from pretix.base.email import SimpleFunctionalMailTextPlaceholder
from pretix.base.models import Event, Order
from pretix.base.settings import settings_hierarkey
from pretix.base.signals import register_mail_placeholders
from pretix.control.signals import nav_event, nav_organizer, order_info
from pretix.helpers.format import format_map
from pretix.multidomain.urlreverse import build_absolute_uri
from pretix.presale.signals import checkout_confirm_messages, global_footer_link


@receiver(order_info, dispatch_uid="withdrawal_control_order_info")
def on_control_order_info(sender: Event, request, order: Order, **kwargs):
    withdrawals = order.withdrawals.all()
    if not withdrawals:
        return ""

    template = get_template("pretix_withdrawal/control/order_info.html")
    ctx = {
        "order": order,
        "request": request,
        "event": sender,
        "withdrawals": withdrawals,
    }
    return template.render(ctx, request=request)


def _withdrawal_url(organizer, event=None, order=None):
    if organizer.settings.withdrawal_use_custom:
        return format_map(
            organizer.settings.withdrawal_custom_url,
            {
                "event": event.slug if event else "",
                "organizer": organizer.slug,
                "code": order.full_code if order else "",
                "email": urllib.parse.quote_plus(order.email) if order else "",
            },
        )

    q = QueryDict(mutable=True)
    if order:
        q["code"] = order.full_code
        q["email"] = order.email

    return build_absolute_uri(
        event or organizer,
        "plugins:pretix_withdrawal:presale.{}.create".format(
            "event" if event else "organizer"
        ),
    ) + ("?" + q.urlencode() if q else "")


def _withdrawal_policy_url(organizer, event=None):
    if organizer.settings.withdrawal_policy_url:
        return format_map(
            organizer.settings.withdrawal_policy_url,
            {
                "event": event.slug if event else "",
                "organizer": organizer.slug,
            },
        )
    return build_absolute_uri(
        event or organizer,
        "plugins:pretix_withdrawal:presale.{}.policy".format(
            "event" if event else "organizer"
        ),
    )


@receiver(global_footer_link, dispatch_uid="withdrawal_footer_link")
def footer_link(sender, request=None, **kwargs):
    if not request:
        return []

    organizer = getattr(request, "organizer", None)
    event = getattr(request, "event", None)

    if not organizer or "pretix_withdrawal" not in (event or organizer).plugins:
        return []
    links = []
    if request.organizer.settings.withdrawal_policy_label:
        links.append(
            {
                "label": request.organizer.settings.withdrawal_policy_label,
                "url": _withdrawal_policy_url(organizer, event),
            }
        )
    links.append(
        {
            "label": request.organizer.settings.withdrawal_label,
            "url": _withdrawal_url(organizer, event),
            "cssclass": "btn btn-primary btn-xs",
        }
    )

    return links


@receiver(checkout_confirm_messages, dispatch_uid="withdrawal_confirm_messages")
def confirm_messages(sender, *args, **kwargs):
    attr = ' href="{url}" target="_blank"'.format(
        url=_withdrawal_policy_url(sender.organizer, sender)
    )
    return {
        "withdrawal_policy": _(
            "I have read and agree with the contents of the <a{attr}>cancellation policy</a>."
        ).format(attr=attr)
    }


@receiver(register_mail_placeholders, dispatch_uid="pretix_withdrawal_placeholders")
def register_placeholders(sender, **kwargs):
    return [
        SimpleFunctionalMailTextPlaceholder(
            "withdrawal_url",
            ["order", "event"],
            lambda order, event: _withdrawal_url(event.organizer, event, order),
            lambda event: _withdrawal_url(event.organizer, event),
        ),
        SimpleFunctionalMailTextPlaceholder(
            "withdrawal_policy_url",
            ["event"],
            lambda event: _withdrawal_policy_url(event.organizer, event),
            lambda event: _withdrawal_policy_url(event.organizer, event),
        ),
    ]


@receiver(nav_organizer, dispatch_uid="pretix_withdrawal_organizer_nav_settings")
def navbar_organizer_settings(sender, request, **kwargs):
    if not request.user.has_organizer_permission(
        request.organizer, "organizer.settings.general:write", request=request
    ):
        return []

    url = resolve(request.path_info)
    return [
        {
            "label": _("Withdrawal"),
            "url": reverse(
                "plugins:pretix_withdrawal:control.organizer.settings",
                kwargs={
                    "organizer": request.organizer.slug,
                },
            ),
            "active": url.namespace == "plugins:pretix_withdrawal"
            and url.url_name.endswith("settings"),
            "parent": reverse(
                "control:organizer.edit",
                kwargs={"organizer": request.organizer.slug},
            ),
        },
    ]


@receiver(nav_organizer, dispatch_uid="pretix_withdrawal_organizer_nav_list")
def navbar_organizer_list(sender, request, **kwargs):
    url = resolve(request.path_info)
    return [
        {
            "icon": "ban",
            "label": _("Withdrawals"),
            "url": reverse(
                "plugins:pretix_withdrawal:control.organizer.index",
                kwargs={
                    "organizer": request.organizer.slug,
                },
            ),
            "active": url.namespace == "plugins:pretix_withdrawal"
            and not url.url_name.endswith("settings"),
        }
    ]


@receiver(nav_event, dispatch_uid="pretix_withdrawal_event_nav_list")
def nav_event_receiver(sender, request, **kwargs):
    url = request.resolver_match
    if not request.user.has_event_permission(
        request.organizer, request.event, "event.orders:read", request=request
    ):
        return []
    return [
        {
            "label": _("Withdrawals"),
            "url": reverse(
                "plugins:pretix_withdrawal:control.event.index",
                kwargs={
                    "event": request.event.slug,
                    "organizer": request.organizer.slug,
                },
            ),
            "parent": reverse(
                "control:event.orders",
                kwargs={
                    "event": request.event.slug,
                    "organizer": request.event.organizer.slug,
                },
            ),
            "active": url.namespace == "plugins:pretix_withdrawal",
        }
    ]


settings_hierarkey.add_default("withdrawal_use_custom", default_type=bool, value=False)
settings_hierarkey.add_default(
    "withdrawal_custom_url",
    LazyI18nString(""),
    LazyI18nString,
)

settings_hierarkey.add_default("withdrawal_contact_mail", default_type=str, value=None)
settings_hierarkey.add_default(
    "withdrawal_label",
    LazyI18nString.from_gettext(gettext_noop("Withdraw from contract")),
    LazyI18nString,
)

settings_hierarkey.add_default(
    "withdrawal_submit_label",
    LazyI18nString.from_gettext(gettext_noop("Confirm withdrawal")),
    LazyI18nString,
)
settings_hierarkey.add_default(
    "withdrawal_form_above_msg",
    LazyI18nString.from_gettext(
        gettext_noop("Please fill out the form below to withdraw from your order.")
    ),
    LazyI18nString,
)
settings_hierarkey.add_default(
    "withdrawal_form_message_help_text",
    LazyI18nString.from_gettext(
        gettext_noop(
            "Do you want to withdraw part of your order? Please specify here which items you want to cancel."
        )
    ),
    LazyI18nString,
)

settings_hierarkey.add_default(
    "withdrawal_received_success_msg",
    LazyI18nString.from_gettext(
        gettext_noop(
            "We received your withdrawal. We will send an email to {email} to acknowledge the receipt. "
            "The review of your withdrawal’s legal validity and scope will be conducted in a separate step by our customer service team. "
            "We will get back to you shortly."
        )
    ),
    LazyI18nString,
)

settings_hierarkey.add_default(
    "withdrawal_received_mail_subject",
    LazyI18nString.from_gettext(gettext_noop("Your withdrawal")),
    LazyI18nString,
)
settings_hierarkey.add_default(
    "withdrawal_received_mail_body",
    LazyI18nString.from_gettext(
        gettext_noop(
            "Hello,\n\n"
            "we received your declaration of revocation.\n\n"
            "- Date and time: {created}\n"
            "- Name: {name}\n"
            "- Order: {code}\n"
            "\n"
            "Your right of withdrawal is currently being reviewed. Please note that this email\n"
            "merely confirms receipt of your declaration. The review of its legal validity and\n"
            "scope will be conducted in a separate step by our customer service team.\n"
            "We will get back to you shortly.  \n\n"
            "Best regards,  \n"
            "Your {organizer} team"
        )
    ),
    LazyI18nString,
)
settings_hierarkey.add_default(
    "withdrawal_warn_mail_subject",
    LazyI18nString.from_gettext(
        gettext_noop("We received a withdrawal for your order")
    ),
    LazyI18nString,
)
settings_hierarkey.add_default(
    "withdrawal_warn_mail_body",
    LazyI18nString.from_gettext(
        gettext_noop(
            "Hello,\n\n"
            "we received a withdrawal from order {code} for {event} from an email address different to the one used in your order.\n\n"
            "If you did not initiate this withdrawal please contact us immediately.\n\n"
            "Best regards,  \n"
            "Your {organizer} team"
        )
    ),
    LazyI18nString,
)

settings_hierarkey.add_default(
    "withdrawal_policy_label",
    LazyI18nString(""),
    LazyI18nString,
)
settings_hierarkey.add_default(
    "withdrawal_policy_url",
    LazyI18nString(""),
    LazyI18nString,
)
settings_hierarkey.add_default(
    "withdrawal_policy_text",
    LazyI18nString(""),
    LazyI18nString,
)
