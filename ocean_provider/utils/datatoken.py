import logging
from datetime import datetime

from jsonsempai import magic  # noqa: F401
from artifacts import DataTokenTemplate
from eth_utils import remove_0x_prefix
from hexbytes import HexBytes
from ocean_provider.utils.basics import get_web3
from ocean_provider.utils.currency import to_wei
from ocean_provider.utils.services import Service
from web3.logs import DISCARD
from websockets import ConnectionClosed

OPF_FEE_PER_TOKEN = to_wei("0.001")  # 0.1%
MAX_MARKET_FEE_PER_TOKEN = to_wei("0.001")

logger = logging.getLogger(__name__)


def get_dt_contract(web3, address):
    abi = DataTokenTemplate.abi

    return web3.eth.contract(address=address, abi=abi)


def get_tx_receipt(web3, tx_hash):
    return web3.eth.wait_for_transaction_receipt(HexBytes(tx_hash), timeout=120)


def get_datatoken_minter(datatoken_address):
    """
    :return: Eth account address of the Datatoken minter
    """
    dt = get_dt_contract(get_web3(), datatoken_address)
    publisher = dt.caller.minter()
    return publisher


def mint(web3, contract, receiver_address, amount, minter_wallet):
    contract_fn = contract.functions.mint(receiver_address, amount)
    _transact = {
        "from": minter_wallet.address,
        "account_key": str(minter_wallet.key),
        "chainId": web3.eth.chain_id,
        "gasPrice": int(web3.eth.gas_price * 1.1),
    }

    return contract_fn.transact(_transact).hex()


def verify_order_tx(
    web3, contract, tx_id: str, did: str, service: Service, amount, sender: str
):
    try:
        tx_receipt = get_tx_receipt(web3, tx_id)
    except ConnectionClosed:
        # try again in this case
        tx_receipt = get_tx_receipt(web3, tx_id)

    if tx_receipt is None:
        raise AssertionError(
            "Failed to get tx receipt for the `startOrder` transaction.."
        )

    if tx_receipt.status == 0:
        raise AssertionError("order transaction failed.")

    receiver = contract.caller.minter()
    event_logs = contract.events.OrderStarted().processReceipt(
        tx_receipt, errors=DISCARD
    )
    order_log = event_logs[0] if event_logs else None
    if not order_log:
        raise AssertionError(
            f"Cannot find the event for the order transaction with tx id {tx_id}."
        )
    assert (
        len(event_logs) == 1
    ), f"Multiple order events in the same transaction !!! {event_logs}"

    asset_id = remove_0x_prefix(did).lower()
    assert (
        asset_id == remove_0x_prefix(contract.address).lower()
    ), "asset-id does not match the datatoken id."
    if str(order_log.args.serviceId) != str(service.index):
        raise AssertionError(
            f"The asset id (DID) or service id in the event does "
            f"not match the requested asset. \n"
            f"requested: (did={did}, serviceId={service.index}\n"
            f"event: (serviceId={order_log.args.serviceId}"
        )

    # Check if order expired. timeout == 0 means order is valid forever
    service_timeout = service.main["timeout"]
    timestamp_now = datetime.utcnow().timestamp()
    timestamp_delta = timestamp_now - order_log.args.timestamp
    logger.debug(
        f"verify_order_tx: service timeout = {service_timeout}, timestamp delta = {timestamp_delta}"
    )
    if service_timeout != 0 and timestamp_delta > service_timeout:
        raise ValueError(
            f"The order has expired. \n"
            f"current timestamp={timestamp_now}\n"
            f"order timestamp={order_log.args.timestamp}\n"
            f"timestamp delta={timestamp_delta}\n"
            f"service timeout={service_timeout}"
        )

    target_amount = amount - contract.caller.calculateFee(amount, OPF_FEE_PER_TOKEN)
    if order_log.args.mrktFeeCollector and order_log.args.marketFee > 0:
        max_market_fee = contract.caller.calculateFee(amount, MAX_MARKET_FEE_PER_TOKEN)
        assert order_log.args.marketFee <= (max_market_fee + 5), (
            f"marketFee {order_log.args.marketFee} exceeds the expected maximum "
            f"of {max_market_fee} based on feePercentage="
            f"{MAX_MARKET_FEE_PER_TOKEN} ."
        )
        target_amount = target_amount - order_log.args.marketFee

    # verify sender of the tx using the Tx record
    tx = web3.eth.get_transaction(tx_id)
    if sender not in [order_log.args.consumer, order_log.args.payer]:
        raise AssertionError("sender of order transaction is not the consumer/payer.")
    transfer_logs = contract.events.Transfer().processReceipt(
        tx_receipt, errors=DISCARD
    )
    receiver_to_transfers = {}
    for tr in transfer_logs:
        if tr.args.to not in receiver_to_transfers:
            receiver_to_transfers[tr.args.to] = []
        receiver_to_transfers[tr.args.to].append(tr)
    if receiver not in receiver_to_transfers:
        raise AssertionError(
            f"receiver {receiver} is not found in the transfer events."
        )
    transfers = sorted(receiver_to_transfers[receiver], key=lambda x: x.args.value)
    total = sum(tr.args.value for tr in transfers)
    if total < (target_amount - 5):
        raise ValueError(
            f"transferred value does meet the service cost: "
            f"service.cost - fees={target_amount}, "
            f"transferred value={total}"
        )
    return tx, order_log, transfers[-1]
