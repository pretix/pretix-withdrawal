from typing import Any, Dict, Union

import css_inline
import uuid
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.template.loader import get_template
from django.utils.formats import date_format
from django.utils.translation import gettext_lazy as _
from django_scopes import ScopedManager
from i18nfield.strings import LazyI18nString
from pretix.base.i18n import language
from pretix.base.models import LoggedModel, OutgoingMail, User
from pretix.base.notifications import Notification
from pretix.base.services.mail import (
    SendMailException,
    mail,
    mail_send_task,
    render_mail,
)
from pretix.base.validators import NoUrlValidator
from pretix.helpers.format import format_map
from pretix.multidomain.urlreverse import build_absolute_uri


class Withdrawal(LoggedModel):
    organizer = models.ForeignKey(
        "pretixbase.Organizer",
        related_name="withdrawals",
        on_delete=models.CASCADE,
    )
    event = models.ForeignKey(
        "pretixbase.Event",
        related_name="withdrawals",
        on_delete=models.PROTECT,  # TODO: should this only PROTECT if withdrawal is not yet settled?
        null=True,
        blank=True,
    )
    order = models.ForeignKey(
        "pretixbase.Order",
        related_name="withdrawals",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    created = models.DateTimeField(auto_now_add=True)
    settled = models.DateTimeField(null=True)
    order_code = models.CharField(
        max_length=67,  # user may enter order.full_code
        verbose_name=_("Order code"),
        validators=[
            RegexValidator(
                regex="^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$",
                message=_(
                    "The order code may only contain letters, numbers, dots and dashes."
                ),
            ),
        ],
    )
    email = models.EmailField(db_index=True, verbose_name=_("Email"), max_length=190)
    name = models.CharField(max_length=255, verbose_name=_("Name"), blank=True)
    message = models.TextField(
        verbose_name=_("Message"),
        null=True,
        blank=True,
        validators=[
            NoUrlValidator(
                message=_(
                    "Your message includes an URL and therefore is considered SPAM. Please remove the URL %(match)s."
                ),
            ),
        ],
    )
    locale = models.CharField(
        verbose_name=_("Locale"),
        max_length=32,
    )
    internal_notes = models.TextField(
        verbose_name=_("Internal comment"), null=True, blank=True
    )

    objects = ScopedManager(organizer="organizer")

    def mail_withdrawal_received(self):
        with language(self.locale, self.event.settings.region if self.event else None):
            context = {
                "created": date_format(
                    self.created.astimezone(
                        self.event.timezone if self.event else self.organizer.timezone
                    ),
                    "SHORT_DATETIME_FORMAT",
                ),
                "name": self.name or "",
                "code": self.order_code,
                "organizer": self.organizer,
            }
            self._send_mail(
                self.email,
                self.organizer.settings.withdrawal_received_mail_subject,
                self.organizer.settings.withdrawal_received_mail_body,
                context,
                "pretix_withdrawal.email.withdrawal.received",
            )
        if self.organizer.settings.withdrawal_contact_mail:
            with language(
                self.event.settings.locale if self.event else self.locale,
                self.event.settings.region if self.event else None,
            ):
                self._send_notification_mail()

    def mail_warn_withdrawal_received(self):
        if not self.order or "@" not in self.order.email:
            return
        with language(self.order.locale, self.event.settings.region):
            context = {
                "event": self.event,
                "code": self.order,
                "organizer": self.organizer,
            }
            self._send_mail(
                self.order.email,
                self.organizer.settings.withdrawal_warn_mail_subject,
                self.organizer.settings.withdrawal_warn_mail_body,
                context,
                "pretix_withdrawal.email.withdrawal.warn",
            )

    def _send_mail(
        self,
        recipient,
        subject: Union[str, LazyI18nString],
        template: Union[str, LazyI18nString],
        context: Dict[str, Any] = None,
        log_entry_type: str = "pretix_withdrawal.email.withdrawal.received",
        user: User = None,
    ):
        with language(self.locale, (self.event or self.organizer).settings.region):
            try:
                email_content = render_mail(template, context)
                subject = format_map(subject, context)
                mail(
                    recipient,
                    subject,
                    template,
                    context,
                    self.event,
                    self.locale,
                )
            except SendMailException:
                raise
            else:
                self.log_action(
                    log_entry_type,
                    user=user,
                    data={
                        "subject": subject,
                        "message": email_content,
                        "recipient": recipient,
                    },
                )

    def _send_notification_mail(self):
        # currently notifications only work on event-level, this re-builds it manually
        # see pretix.base.services.notifications.send_notification_mail
        # TODO: allow organizer-level notifications

        if self.event:
            url = build_absolute_uri(
                self.event,
                "plugins:pretix_withdrawal:control.event.view",
                kwargs={
                    "organizer": self.organizer.slug,
                    "event": self.event.slug,
                    "pk": self.pk,
                },
            )
        else:
            url = build_absolute_uri(
                self.organizer,
                "plugins:pretix_withdrawal:control.organizer.view",
                kwargs={
                    "organizer": self.organizer.slug,
                    "pk": self.pk,
                },
            )

        notification = Notification(
            event=self.event,
            title=_("Withdrawal for {order}").format(order=self.order_code),
            url=url,
        )
        notification.add_action(_("View withdrawal"), url)
        notification.add_attribute(
            _("From"), "%s (%s)" % (self.name, self.email) if self.name else self.email
        )
        if self.order:
            notification.add_attribute(_("Order"), self.order.code)
            notification.add_action(
                _("View order"),
                build_absolute_uri(
                    self.event,
                    "control:event.order",
                    kwargs={
                        "organizer": self.organizer.slug,
                        "event": self.order.event.slug,
                        "code": self.order.code,
                    },
                ),
            )
        else:
            notification.add_attribute(_("Order (code unknown)"), self.order_code)

        if self.event:
            notification.add_attribute(_("Event"), self.event)
        if self.message:
            notification.add_attribute(_("Message"), self.message)

        ctx = {
            "site": settings.PRETIX_INSTANCE_NAME,
            "site_url": settings.SITE_URL,
            "color": settings.PRETIX_PRIMARY_COLOR,
            "notification": notification,
            "settings_url": build_absolute_uri(
                self.organizer,
                "plugins:pretix_withdrawal:control.organizer.settings",
            ),
        }
        tpl_html = get_template("pretixbase/email/notification.html")

        body_html = tpl_html.render(ctx)
        inliner = css_inline.CSSInliner(keep_style_tags=False)
        body_html = inliner.inline(body_html)

        tpl_plain = get_template("pretixbase/email/notification.txt")
        body_plain = tpl_plain.render(ctx)

        guid = uuid.uuid4()
        m = OutgoingMail.objects.create(
            guid=guid,
            to=[
                m.strip()
                for m in self.organizer.settings.withdrawal_contact_mail.split(",")
            ],
            subject="[{}] {}: {}".format(
                settings.PRETIX_INSTANCE_NAME,
                (
                    (self.event.settings.mail_prefix or self.event.slug.upper())
                    if self.event
                    else self.organizer.slug.upper()
                ),
                notification.title,
            ),
            body_plain=body_plain,
            body_html=body_html,
            sender=settings.MAIL_FROM_NOTIFICATIONS,
            headers={
                "X-Auto-Response-Suppress": "OOF, NRN, AutoReply, RN",
                "Auto-Submitted": "auto-generated",
                "X-Mailer": "pretix",
                "X-PX-Correlation": str(guid),
            },
        )
        mail_send_task.apply_async(
            kwargs={
                "outgoing_mail": m.pk,
            }
        )
