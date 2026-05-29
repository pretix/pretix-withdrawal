from django.dispatch import receiver
from django.template.loader import get_template
from django.urls import resolve, reverse
from django.utils.translation import gettext_lazy as _, gettext_noop
from i18nfield.strings import LazyI18nString
from pretix.base.models import Event, Order
from pretix.base.settings import settings_hierarkey
from pretix.control.signals import nav_event, nav_organizer, order_info
from pretix.presale.signals import global_footer_link


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


@receiver(global_footer_link, dispatch_uid="withdrawal_footer_link")
def footer_link(sender, request=None, **kwargs):
    if not request or not hasattr(request, "organizer"):
        return []
    if hasattr(request, "event"):
        if "pretix_withdrawal" not in request.event.plugins:
            return []
        url = reverse(
            "plugins:pretix_withdrawal:presale.event.create",
            kwargs={
                "event": request.event.slug,
                "organizer": request.organizer.slug,
            },
        )
    else:
        if "pretix_withdrawal" not in request.organizer.plugins:
            return []
        url = reverse(
            "plugins:pretix_withdrawal:presale.organizer.create",
            kwargs={
                "organizer": request.organizer.slug,
            },
        )
    return {
        "label": request.organizer.settings.withdrawal_label,
        "url": url,
        "cssclass": "btn btn-primary btn-xs",
    }


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
