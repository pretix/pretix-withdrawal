from django.conf import settings
from django.utils.translation import gettext_lazy as _

from . import __version__

try:
    from pretix.base.plugins import PLUGIN_LEVEL_EVENT_ORGANIZER_HYBRID, PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2026.3.0 or above to run this plugin!")


class PluginApp(PluginConfig):
    default = True
    name = "pretix_withdrawal"
    verbose_name = "Withdrawal"

    class PretixPluginMeta:
        name = _("Withdrawal")
        author = "pretix team"
        description = _(
            "Add support to withdraw from pretix online purchases to comply with EU legislation."
        )
        visible = True
        version = __version__
        category = "FEATURE"
        compatibility = "pretix>=2026.3.0.dev0"
        level = PLUGIN_LEVEL_EVENT_ORGANIZER_HYBRID
        settings_links = [
            (
                (_("Settings"), _("Withdrawal")),
                "plugins:pretix_withdrawal:control.organizer.settings",
                {},
            ),
            (
                (_("Settings"), _("Withdrawal")),
                "plugins:pretix_withdrawal:control.event.settings",
                {},
            ),
        ]
        navigation_links = [
            (
                (_("Orders"), _("Withdrawals")),
                "plugins:pretix_withdrawal:control.event.index",
                {},
            ),
            (
                (_("Withdrawals"),),
                "plugins:pretix_withdrawal:control.organizer.index",
                {},
            ),
        ]

    def ready(self):
        from . import signals  # NOQA
