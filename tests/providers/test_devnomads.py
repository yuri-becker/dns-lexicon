"""Integration tests for PowerDNS"""

from unittest import TestCase

import pytest
from integration_tests import IntegrationTestsV2


# Hook into testing framework by inheriting unittest.TestCase and reuse
# the tests which *each and every* implementation of the interface must
# pass, by inheritance from integration_tests.IntegrationTests
class PowerdnsProviderTests(TestCase, IntegrationTestsV2):
    """TestCase for DevNomads"""

    provider_name = "devnomads"
    domain = "example.com"

    def _filter_headers(self):
        return ["Authorization"]

    def _filter_post_data_parameters(self):
        return ["bearer_token"]
