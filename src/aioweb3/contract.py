import itertools
from typing import TYPE_CHECKING, Any, Callable, Optional, Tuple, cast

from eth_abi.exceptions import DecodingError
from eth_typing import BlockNumber, ChecksumAddress
from web3 import Web3
from web3._utils.abi import (get_abi_input_names, get_abi_input_types,
                             get_abi_output_types, get_constructor_abi,
                             map_abi_data)
from web3._utils.blocks import is_hex_encoded_block_hash
from web3._utils.contracts import (find_matching_event_abi,
                                   find_matching_fn_abi, prepare_transaction)
from web3._utils.empty import empty
from web3._utils.normalizers import (BASE_RETURN_NORMALIZERS, normalize_abi,
                                     normalize_address, normalize_bytecode)
from web3.contract import ACCEPTABLE_EMPTY_STRINGS, ContractFunction
from web3.exceptions import BadFunctionCallOutput, BlockNumberOutofRange
from web3.types import (ABI, ABIEvent, ABIFunction, BlockIdentifier,
                        CallOverrideParams, EventData, FunctionIdentifier,
                        LogReceipt, TxParams, TxReceipt)

from .async_web3 import AsyncWeb3
from .exceptions import SyncCallDetectedError


async def async_parse_block_identifier(
    web3: 'AsyncWeb3',
    block_identifier: BlockIdentifier
) -> BlockIdentifier:
    if not isinstance(web3, (AsyncWeb3,)):
        raise
    if isinstance(block_identifier, int):
        return await async_parse_block_identifier_int(web3, block_identifier)
    elif block_identifier in ['latest', 'earliest', 'pending']:
        return block_identifier
    elif isinstance(block_identifier,
                    bytes) or is_hex_encoded_block_hash(block_identifier):
        return web3.eth.get_block(block_identifier)['number']
    else:
        raise BlockNumberOutofRange


async def async_parse_block_identifier_int(
    web3: 'Web3',
    block_identifier_int: int
) -> BlockNumber:
    # TODO(async): Make this async
    if block_identifier_int >= 0:
        block_num = block_identifier_int
    else:
        last_block = web3.eth.get_block('latest')['number']
        block_num = last_block + block_identifier_int + 1
        if block_num < 0:
            raise BlockNumberOutofRange
    return BlockNumber(block_num)


async def async_call_contract_function(
    web3: 'Web3',
    address: ChecksumAddress,
    normalizers: Tuple[Callable[...,
                                Any],
                       ...],
    function_identifier: FunctionIdentifier,
    transaction: TxParams,
    block_id: Optional[BlockIdentifier] = None,
    contract_abi: Optional[ABI] = None,
    fn_abi: Optional[ABIFunction] = None,
    state_override: Optional[CallOverrideParams] = None,
    *args: Any,
    **kwargs: Any
) -> Any:
    """
    Helper function for interacting with a contract function using the
    `eth_call` API.
    """
    call_transaction = prepare_transaction(
        address,
        web3,
        fn_identifier=function_identifier,
        contract_abi=contract_abi,
        fn_abi=fn_abi,
        transaction=transaction,
        fn_args=args,
        fn_kwargs=kwargs,
    )

    return_data = web3.eth.call(
        call_transaction,
        block_identifier=block_id,
        state_override=state_override,
    )

    if fn_abi is None:
        fn_abi = find_matching_fn_abi(
            contract_abi,
            web3.codec,
            function_identifier,
            args,
            kwargs
        )

    output_types = get_abi_output_types(fn_abi)

    try:
        output_data = web3.codec.decode_abi(output_types, return_data)
    except DecodingError as e:
        # Provide a more helpful error message than the one provided by
        # eth-abi-utils
        is_missing_code_error = (
            return_data in ACCEPTABLE_EMPTY_STRINGS and
            web3.eth.get_code(address) in ACCEPTABLE_EMPTY_STRINGS
        )
        if is_missing_code_error:
            msg = (
                "Could not transact with/call contract function, is contract "
                "deployed correctly and chain synced?"
            )
        else:
            msg = (
                f"Could not decode contract function call to {function_identifier} with "
                f"return data: {str(return_data)}, output_types: {output_types}"
            )
        raise BadFunctionCallOutput(msg) from e

    _normalizers = itertools.chain(BASE_RETURN_NORMALIZERS, normalizers,)
    normalized_data = map_abi_data(_normalizers, output_types, output_data)

    if len(normalized_data) == 1:
        return normalized_data[0]
    else:
        return normalized_data


class AsyncContractFunction(ContractFunction):
    async def call(
        self,
        transaction: Optional[TxParams] = None,
        block_identifier: BlockIdentifier = 'latest',
        state_override: Optional[CallOverrideParams] = None,
    ):
        if transaction is None:
            call_transaction: TxParams = {}
        else:
            call_transaction = cast(TxParams, dict(**transaction))

        if 'data' in call_transaction:
            raise ValueError("Cannot set 'data' field in call transaction")

        if self.address:
            call_transaction.setdefault('to', self.address)
        if self.web3.eth.default_account is not empty:
            # type ignored b/c check prevents an empty default_account
            call_transaction.setdefault(
                'from',
                self.web3.eth.default_account
            )  # type: ignore

        if 'to' not in call_transaction:
            if isinstance(self, type):
                raise ValueError(
                    "When using `Contract.[methodtype].[method].call()` from"
                    " a contract factory you "
                    "must provide a `to` address with the transaction"
                )
            else:
                raise ValueError(
                    "Please ensure that this contract instance has an address."
                )

        block_id = await async_parse_block_identifier(
            self.web3,
            block_identifier
        )

        return async_call_contract_function(
            self.web3,
            self.address,
            self._return_data_normalizers,
            self.function_identifier,
            call_transaction,
            block_id,
            self.contract_abi,
            self.abi,
            state_override,
            *self.args,
            **self.kwargs
        )