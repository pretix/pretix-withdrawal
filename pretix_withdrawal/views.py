from datetime import datetime
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, ListView, TemplateView
from pretix.base.i18n import get_language_without_region
from pretix.base.models import Order
from pretix.base.models.organizer import TeamQuerySet
from pretix.control.permissions import (
    EventPermissionRequiredMixin,
)
from pretix.control.views import PaginationMixin
from pretix.control.views.event import EventSettingsViewMixin
from pretix.control.views.organizer import (
    OrganizerDetailViewMixin,
    OrganizerSettingsFormView,
)
from pretix.multidomain.urlreverse import eventreverse

from .forms import (
    CommentForm,
    CreateForm,
    OrganizerSettingsForm,
    OrganizerWithdrawalFilterForm,
    WithdrawalFilterForm,
)
from .models import Withdrawal
from .signals import _withdrawal_url


class WithdrawalCreate(CreateView):
    model = Withdrawal
    form_class = CreateForm
    context_object_name = "withdrawal"
    template_name = "pretix_withdrawal/presale_form.html"

    def get(self, request, *args, **kwargs):
        if request.organizer.settings.withdrawal_use_custom:
            return redirect(
                _withdrawal_url(request.organizer, getattr(request, "event", None))
            )
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if request.organizer.settings.withdrawal_use_custom:
            return redirect(
                _withdrawal_url(request.organizer, getattr(request, "event", None))
            )
        return super().post(request, *args, **kwargs)

    @transaction.atomic
    def form_valid(self, form):
        # set instance.organizer and try to match order_code
        # if order_code matches, set event as well
        # set instance.event to request.event only if no order_code matched
        form.instance.organizer = self.request.organizer
        form.instance.locale = get_language_without_region()

        orders_qs = Order.objects.filter(
            organizer=self.request.organizer,
        )
        if "-" in form.instance.order_code:
            event_slug, order_code = form.instance.order_code.split("-", 1)
            orders_qs = orders_qs.filter(
                event__slug__icontains=event_slug,
                code__icontains=Order.normalize_code(order_code),
            )
        else:
            orders_qs = orders_qs.filter(
                code__icontains=Order.normalize_code(form.instance.order_code)
            )

        if orders_qs.count() > 1 and self.request.event:
            orders_qs = orders_qs.filter(event=self.request.event)

        form.instance.order = orders_qs.first()
        if form.instance.order:
            form.instance.event_id = form.instance.order.event_id
        elif hasattr(self.request, "event"):
            form.instance.event = self.request.event

        ret = super().form_valid(form)
        form.instance.log_action(
            "pretix_withdrawal.withdrawal.received",
            data=dict(form.cleaned_data),
            user=self.request.user,
        )

        # send confirmation e-mail to customer and organizer
        form.instance.mail_withdrawal_received()
        if form.instance.order and form.instance.order.email != form.instance.email:
            form.instance.mail_warn_withdrawal_received()

        messages.success(
            self.request,
            str(self.request.organizer.settings.withdrawal_received_success_msg).format(
                email=form.instance.email,
                code=form.instance.order_code,
            ),
        )

        return ret

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organizer"] = self.request.organizer
        if self.request.method == "GET":
            kwargs["initial"] = {
                "order_code": self.request.GET.get("code", ""),
                "email": self.request.GET.get("email", ""),
            }
        return kwargs

    def form_invalid(self, form):
        messages.error(
            self.request, _("We could not save your changes. See below for details.")
        )
        return super().form_invalid(form)

    def get_success_url(self):
        if hasattr(self.request, "event"):
            return eventreverse(self.request.event, "presale:event.index", kwargs={})
        return eventreverse(
            self.request.organizer, "presale:organizer.index", kwargs={}
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if hasattr(self.request, "event"):
            ctx["basetemplate"] = "pretixpresale/event/base.html"
        else:
            ctx["basetemplate"] = "pretixpresale/organizers/base.html"

        ctx["headline"] = self.request.organizer.settings.withdrawal_label
        ctx["form_above_msg"] = (
            self.request.organizer.settings.withdrawal_form_above_msg
        )
        ctx["submit_label"] = self.request.organizer.settings.withdrawal_submit_label

        return ctx


class WithdrawalListViewAbstract(PaginationMixin, ListView):
    model = Withdrawal
    context_object_name = "withdrawals"
    paginate_by = 30
    template_name = "pretix_withdrawal/control/list.html"
    filter_form_class = WithdrawalFilterForm

    def get_queryset(self):
        raise NotImplementedError()

    @cached_property
    def filter_form(self):
        return self.filter_form_class(
            data=self.request.GET,
            request=self.request,
        )

    @cached_property
    def withdrawals_without_event_exist(self):
        return self.request.organizer.withdrawals.filter(
            event__isnull=True, settled__isnull=True
        ).exists()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = self.filter_form
        ctx["withdrawals_without_event_exist"] = self.withdrawals_without_event_exist
        return ctx


class OrganizerWithdrawalPermissionMixin:
    @cached_property
    def events_without_permission_exist(self):
        return self.request.organizer.events.filter(
            ~Exists(
                self.request.user.teams.with_event_permission(
                    "event.orders:read"
                ).filter(
                    Q(all_events=True) | Q(limit_events=OuterRef("pk")),
                    organizer_id=OuterRef("organizer_id"),
                )
            )
        ).exists()


class OrganizerWithdrawalListView(
    OrganizerDetailViewMixin,
    OrganizerWithdrawalPermissionMixin,
    WithdrawalListViewAbstract,
):
    filter_form_class = OrganizerWithdrawalFilterForm

    @cached_property
    def filter_form(self):
        return self.filter_form_class(
            data=self.request.GET,
            request=self.request,
            # only allow filtering to events_none if user is allowed to see withdrawals without events
            events_include_none=not self.events_without_permission_exist,
        )

    def get_queryset(self):
        qs = self.request.organizer.withdrawals.all().select_related(
            "event",
            "order",
        )

        if (
            not self.request.user.has_active_staff_session(
                self.request.session.session_key
            )
            and self.events_without_permission_exist
        ):
            # user does not have access to all events: limit withdrawals to events
            # the user can event.orders:read only. Do not show unassigned withdrawals!
            qs = qs.filter(
                Q(
                    event__organizer_id__in=self.request.user.teams.filter(
                        TeamQuerySet.event_permission_q("event.orders:read"),
                        all_events=True,
                    ).values_list("organizer", flat=True)
                )
                | Q(
                    event_id__in=self.request.user.teams.filter(
                        TeamQuerySet.event_permission_q("event.orders:read"),
                    ).values_list("limit_events__id", flat=True)
                )
            )

        if self.filter_form.is_valid():
            qs = self.filter_form.filter_qs(qs)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["basetemplate"] = "pretixcontrol/organizers/base.html"
        ctx["events_without_permission_exist"] = self.events_without_permission_exist
        return ctx


class EventWithdrawalListView(EventPermissionRequiredMixin, WithdrawalListViewAbstract):
    permission = "event.orders:read"

    def get_queryset(self):
        qs = self.request.event.withdrawals.all().select_related(
            "event",
            "order",
        )

        if self.filter_form.is_valid():
            qs = self.filter_form.filter_qs(qs)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["basetemplate"] = "pretixcontrol/event/base.html"
        return ctx


class WithdrawalDetailViewAbstract(DetailView):
    model = Withdrawal
    template_name = "pretix_withdrawal/control/detail.html"
    context_object_name = "withdrawal"

    @cached_property
    def withdrawal(self):
        if hasattr(self, "object") and self.object:
            return self.object
        return self.get_object()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["comment_form"] = CommentForm(
            initial={"internal_notes": self.withdrawal.internal_notes}
        )
        return ctx

    def post(self, *args, **kwargs):
        form = CommentForm(self.request.POST)
        if form.is_valid():
            if (
                form.cleaned_data.get("internal_notes")
                != self.withdrawal.internal_notes
            ):
                self.withdrawal.internal_notes = form.cleaned_data.get("internal_notes")
                self.withdrawal.log_action(
                    "pretix_withdrawal.comment",
                    user=self.request.user,
                    data={"new_comment": form.cleaned_data.get("internal_notes")},
                )
                self.withdrawal.save(update_fields=["internal_notes"])
            messages.success(self.request, _("The comment has been updated."))
        else:
            messages.error(self.request, _("Could not update the comment."))
        return redirect(self.get_success_url())


class OrganizerWithdrawalDetailView(
    OrganizerDetailViewMixin,
    OrganizerWithdrawalPermissionMixin,
    WithdrawalDetailViewAbstract,
):
    def get_object(self, queryset=None):
        withdrawal = get_object_or_404(
            Withdrawal.objects.select_related("order", "event"),
            organizer=self.request.organizer,
            pk=self.kwargs.get("pk"),
        )
        if not withdrawal.event and self.events_without_permission_exist:
            # only allow users with access to all events to access withdrawals that are not assigned to an event
            raise PermissionDenied(
                _("You do not have permission to view this content.")
            )
        return withdrawal

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["basetemplate"] = "pretixcontrol/organizers/base.html"
        return ctx

    def get_success_url(self):
        return reverse(
            "plugins:pretix_withdrawal:control.organizer.view",
            kwargs={
                "organizer": self.request.organizer.slug,
                "pk": self.withdrawal.pk,
            },
        )


class EventWithdrawalDetailView(
    EventPermissionRequiredMixin, WithdrawalDetailViewAbstract
):
    permission = "event.orders:read"

    def get_object(self, queryset=None):
        return get_object_or_404(
            Withdrawal.objects.select_related("order"),
            organizer=self.request.organizer,
            event=self.request.event,
            pk=self.kwargs.get("pk"),
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["basetemplate"] = "pretixcontrol/event/base.html"
        return ctx

    def get_success_url(self):
        return reverse(
            "plugins:pretix_withdrawal:control.event.view",
            kwargs={
                "organizer": self.request.organizer.slug,
                "event": self.request.event.slug,
                "pk": self.withdrawal.pk,
            },
        )


class WithdrawalSettleMixin:
    model = Withdrawal
    template_name = "pretix_withdrawal/control/settle.html"
    context_object_name = "withdrawal"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["basetemplate"] = self.basetemplate
        order = self.withdrawal.order
        ctx["warn_order_cancel"] = order and not (
            order.status == "c"
            or order.status == "e"
            or (order.status == "p" and order.count_positions == 0)
        )
        return ctx

    def post(self, *args, **kwargs):
        if not self.withdrawal.settled:
            self.withdrawal.settled = datetime.now()
            self.withdrawal.save(update_fields=["settled"])
        messages.success(self.request, _("The withdrawal is settled."))
        if "next" in self.request.GET and url_has_allowed_host_and_scheme(
            self.request.GET.get("next"), allowed_hosts=None
        ):
            return redirect(self.request.GET.get("next"))
        return redirect(self.get_success_url())


class OrganizerWithdrawalSettleView(
    WithdrawalSettleMixin, OrganizerWithdrawalDetailView
):
    basetemplate = "pretixcontrol/organizers/base.html"

    def get_success_url(self):
        return reverse(
            "plugins:pretix_withdrawal:control.organizer.view",
            kwargs={
                "organizer": self.request.organizer.slug,
                "pk": self.withdrawal.pk,
            },
        )


class EventWithdrawalSettleView(WithdrawalSettleMixin, EventWithdrawalDetailView):
    basetemplate = "pretixcontrol/event/base.html"

    def get_success_url(self):
        return reverse(
            "plugins:pretix_withdrawal:control.event.view",
            kwargs={
                "organizer": self.request.organizer.slug,
                "event": self.request.event.slug,
                "pk": self.withdrawal.pk,
            },
        )


class OrganizerSettingsView(OrganizerSettingsFormView):
    model = Withdrawal
    form_class = OrganizerSettingsForm
    template_name = "pretix_withdrawal/control/settings.html"

    def get_success_url(self) -> str:
        return reverse(
            "plugins:pretix_withdrawal:control.organizer.settings",
            kwargs={
                "organizer": self.request.organizer.slug,
            },
        )


class EventSettingsView(
    EventSettingsViewMixin, EventPermissionRequiredMixin, TemplateView
):
    template_name = "pretix_withdrawal/control/event_settings.html"
    permission = "event.settings.general:write"

    def get_context_data(self, *args, **kwargs) -> dict:
        context = super().get_context_data(*args, **kwargs)
        context["organizer_settings_url"] = reverse(
            "plugins:pretix_withdrawal:control.organizer.settings",
            kwargs={
                "organizer": self.request.organizer.slug,
            },
        )
        return context
