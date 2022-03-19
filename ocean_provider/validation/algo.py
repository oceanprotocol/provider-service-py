#
# Copyright 2021 Ocean Protocol Foundation
# SPDX-License-Identifier: Apache-2.0
#
import json
import logging

from ocean_provider.constants import BaseURLs
from ocean_provider.serializers import StageAlgoSerializer
from ocean_provider.utils.basics import get_asset_from_metadatastore, get_config
from ocean_provider.utils.url import append_userdata
from ocean_provider.utils.util import (
    check_asset_consumable,
    decode_from_data,
    get_metadata_url,
    get_service_files_list,
    msg_hash,
    record_consume_request,
    validate_order,
    validate_transfer_not_used_for_other_service,
)

logger = logging.getLogger(__name__)


class WorkflowValidator:
    def __init__(self, web3, consumer_address, provider_wallet, data):
        """Initializes the validator."""
        self.web3 = web3
        self.consumer_address = consumer_address
        self.provider_wallet = provider_wallet
        self.data = data
        self.workflow = dict({"stages": []})

    def validate(self):
        """Validates for input and output contents."""
        if not self.validate_input():
            return False

        if not self.validate_output():
            return False

        self.workflow["stages"].append(
            {
                "index": 0,
                "input": self.validated_inputs,
                "compute": {
                    "Instances": 1,
                    "namespace": "ocean-compute",
                    "maxtime": 3600,
                },
                "algorithm": self.validated_algo_dict,
                "output": self.validated_output_dict,
            }
        )

        return True

    def validate_input(self, index=0):
        """Validates input dictionary."""
        main_input = self.data["dataset"]
        additional_inputs = self.data.get("additionalDatasets", list())

        if not additional_inputs:
            additional_inputs = []

        if not isinstance(additional_inputs, list):
            self.error = "Additional input is invalid or can not be decoded."
            return False

        all_data = [main_input] + additional_inputs
        algo_data = self.data["algorithm"]

        self.validated_inputs = []
        valid_until_list = []

        for index, input_item in enumerate(all_data):
            input_item["algorithm"] = algo_data
            input_item_validator = InputItemValidator(
                self.web3,
                self.consumer_address,
                self.provider_wallet,
                input_item,
                {"environment": self.data.get("environment")},
                index,
            )

            status = input_item_validator.validate()
            if not status:
                prefix = f"Error in input at index {index}: " if index else ""
                self.error = prefix + input_item_validator.error
                return False

            self.validated_inputs.append(input_item_validator.validated_inputs)
            valid_until_list.append(input_item_validator.valid_until)

            if index == 0:
                self.service_endpoint = input_item_validator.service.service_endpoint

        self.valid_until = min(valid_until_list)
        status = self._build_and_validate_algo(algo_data)
        if not status:
            return False

        return True

    def validate_output(self):
        """Validates output dictionary after stage build."""
        output_def = decode_from_data(self.data, "output", dec_type="dict")

        if output_def == -1:
            self.error = "Output is invalid or can not be decoded."
            return False

        self.validated_output_dict = build_stage_output_dict(
            output_def,
            self.service_endpoint,
            self.consumer_address,
            self.provider_wallet,
        )

        return True

    def _build_and_validate_algo(self, algo_data):
        """Returns False if invalid, otherwise sets the validated_algo_dict attribute."""
        algorithm_did = algo_data.get("documentId")
        self.algo_service = None
        algo = None

        if algorithm_did and not algo_data.get("meta"):
            algorithm_tx_id = algo_data.get("transferTxId")
            algorithm_service_id = algo_data.get("serviceId")

            algo = get_asset_from_metadatastore(get_metadata_url(), algorithm_did)

            try:
                asset_type = algo.metadata["type"]
            except ValueError:
                asset_type = None

            if asset_type != "algorithm":
                self.error = f"DID {algorithm_did} is not a valid algorithm"
                return False

            if not algorithm_service_id:
                self.error = "No serviceId in algorithm input item."
                return False

            try:
                self.algo_service = algo.get_service_by_id(algorithm_service_id)
                algorithm_token_address = self.algo_service.datatoken_address

                if self.algo_service.type == "compute":
                    asset_urls = get_service_files_list(
                        self.algo_service, self.provider_wallet
                    )

                    if not asset_urls:
                        self.error = "Services in algorithm with compute type must be in the same provider you are calling."
                        return False

                if not self.algo_service:
                    self.error = "Failed to retrieve purchased algorithm service id."
                    return False
                logger.debug("validate_order called for ALGORITHM usage.")
                _tx, _order_log, _provider_fees_log = validate_order(
                    self.web3,
                    self.consumer_address,
                    algorithm_tx_id,
                    algo,
                    self.algo_service,
                )
                validate_transfer_not_used_for_other_service(
                    algorithm_did,
                    self.algo_service.id,
                    algorithm_tx_id,
                    self.consumer_address,
                    algorithm_token_address,
                )
                record_consume_request(
                    algorithm_did,
                    self.algo_service.id,
                    algorithm_tx_id,
                    self.consumer_address,
                    algorithm_token_address,
                    1,
                )
            except Exception as e:
                logger.debug(
                    f"validate_order for ALGORITHM failed with error {str(e)}."
                )
                self.error = "Algorithm is already in use or can not be found on chain."
                return False

        algorithm_dict = StageAlgoSerializer(
            self.consumer_address,
            self.provider_wallet,
            algo_data,
            self.algo_service,
            algo,
        ).serialize()

        valid, error_msg = validate_formatted_algorithm_dict(
            algorithm_dict, algorithm_did
        )

        if not valid:
            self.error = error_msg
            return False

        self.validated_algo_dict = algorithm_dict

        return True


def validate_formatted_algorithm_dict(algorithm_dict, algorithm_did):
    if algorithm_did and not (
        algorithm_dict.get("url") or algorithm_dict.get("remote")
    ):
        return False, f"cannot get url for the algorithmDid {algorithm_did}"

    if (
        not algorithm_dict.get("url")
        and not algorithm_dict.get("rawcode")
        and not algorithm_dict.get("remote")
    ):
        return (
            False,
            "algorithmMeta must define one of `url` or `rawcode` or `remote`, but all seem missing.",
        )  # noqa

    container = algorithm_dict.get("container", {})
    # Validate `container` data
    if not (
        container.get("entrypoint") and container.get("image") and container.get("tag")
    ):
        return (
            False,
            "algorithm `container` must specify values for all of entrypoint, image and tag.",
        )  # noqa

    return True, ""


class InputItemValidator:
    def __init__(
        self, web3, consumer_address, provider_wallet, data, extra_data, index
    ):
        """Initializes the input item validator."""
        self.web3 = web3
        self.consumer_address = consumer_address
        self.provider_wallet = provider_wallet
        self.data = data
        self.extra_data = extra_data
        self.index = index

    def validate(self):
        required_keys = ["documentId", "transferTxId"]

        for req_item in required_keys:
            if not self.data.get(req_item):
                self.error = f"No {req_item} in input item."
                return False

        if not self.data.get("serviceId") and self.data.get("serviceId") != 0:
            self.error = "No serviceId in input item."
            return False

        self.did = self.data.get("documentId")
        self.asset = get_asset_from_metadatastore(get_metadata_url(), self.did)

        if not self.asset:
            self.error = f"Asset for did {self.did} not found."
            return False

        self.service = self.asset.get_service_by_id(self.data["serviceId"])

        if not self.service:
            self.error = f"Service id {self.data['serviceId']} not found."
            return False

        consumable, message = check_asset_consumable(
            self.asset, self.consumer_address, logger, self.service.service_endpoint
        )

        if not consumable:
            self.error = message
            return False

        if self.service.type not in ["access", "compute"]:
            self.error = "Services in input can only be access or compute."
            return False

        if self.service.type != "compute" and self.index == 0:
            self.error = "Service for main asset must be compute."
            return False

        asset_urls = get_service_files_list(self.service, self.provider_wallet)

        if self.service.type == "compute" and not asset_urls:
            self.error = "Services in input with compute type must be in the same provider you are calling."
            return False

        if self.service.type == "compute":
            if not self.validate_algo():
                return False

        if asset_urls:
            asset_urls = [append_userdata(a_url, self.data) for a_url in asset_urls]
            self.validated_inputs = dict(
                {"index": self.index, "id": self.did, "url": asset_urls}
            )
        else:
            self.validated_inputs = {
                "index": self.index,
                "id": self.did,
                "remote": {
                    "txid": self.data.get("transferTxId"),
                    "serviceId": self.service.id,
                },
            }

            userdata = self.data.get("userdata")
            if userdata:
                self.validate_inputs["remote"]["userdata"] = userdata

        return self.validate_usage()

    def _validate_trusted_algos(
        self, algorithm_did, trusted_algorithms, trusted_publishers
    ):
        if not trusted_algorithms and not trusted_publishers:
            return True

        if trusted_publishers:
            algo_ddo = get_asset_from_metadatastore(get_metadata_url(), algorithm_did)
            if algo_ddo.nft["owner"] not in trusted_publishers:
                self.error = "this algorithm is not from a trusted publisher"
                return False

        if trusted_algorithms:
            try:
                did_to_trusted_algo_dict = {
                    algo["did"]: algo for algo in trusted_algorithms
                }
                if algorithm_did not in did_to_trusted_algo_dict:
                    self.error = f"this algorithm did {algorithm_did} is not trusted."
                    return False

            except KeyError:
                self.error = (
                    "Some algos in the publisherTrustedAlgorithms don't have a did."
                )
                return False

            trusted_algo_dict = did_to_trusted_algo_dict[algorithm_did]
            allowed_files_checksum = trusted_algo_dict.get("filesChecksum")
            allowed_container_checksum = trusted_algo_dict.get(
                "containerSectionChecksum"
            )
            algo_ddo = get_asset_from_metadatastore(
                get_metadata_url(), trusted_algo_dict["did"]
            )

            service = algo_ddo.get_service_by_id(
                self.data["algorithm"].get("serviceId")
            )

            files_checksum = msg_hash(service.encrypted_files)
            if allowed_files_checksum and files_checksum != allowed_files_checksum:
                self.error = f"filesChecksum for algorithm with did {algo_ddo.did} does not match"
                return False

            container_section_checksum = msg_hash(
                json.dumps(
                    algo_ddo.metadata["algorithm"]["container"], separators=(",", ":")
                )
            )
            if (
                allowed_container_checksum
                and container_section_checksum != allowed_container_checksum
            ):
                self.error = f"containerSectionChecksum for algorithm with did {algo_ddo.did} does not match"
                return False

        return True

    def validate_algo(self):
        """Validates algorithm details that allow the algo dict to be built."""
        algo_data = self.data["algorithm"]
        algorithm_meta = algo_data.get("meta")
        algorithm_did = algo_data.get("documentId")
        if algorithm_did is None and algorithm_meta is None:
            self.error = "both meta and documentId are missing from algorithm input, at least one of these is required."
            return False

        privacy_options = self.service.compute_dict

        if algorithm_did:
            return self._validate_trusted_algos(
                algorithm_did,
                privacy_options.get("publisherTrustedAlgorithms", []),
                privacy_options.get("publisherTrustedAlgorithmPublishers", []),
            )

        allow_raw_algo = privacy_options.get("allowRawAlgorithm", False)
        if allow_raw_algo is False:
            self.error = f"cannot run raw algorithm on this did {self.did}."
            return False

        return True

    def validate_usage(self):
        """Verify that the tokens have been transferred to the provider's wallet."""
        tx_id = self.data.get("transferTxId")
        token_address = self.service.datatoken_address
        logger.debug("Validating ASSET usage.")

        try:
            _tx, _order_log, _provider_fees_log = validate_order(
                self.web3,
                self.consumer_address,
                tx_id,
                self.asset,
                self.service,
                self.extra_data,
            )
            self.valid_until = _provider_fees_log.args.validUntil
            validate_transfer_not_used_for_other_service(
                self.did, self.service.id, tx_id, self.consumer_address, token_address
            )
            record_consume_request(
                self.did,
                self.service.id,
                tx_id,
                self.consumer_address,
                token_address,
                1,
            )
        except Exception as e:
            logger.exception(f"validate_usage failed with {str(e)}.")
            self.error = (
                f"Order for serviceId {self.service.id} is not valid. {str(e)}."
            )
            return False

        return True


def build_stage_output_dict(output_def, service_endpoint, owner, provider_wallet):
    config = get_config()
    if BaseURLs.SERVICES_URL in service_endpoint:
        service_endpoint = service_endpoint.split(BaseURLs.SERVICES_URL)[0]

    return dict(
        {
            "metadataUri": config.aquarius_url,
            "owner": output_def.get("owner", owner),
        }
    )
