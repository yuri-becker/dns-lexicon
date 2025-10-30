"""Module provider for Hetzner"""

import json
import logging
from argparse import ArgumentParser
from typing import Any, TypedDict, cast

import requests

from lexicon.config import ConfigResolver
from lexicon.exceptions import AuthenticationError, LexiconError
from lexicon.interfaces import Provider as BaseProvider

LOGGER = logging.getLogger(__name__)

RrsetRecord = TypedDict("RrsetRecord", {"value": str})
RrSet = TypedDict(
    "RrSet",
    {
        "id": str,
        "name": str,
        "type": str,
        "ttl": int,
        "records": list[RrsetRecord],
    },
)
CreateRecordRequest = TypedDict(
    "CreateRecordRequest",
    {"name": str, "type": str, "ttl": int | None, "records": list[RrsetRecord]},
)
SetRecordsRequest = TypedDict("SetRecordsRequest", {"records": list[RrsetRecord]})
SetTtlRequest = TypedDict("SetTtlRequest", {"ttl": int})


class Provider(BaseProvider):
    """
    Provider for Hetzner Cloud DNS at https://console.hetzner.com or https://api.hetzner.cloud.
    Does not work for konsoleH, Domain Robot, or dns.hetzner.com.
    If you're still using dns.hetzner.com,
    see the [official migration guide](https://docs.hetzner.com/networking/dns/migration-to-hetzner-console/process),
    or use the `hetzner_legacy` provider.
    """

    API_ENDPOINT = "https://api.hetzner.cloud/v1/zones"

    @staticmethod
    def get_nameservers() -> list[str]:
        return ["ns.hetzner.com"]

    @staticmethod
    def configure_parser(parser: ArgumentParser) -> None:
        parser.add_argument("--auth-token", help="Specify Hetzner DNS API token")

    def __init__(self, config: ConfigResolver | dict[str, Any]):
        super(Provider, self).__init__(config)

    def authenticate(self) -> None:
        self.domain_id = self._get_zone_by_domain(self.domain)["id"]

    def cleanup(self) -> None:
        pass

    def create_record(self, rtype: str, name: str, content: str) -> bool:
        records = self.list_records(rtype, name, content)
        if len(records) >= 1:
            for record in records:
                LOGGER.info(
                    f"Record {rtype} {name} {content} already exists and has id {record['id']}",
                )
            return True

        ttl = self._get_lexicon_option("ttl")
        self._post(
            f"/{self.domain_id}/rrsets",
            cast(
                dict[str, Any],
                CreateRecordRequest(
                    name=self._get_record_name(self.domain, name),
                    type=rtype,
                    ttl=int(ttl) if ttl else None,
                    records=[RrsetRecord(value=name)],
                ),
            ),
        )
        return True

    def list_records(
        self,
        rtype: str | None = None,
        name: str | None = None,
        content: str | None = None,
    ) -> list[dict[str, Any]]:
        rrsets: list[RrSet] = self._get(f"/{self.domain_id}/rrsets")["rrsets"]
        return [
            {
                "id": rrset["id"],
                "name": self._full_name(rrset["name"]),
                "content": record["value"],
                "type": rrset["type"],
                "ttl": rrset["ttl"],
            }
            for rrset in rrsets
            for record in rrset["records"]
            if (rtype is None or rrset["type"] == rtype)
            and (
                name is None or self._full_name(rrset["name"]) == self._full_name(name)
            )
            and (content is None or record["value"] == content)
        ]

    def update_record(
        self,
        identifier: str | None = None,
        rtype: str | None = None,
        name: str | None = None,
        content: str | None = None,
    ) -> bool:
        if name is None:
            raise LexiconError("Cannot update record - name has to be set.")
        if rtype is None:
            raise LexiconError("Cannot update record - rtype has to be set.")

        rrset_name = self._get_record_name(self.domain, name)
        if content is not None:
            self._post(
                f"/{self.domain_id}/rrsets/{rrset_name}/{rtype}/actions/set_records",
                cast(
                    dict[str, Any],
                    SetRecordsRequest(records=[RrsetRecord(value=content)]),
                ),
            )

        ttl = self._get_lexicon_option("ttl")
        if ttl is not None:
            self._post(
                f"/{self.domain_id}/rrsets/{rrset_name}/{rtype}/actions/change_ttl",
                cast(dict[str, Any], SetTtlRequest(ttl=int(ttl))),
            )

        return True

    def delete_record(
        self,
        identifier: str | None = None,
        rtype: str | None = None,
        name: str | None = None,
        content: str | None = None,
    ) -> bool:
        if name is None:
            raise LexiconError("Cannot delete record - name has to be set.")
        if rtype is None:
            raise LexiconError("Cannot delete record - rtype has to be set.")

        rrset_name = self._get_record_name(self.domain, name)
        self._delete(f"/{self.domain_id}/rrsets/{rrset_name}/{rtype}")
        return True

    # Helpers
    def _request(
        self,
        action: str = "GET",
        url: str = "/",
        data: dict[str, Any] | None = {},
        query_params: dict[str, Any] | None = None,
    ):
        data = data or {}
        query_params = query_params or {}
        response = requests.request(
            action,
            self.API_ENDPOINT + url,
            params=query_params,
            data=json.dumps(data),
            headers={
                "Authorization": f"Bearer {self._get_provider_option('auth_token')}",
                "Content-Type": "application/json",
            },
        )
        # if the request fails for any reason, throw an error.
        response.raise_for_status()
        return response.json()

    def _get_zone_by_domain(self, domain: str) -> dict[str, Any]:
        """
        Requests the zone object for the given domain name
        :param domain: Name of domain for which dns zone should be searched
        :rtype: dict
        :return: "zone" field of the response at docs.hetzner.cloud/reference/cloud#zones-get-a-zone
        :raises Exception: If no zone was found
        :raises KeyError, ValueError: If the response is malformed
        :raises urllib.error.HttpError: If request to /zones/domain did not return 200
        """
        try:
            return self._get(f"/{domain}")["zone"]
        except requests.HTTPError as err:
            if err.response.status_code == 401:
                raise AuthenticationError()
            elif err.response.status_code == 404:
                raise LexiconError(f"There is no zone for {domain}.")
            else:
                raise LexiconError(err)

    def _get_record_name(self, domain: str, record_name: str) -> str:
        """
        Get the name attribute appropriate for hetzner api. This means it's the name
        without domain name if record name ends with managed domain name else a fqdn
        :param domain: Name of domain for which dns zone should be searched
        :param record_name: The record name to convert
        :return: The record name in an appropriate format for hetzner api
        """
        if record_name.rstrip(".").endswith(domain):
            record_name = self._relative_name(record_name)
        return record_name
