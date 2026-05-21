from django.urls import path

from . import views

urlpatterns = [
    path(
        "control/organizer/<str:organizer>/settings/withdrawal",
        views.OrganizerSettingsView.as_view(),
        name="control.organizer.settings",
    ),
    path(
        "control/organizer/<str:organizer>/withdrawals",
        views.OrganizerWithdrawalListView.as_view(),
        name="control.organizer.index",
    ),
    path(
        "control/organizer/<str:organizer>/withdrawals/<int:pk>",
        views.OrganizerWithdrawalDetailView.as_view(),
        name="control.organizer.view",
    ),
    path(
        "control/organizer/<str:organizer>/withdrawals/<int:pk>/settle",
        views.OrganizerWithdrawalSettleView.as_view(),
        name="control.organizer.settle",
    ),
    path(
        "control/event/<str:organizer>/<str:event>/settings/withdrawal",
        views.EventSettingsView.as_view(),
        name="control.event.settings",
    ),
    path(
        "control/event/<str:organizer>/<str:event>/withdrawals/",
        views.EventWithdrawalListView.as_view(),
        name="control.event.index",
    ),
    path(
        "control/event/<str:organizer>/<str:event>/withdrawals/<int:pk>",
        views.EventWithdrawalDetailView.as_view(),
        name="control.event.view",
    ),
    path(
        "control/event/<str:organizer>/<str:event>/withdrawals/<int:pk>/settle",
        views.EventWithdrawalSettleView.as_view(),
        name="control.event.settle",
    ),
]
organizer_patterns = [
    path(
        "_withdraw/",
        views.WithdrawalCreate.as_view(),
        name="presale.organizer.create",
    ),
]
event_patterns = [
    path("withdraw/", views.WithdrawalCreate.as_view(), name="presale.event.create"),
]
