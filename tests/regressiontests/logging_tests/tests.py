from __future__ import with_statement

import copy

from django.conf import compat_patch_logging_config
from django.test import TestCase


# logging config prior to using filter with mail_admins
OLD_LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler'
        }
    },
    'loggers': {
        'django.request': {
            'handlers': ['mail_admins'],
            'level': 'ERROR',
            'propagate': True,
        },
    }
}



class PatchLoggingConfigTest(TestCase):
    def test_filter_added(self):
        """
        Test that debug-false filter is added to mail_admins handler if it has
        no filters.

        """
        config = copy.deepcopy(OLD_LOGGING)
        compat_patch_logging_config(config)

        self.assertEqual(
            config["handlers"]["mail_admins"]["filters"],
            ['require_debug_false'])


    def test_filter_configuration(self):
        """
        Test that the debug-false filter is a CallbackFilter with a callback
        that works as expected (returns ``not DEBUG``).

        """
        config = copy.deepcopy(OLD_LOGGING)
        compat_patch_logging_config(config)

        flt = config["filters"]["require_debug_false"]

        self.assertEqual(flt["()"], "django.utils.log.CallbackFilter")

        callback = flt["callback"]

        with self.settings(DEBUG=True):
            self.assertEqual(callback("record is not used"), False)

        with self.settings(DEBUG=False):
            self.assertEqual(callback("record is not used"), True)


    def test_no_patch_if_filters_key_exists(self):
        """
        Test that the logging configuration is not modified if the mail_admins
        handler already has a "filters" key.

        """
        config = copy.deepcopy(OLD_LOGGING)
        config["handlers"]["mail_admins"]["filters"] = []
        new_config = copy.deepcopy(config)
        compat_patch_logging_config(new_config)

        self.assertEqual(config, new_config)

    def test_no_patch_if_no_mail_admins_handler(self):
        """
        Test that the logging configuration is not modified if the mail_admins
        handler is not present.

        """
        config = copy.deepcopy(OLD_LOGGING)
        config["handlers"].pop("mail_admins")
        new_config = copy.deepcopy(config)
        compat_patch_logging_config(new_config)

        self.assertEqual(config, new_config)
