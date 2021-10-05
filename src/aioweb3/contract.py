"""Interaction with smart contracts over async Web3 connector. """
import copy
import itertools
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Collection,
    Dict,
    Generator,
    Iterable,
    List,
    NoReturn,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
    cast,
)
import warnings

from eth_abi.exceptions import (DecodingError,)
from eth_typing import (Address, BlockNumber, ChecksumAddress, HexStr,)
from eth_utils import (
    add_0x_prefix,
    combomethod,
    encode_hex,
    function_abi_to_4byte_selector,
    is_list_like,
    is_text,
    to_tuple,
)
from eth_utils.toolz import (compose, partial,)
from hexbytes import (HexBytes,)

from web3._utils.abi import (
    abi_to_signature,
    check_if_arguments_can_be_encoded,
    fallback_func_abi_exists,
    filter_by_type,
    get_abi_input_names,
    get_abi_input_types,
    get_abi_output_types,
    get_constructor_abi,
    is_array_type,
    map_abi_data,
    merge_args_and_kwargs,
    receive_func_abi_exists,
)
from web3._utils.blocks import (is_hex_encoded_block_hash,)
from web3._utils.contracts import (
    encode_abi,
    find_matching_event_abi,
    find_matching_fn_abi,
    get_function_info,
    prepare_transaction,
)
from web3._utils.datatypes import (PropertyCheckingFactory,)
from web3._utils.decorators import (deprecated_for,)
from web3._utils.empty import (empty,)
from web3._utils.encoding import (to_4byte_hex, to_hex,)
from web3._utils.events import (EventFilterBuilder, get_event_data, is_dynamic_sized_type,)
from web3._utils.filters import (LogFilter, construct_event_filter_params,)
from web3._utils.function_identifiers import (FallbackFn, ReceiveFn,)
from web3._utils.normalizers import (
    BASE_RETURN_NORMALIZERS,
    normalize_abi,
    normalize_address,
    normalize_bytecode,
)
from web3._utils.transactions import (fill_transaction_defaults,)
from web3.datastructures import (AttributeDict, MutableAttributeDict,)
from web3.exceptions import (
    ABIEventFunctionNotFound,
    ABIFunctionNotFound,
    BadFunctionCallOutput,
    BlockNumberOutofRange,
    FallbackNotFound,
    InvalidEventABI,
    LogTopicError,
    MismatchedABI,
    NoABIEventsFound,
    NoABIFound,
    NoABIFunctionsFound,
    ValidationError,
)
from web3.logs import (DISCARD, IGNORE, STRICT, WARN, EventLogErrorFlags,)
from web3.types import (  # noqa: F401
    ABI,
    ABIEvent,
    ABIFunction,
    BlockIdentifier,
    CallOverrideParams,
    EventData,
    FunctionIdentifier,
    LogReceipt,
    TxParams,
    TxReceipt,
)

from aioweb3.exceptions import SyncCallDetectedError

if TYPE_CHECKING:
    from .async_web3 import AsyncWeb3  # noqa: F401

from web3.contract import (
    ACCEPTABLE_EMPTY_STRINGS,
    ConciseContract,
    ConciseMethod,
    ContractFunctions,
    ContractEvents,
    ContractEvent,
    ContractFunction,
    ContractConstructor,
    Contract,
    mk_collision_prop
)


class AsyncContractFunctions(ContractFunctions):
    def __init__(
        self,
        abi: ABI,
        web3: 'AsyncWeb3',
        address: Optional[ChecksumAddress] = None
    ) -> None:
        self.abi = abi
        self.web3 = web3
        self.address = address

        if self.abi:
            self._functions = filter_by_type('function', self.abi)
            for func in self._functions:
                setattr(
                    self,
                    func['name'],
                    AsyncContractFunction.factory(
                        func['name'],
                        web3=self.web3,
                        contract_abi=self.abi,
                        address=self.address,
                        function_identifier=func['name']
                    )
                )


class AsyncContractEvents(ContractEvents):
    def __init__(
        self,
        abi: ABI,
        web3: 'AsyncWeb3',
        address: Optional[ChecksumAddress] = None
    ) -> None:
        if abi:
            self.abi = abi
            self._events = filter_by_type('event', self.abi)
            for event in self._events:
                setattr(
                    self,
                    event['name'],
                    AsyncContractEvent.factory(
                        event['name'],
                        web3=web3,
                        contract_abi=self.abi,
                        address=address,
                        event_name=event['name']
                    )
                )

    def __getattr__(self, event_name: str) -> Type['AsyncContractEvent']:
        # Re-implementing here to keep the redefined type definition
        return super().__getattribute__(event_name)

    def __getitem__(self, event_name: str) -> Type['AsyncContractEvent']:
        return getattr(self, event_name)

    def __iter__(self) -> Iterable[Type['AsyncContractEvent']]:
        """Iterate over supported

        :return: Iterable of :class:`ContractEvent`
        """
        for event in self._events:
            yield self[event['name']]


class AsyncContract(Contract):
    # set during class construction
    web3: 'AsyncWeb3' = None

    # instance level properties
    address: ChecksumAddress = None

    # class properties (overridable at instance level)
    abi: ABI = None

    asm = None
    ast = None

    bytecode = None
    bytecode_runtime = None
    clone_bin = None

    functions: AsyncContractFunctions = None
    caller: 'AsyncContractCaller' = None

    #: Instance of :class:`ContractEvents` presenting available Event ABIs
    events: AsyncContractEvents = None

    dev_doc = None
    interface = None
    metadata = None
    opcodes = None
    src_map = None
    src_map_runtime = None
    user_doc = None

    def __init__(self, address: Optional[ChecksumAddress] = None) -> None:
        """Create a new smart contract proxy object.

        :param address: Contract address as 0x hex string
        """
        if self.web3 is None:
            raise AttributeError(
                'The `Contract` class has not been initialized.  Please use the '
                '`web3.contract` interface to create your contract class.'
            )

        if address:
            self.address = normalize_address(self.web3.ens, address)

        if not self.address:
            raise TypeError("The address argument is required to instantiate a contract.")

        self.functions = AsyncContractFunctions(self.abi, self.web3, self.address)
        self.caller = AsyncContractCaller(self.abi, self.web3, self.address)
        self.events = AsyncContractEvents(self.abi, self.web3, self.address)
        self.fallback = AsyncContract.get_fallback_function(self.abi, self.web3, self.address)
        self.receive = AsyncContract.get_receive_function(self.abi, self.web3, self.address)

    @classmethod
    def factory(
        cls,
        web3: 'AsyncWeb3',
        class_name: Optional[str] = None,
        **kwargs: Any
    ) -> 'Contract':

        kwargs['web3'] = web3

        normalizers = {
            'abi': normalize_abi,
            'address': partial(normalize_address,
                               kwargs['web3'].ens),
            'bytecode': normalize_bytecode,
            'bytecode_runtime': normalize_bytecode,
        }

        contract = cast(
            AsyncContract,
            PropertyCheckingFactory(
                class_name or cls.__name__,
                (cls,
                 ),
                kwargs,
                normalizers=normalizers,
            )
        )
        contract.functions = AsyncContractFunctions(contract.abi, contract.web3)
        contract.caller = AsyncContractCaller(contract.abi, contract.web3, contract.address)
        contract.events = AsyncContractEvents(contract.abi, contract.web3)
        contract.fallback = AsyncContract.get_fallback_function(contract.abi, contract.web3)
        contract.receive = AsyncContract.get_receive_function(contract.abi, contract.web3)

        return contract

    #
    # Contract Methods
    #
    @classmethod
    def constructor(cls, *args: Any, **kwargs: Any) -> 'AsyncContractConstructor':
        """
        :param args: The contract constructor arguments as positional arguments
        :param kwargs: The contract constructor arguments as keyword arguments
        :return: a contract constructor object
        """
        if cls.bytecode is None:
            raise ValueError(
                "Cannot call constructor on a contract that does not have 'bytecode' associated "
                "with it"
            )

        return AsyncContractConstructor(cls.web3, cls.abi, cls.bytecode, *args, **kwargs)

    #  Public API
    #
    @combomethod
    def encodeABI(
        cls,
        fn_name: str,
        args: Optional[Any] = None,
        kwargs: Optional[Any] = None,
        data: Optional[HexStr] = None
    ) -> HexStr:
        """
        Encodes the arguments using the Ethereum ABI for the contract function
        that matches the given name and arguments..

        :param data: defaults to function selector
        """
        fn_abi, fn_selector, fn_arguments = get_function_info(
            fn_name, cls.web3.codec, contract_abi=cls.abi, args=args, kwargs=kwargs,
        )

        if data is None:
            data = fn_selector

        return encode_abi(cls.web3, fn_abi, fn_arguments, data)

    @combomethod
    def all_functions(self) -> List['ContractFunction']:
        return find_functions_by_identifier(self.abi, self.web3, self.address, lambda _: True)

    @combomethod
    def get_function_by_signature(self, signature: str) -> 'AsyncContractFunction':
        if ' ' in signature:
            raise ValueError(
                'Function signature should not contain any spaces. '
                'Found spaces in input: %s' % signature
            )

        def callable_check(fn_abi: ABIFunction) -> bool:
            return abi_to_signature(fn_abi) == signature

        fns = find_functions_by_identifier(self.abi, self.web3, self.address, callable_check)
        return get_function_by_identifier(fns, 'signature')

    @combomethod
    def find_functions_by_name(self, fn_name: str) -> List['AsyncContractFunction']:
        def callable_check(fn_abi: ABIFunction) -> bool:
            return fn_abi['name'] == fn_name

        return find_functions_by_identifier(self.abi, self.web3, self.address, callable_check)

    @combomethod
    def get_function_by_name(self, fn_name: str) -> 'AsyncContractFunction':
        fns = self.find_functions_by_name(fn_name)
        return get_function_by_identifier(fns, 'name')

    @combomethod
    def get_function_by_selector(
        self,
        selector: Union[bytes,
                        int,
                        HexStr]
    ) -> 'AsyncContractFunction':
        def callable_check(fn_abi: ABIFunction) -> bool:
            # typed dict cannot be used w/ a normal Dict
            # https://github.com/python/mypy/issues/4976
            return encode_hex(function_abi_to_4byte_selector(fn_abi)
                              ) == to_4byte_hex(selector)  # type: ignore # noqa: E501

        fns = find_functions_by_identifier(self.abi, self.web3, self.address, callable_check)
        return get_function_by_identifier(fns, 'selector')

    @combomethod
    def decode_function_input(self, data: HexStr) -> Tuple['AsyncContractFunction', Dict[str, Any]]:
        # type ignored b/c expects data arg to be HexBytes
        data = HexBytes(data)  # type: ignore
        selector, params = data[:4], data[4:]
        func = self.get_function_by_selector(selector)

        names = get_abi_input_names(func.abi)
        types = get_abi_input_types(func.abi)
        # TODO: double-cehck async
        decoded = self.web3.codec.decode_abi(types, cast(HexBytes, params))
        normalized = map_abi_data(BASE_RETURN_NORMALIZERS, types, decoded)

        return func, dict(zip(names, normalized))

    @combomethod
    def find_functions_by_args(self, *args: Any) -> List['AsyncContractFunction']:
        def callable_check(fn_abi: ABIFunction) -> bool:
            return check_if_arguments_can_be_encoded(fn_abi, self.web3.codec, args=args, kwargs={})

        return find_functions_by_identifier(self.abi, self.web3, self.address, callable_check)

    @combomethod
    def get_function_by_args(self, *args: Any) -> 'AsyncContractFunction':
        fns = self.find_functions_by_args(*args)
        return get_function_by_identifier(fns, 'args')

    @staticmethod
    def get_fallback_function(
        abi: ABI,
        web3: 'AsyncWeb3',
        address: Optional[ChecksumAddress] = None
    ) -> 'AsyncContractFunction':
        if abi and fallback_func_abi_exists(abi):
            # TODO: make sure this doesn't block
            return AsyncContractFunction.factory(
                'fallback',
                web3=web3,
                contract_abi=abi,
                address=address,
                function_identifier=FallbackFn
            )()

        return cast('AsyncContractFunction', NonExistentFallbackFunction())

    @staticmethod
    def get_receive_function(
        abi: ABI,
        web3: 'AsyncWeb3',
        address: Optional[ChecksumAddress] = None
    ) -> 'ContractFunction':
        if abi and receive_func_abi_exists(abi):
            return AsyncContractFunction.factory(
                'receive',
                web3=web3,
                contract_abi=abi,
                address=address,
                function_identifier=ReceiveFn
            )()

        return cast('AsyncContractFunction', NonExistentReceiveFunction())


class AsyncContractConstructor(ContractConstructor):
    """
    Class for contract constructor API.
    """
    def __init__(
        self,
        web3: 'AsyncWeb3',
        abi: ABI,
        bytecode: HexStr,
        *args: Any,
        **kwargs: Any
    ) -> None:
        self.web3 = web3
        self.abi = abi
        self.bytecode = bytecode
        self.data_in_transaction = self._encode_data_in_transaction(*args, **kwargs)

    @combomethod
    async def estimateGas(
        self,
        transaction: Optional[TxParams] = None,
        block_identifier: Optional[BlockIdentifier] = None
    ) -> int:
        if transaction is None:
            estimate_gas_transaction: TxParams = {}
        else:
            estimate_gas_transaction = cast(TxParams, dict(**transaction))
            self.check_forbidden_keys_in_transaction(estimate_gas_transaction, ["data", "to"])

        if self.web3.eth.default_account is not empty:
            # type ignored b/c check prevents an empty default_account
            estimate_gas_transaction.setdefault(
                'from',
                self.web3.eth.default_account
            )  # type: ignore # noqa: E501

        estimate_gas_transaction['data'] = self.data_in_transaction
        return await self.web3.eth.estimate_gas(
            estimate_gas_transaction,
            block_identifier=block_identifier
        )

    @combomethod
    async def transact(self, transaction: Optional[TxParams] = None) -> HexBytes:
        if transaction is None:
            transact_transaction: TxParams = {}
        else:
            transact_transaction = cast(TxParams, dict(**transaction))
            self.check_forbidden_keys_in_transaction(transact_transaction, ["data", "to"])

        if self.web3.eth.default_account is not empty:
            # type ignored b/c check prevents an empty default_account
            transact_transaction.setdefault('from', self.web3.eth.default_account)  # type: ignore

        transact_transaction['data'] = self.data_in_transaction

        return await self.web3.eth.send_transaction(transact_transaction)


class AsyncConciseMethod(ConciseMethod):
    ALLOWED_MODIFIERS = {'call', 'estimateGas', 'transact', 'buildTransaction'}

    def __init__(
        self,
        function: 'AsyncContractFunction',
        normalizers: Optional[Tuple[Callable[...,
                                             Any],
                                    ...]] = None
    ) -> None:
        self._function = function
        self._function._return_data_normalizers = normalizers

    def __call__(self, *args: Any, **kwargs: Any) -> 'AsyncContractFunction':
        # TODO: async: Make sure this isn't going to block, otherwise await it
        return self.__prepared_function(*args, **kwargs)

    def __prepared_function(self, *args: Any, **kwargs: Any) -> 'AsyncContractFunction':
        # TODO: async check
        modifier_dict: Dict[Any, Any]
        if not kwargs:
            modifier, modifier_dict = 'call', {}
        elif len(kwargs) == 1:
            modifier, modifier_dict = kwargs.popitem()
            if modifier not in self.ALLOWED_MODIFIERS:
                raise TypeError(
                    "The only allowed keyword arguments are: %s" % self.ALLOWED_MODIFIERS
                )
        else:
            raise TypeError("Use up to one keyword argument, one of: %s" % self.ALLOWED_MODIFIERS)

        return getattr(self._function(*args), modifier)(modifier_dict)


class AsyncConciseContract(ConciseContract):
    @classmethod
    def factory(cls, *args: Any, **kwargs: Any) -> AsyncContract:
        return compose(cls, AsyncContract.factory(*args, **kwargs))


from web3.contract import CONCISE_NORMALIZERS, ImplicitMethod, NonExistentFallbackFunction, NonExistentReceiveFunction


class AsyncImplicitMethod(ImplicitMethod):
    def __call_by_default(self, args: Any) -> bool:
        function_abi = find_matching_fn_abi(
            self._function.contract_abi,
            self._function.web3.codec,
            fn_identifier=self._function.function_identifier,
            args=args
        )

        return function_abi['constant'] if 'constant' in function_abi.keys() else False

    @deprecated_for("classic contract syntax. Ex: contract.functions.withdraw(amount).transact({})")
    def __call__(self, *args: Any, **kwargs: Any) -> 'ContractFunction':
        raise SyncCallDetectedError("does this need to be supported?")
        # Modifier is not provided and method is not constant/pure do a transaction instead
        if not kwargs and not self.__call_by_default(args):
            return super().__call__(*args, transact={})
        else:
            return super().__call__(*args, **kwargs)


class AsyncImplicitContract(AsyncConciseContract):
    def __init__(
        self,
        classic_contract: AsyncContract,
        method_class: Union[Type[AsyncImplicitMethod],
                            Type[AsyncConciseMethod]] = AsyncImplicitMethod
    ) -> None:
        super().__init__(classic_contract, method_class=method_class)


class AsyncContractFunction(ContractFunction):
    """Base class for contract functions

    A function accessed via the api contract.functions.myMethod(*args, **kwargs)
    is a subclass of this class.
    """
    address: ChecksumAddress = None
    function_identifier: FunctionIdentifier = None
    web3: 'AsyncWeb3' = None
    contract_abi: ABI = None
    abi: ABIFunction = None
    transaction: TxParams = None
    arguments: Tuple[Any, ...] = None
    args: Any = None
    kwargs: Any = None

    def __call__(self, *args: Any, **kwargs: Any) -> 'AsyncContractFunction':
        clone = copy.copy(self)
        if args is None:
            clone.args = tuple()
        else:
            clone.args = args

        if kwargs is None:
            clone.kwargs = {}
        else:
            clone.kwargs = kwargs
        clone._set_function_info()
        return clone

    async def call(
        self,
        transaction: Optional[TxParams] = None,
        block_identifier: BlockIdentifier = 'latest',
        state_override: Optional[CallOverrideParams] = None,
    ) -> Any:
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
            call_transaction.setdefault('from', self.web3.eth.default_account)  # type: ignore

        if 'to' not in call_transaction:
            if isinstance(self, type):
                raise ValueError(
                    "When using `Contract.[methodtype].[method].call()` from"
                    " a contract factory you "
                    "must provide a `to` address with the transaction"
                )
            else:
                raise ValueError("Please ensure that this contract instance has an address.")

        block_id = await async_parse_block_identifier(self.web3, block_identifier)

        return await async_call_contract_function(
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

    async def transact(self, transaction: Optional[TxParams] = None) -> HexBytes:
        if transaction is None:
            transact_transaction: TxParams = {}
        else:
            transact_transaction = cast(TxParams, dict(**transaction))

        if 'data' in transact_transaction:
            raise ValueError("Cannot set 'data' field in transact transaction")

        if self.address is not None:
            transact_transaction.setdefault('to', self.address)
        if self.web3.eth.default_account is not empty:
            # type ignored b/c check prevents an empty default_account
            transact_transaction.setdefault('from', self.web3.eth.default_account)  # type: ignore

        if 'to' not in transact_transaction:
            if isinstance(self, type):
                raise ValueError(
                    "When using `Contract.transact` from a contract factory you "
                    "must provide a `to` address with the transaction"
                )
            else:
                raise ValueError("Please ensure that this contract instance has an address.")

        return await async_transact_with_contract_function(
            self.address,
            self.web3,
            self.function_identifier,
            transact_transaction,
            self.contract_abi,
            self.abi,
            *self.args,
            **self.kwargs
        )

    async def estimateGas(
        self,
        transaction: Optional[TxParams] = None,
        block_identifier: Optional[BlockIdentifier] = None
    ) -> int:
        if transaction is None:
            estimate_gas_transaction: TxParams = {}
        else:
            estimate_gas_transaction = cast(TxParams, dict(**transaction))

        if 'data' in estimate_gas_transaction:
            raise ValueError("Cannot set 'data' field in estimateGas transaction")
        if 'to' in estimate_gas_transaction:
            raise ValueError("Cannot set to in estimateGas transaction")

        if self.address:
            estimate_gas_transaction.setdefault('to', self.address)
        if self.web3.eth.default_account is not empty:
            # type ignored b/c check prevents an empty default_account
            estimate_gas_transaction.setdefault(
                'from',
                self.web3.eth.default_account
            )  # type: ignore # noqa: E501

        if 'to' not in estimate_gas_transaction:
            if isinstance(self, type):
                raise ValueError(
                    "When using `Contract.estimateGas` from a contract factory "
                    "you must provide a `to` address with the transaction"
                )
            else:
                raise ValueError("Please ensure that this contract instance has an address.")

        return await async_estimate_gas_for_function(
            self.address,
            self.web3,
            self.function_identifier,
            estimate_gas_transaction,
            self.contract_abi,
            self.abi,
            block_identifier,
            *self.args,
            **self.kwargs
        )

    # buildTransaction: superclass

    @classmethod
    def factory(cls, class_name: str, **kwargs: Any) -> 'AsyncContractFunction':
        return PropertyCheckingFactory(class_name, (cls,), kwargs)(kwargs.get('abi'))

    def __repr__(self) -> str:
        if self.abi:
            _repr = '<AsyncFunction %s' % abi_to_signature(self.abi)
            if self.arguments is not None:
                _repr += ' bound to %r' % (self.arguments,)
            return _repr + '>'
        return '<AsyncFunction %s>' % self.fn_name


class AsyncContractEvent(ContractEvent):
    """Base class for contract events

    An event accessed via the api contract.events.myEvents(*args, **kwargs)
    is a subclass of this class.
    """
    address: ChecksumAddress = None
    event_name: str = None
    web3: 'AsyncWeb3' = None
    contract_abi: ABI = None
    abi: ABIEvent = None

    def __init__(self, *argument_names: Tuple[str]) -> None:

        if argument_names is None:
            # https://github.com/python/mypy/issues/6283
            self.argument_names = tuple()  # type: ignore
        else:
            self.argument_names = argument_names

        self.abi = self._get_event_abi()

    @combomethod
    def processReceipt(self,
                       txn_receipt: TxReceipt,
                       errors: EventLogErrorFlags = WARN) -> Iterable[EventData]:
        return self._parse_logs(txn_receipt, errors)

    @to_tuple
    def _parse_logs(self,
                    txn_receipt: TxReceipt,
                    errors: EventLogErrorFlags) -> Iterable[EventData]:
        try:
            errors.name
        except AttributeError:
            raise AttributeError(f'Error flag must be one of: {EventLogErrorFlags.flag_options()}')

        for log in txn_receipt['logs']:
            try:
                rich_log = get_event_data(self.web3.codec, self.abi, log)
            except (MismatchedABI, LogTopicError, InvalidEventABI, TypeError) as e:
                if errors == DISCARD:
                    continue
                elif errors == IGNORE:
                    # type ignores b/c rich_log set on 1092 conflicts with mutated types
                    new_log = MutableAttributeDict(log)  # type: ignore
                    new_log['errors'] = e
                    rich_log = AttributeDict(new_log)  # type: ignore
                elif errors == STRICT:
                    raise e
                else:
                    warnings.warn(
                        f"The log with transaction hash: {log['transactionHash']!r} and "
                        f"logIndex: {log['logIndex']} encountered the following error "
                        f"during processing: {type(e).__name__}({e}). It has been discarded."
                    )
                    continue
            yield rich_log

    @combomethod
    def createFilter(
            self, *,  # PEP 3102
            argument_filters: Optional[Dict[str, Any]] = None,
            fromBlock: Optional[BlockIdentifier] = None,
            toBlock: BlockIdentifier = "latest",
            address: Optional[ChecksumAddress] = None,
            topics: Optional[Sequence[Any]] = None) -> LogFilter:
        """
        Create filter object that tracks logs emitted by this contract event.
        :param filter_params: other parameters to limit the events
        """
        # TODO: make async
        if fromBlock is None:
            raise TypeError("Missing mandatory keyword argument to createFilter: fromBlock")

        if argument_filters is None:
            argument_filters = dict()

        _filters = dict(**argument_filters)

        event_abi = self._get_event_abi()

        check_for_forbidden_api_filter_arguments(event_abi, _filters)

        _, event_filter_params = construct_event_filter_params(
            self._get_event_abi(),
            self.web3.codec,
            contract_address=self.address,
            argument_filters=_filters,
            fromBlock=fromBlock,
            toBlock=toBlock,
            address=address,
            topics=topics,
        )

        filter_builder = EventFilterBuilder(event_abi, self.web3.codec)
        filter_builder.address = cast(ChecksumAddress, event_filter_params.get('address'))
        filter_builder.fromBlock = event_filter_params.get('fromBlock')
        filter_builder.toBlock = event_filter_params.get('toBlock')
        match_any_vals = {
            arg: value
            for arg,
            value in _filters.items()
            if not is_array_type(filter_builder.args[arg].arg_type) and is_list_like(value)
        }
        for arg, value in match_any_vals.items():
            filter_builder.args[arg].match_any(*value)

        match_single_vals = {
            arg: value
            for arg,
            value in _filters.items()
            if not is_array_type(filter_builder.args[arg].arg_type) and not is_list_like(value)
        }
        for arg, value in match_single_vals.items():
            filter_builder.args[arg].match_single(value)

        log_filter = filter_builder.deploy(self.web3)
        log_filter.log_entry_formatter = get_event_data(self.web3.codec, self._get_event_abi())
        log_filter.builder = filter_builder

        return log_filter

    @combomethod
    async def getLogs(
        self,
        argument_filters: Optional[Dict[str,
                                        Any]] = None,
        fromBlock: Optional[BlockIdentifier] = None,
        toBlock: Optional[BlockIdentifier] = None,
        blockHash: Optional[HexBytes] = None
    ) -> Iterable[EventData]:
        """Get events for this contract instance using eth_getLogs API.

        This is a stateless method, as opposed to createFilter.
        It can be safely called against nodes which do not provide
        eth_newFilter API, like Infura nodes.

        If there are many events,
        like ``Transfer`` events for a popular token,
        the Ethereum node might be overloaded and timeout
        on the underlying JSON-RPC call.

        Example - how to get all ERC-20 token transactions
        for the latest 10 blocks:

        .. code-block:: python

            from = max(mycontract.web3.eth.block_number - 10, 1)
            to = mycontract.web3.eth.block_number

            events = mycontract.events.Transfer.getLogs(fromBlock=from, toBlock=to)

            for e in events:
                print(e["args"]["from"],
                    e["args"]["to"],
                    e["args"]["value"])

        The returned processed log values will look like:

        .. code-block:: python

            (
                AttributeDict({
                 'args': AttributeDict({}),
                 'event': 'LogNoArguments',
                 'logIndex': 0,
                 'transactionIndex': 0,
                 'transactionHash': HexBytes('...'),
                 'address': '0xF2E246BB76DF876Cef8b38ae84130F4F55De395b',
                 'blockHash': HexBytes('...'),
                 'blockNumber': 3
                }),
                AttributeDict(...),
                ...
            )

        See also: :func:`web3.middleware.filter.local_filter_middleware`.

        :param argument_filters:
        :param fromBlock: block number or "latest", defaults to "latest"
        :param toBlock: block number or "latest". Defaults to "latest"
        :param blockHash: block hash. blockHash cannot be set at the
          same time as fromBlock or toBlock
        :yield: Tuple of :class:`AttributeDict` instances
        """

        if not self.address:
            raise TypeError(
                "This method can be only called on "
                "an instated contract with an address"
            )

        abi = self._get_event_abi()

        if argument_filters is None:
            argument_filters = dict()

        _filters = dict(**argument_filters)

        blkhash_set = blockHash is not None
        blknum_set = fromBlock is not None or toBlock is not None
        if blkhash_set and blknum_set:
            raise ValidationError(
                'blockHash cannot be set at the same'
                ' time as fromBlock or toBlock'
            )

        # Construct JSON-RPC raw filter presentation based on human readable Python descriptions
        # Namely, convert event names to their keccak signatures
        data_filter_set, event_filter_params = construct_event_filter_params(
            abi,
            self.web3.codec,
            contract_address=self.address,
            argument_filters=_filters,
            fromBlock=fromBlock,
            toBlock=toBlock,
            address=self.address,
        )

        if blockHash is not None:
            event_filter_params['blockHash'] = blockHash

        # Call JSON-RPC API
        logs = await self.web3.eth.get_logs(event_filter_params)

        # Convert raw binary data to Python proxy objects as described by ABI
        return tuple(get_event_data(self.web3.codec, abi, entry) for entry in logs)

    @classmethod
    def factory(cls, class_name: str, **kwargs: Any) -> PropertyCheckingFactory:
        return PropertyCheckingFactory(class_name, (cls,), kwargs)


from web3.contract import ContractCaller
import asyncio


class AsyncContractCaller(ContractCaller):
    def __init__(
        self,
        abi: ABI,
        web3: 'AsyncWeb3',
        address: ChecksumAddress,
        transaction: Optional[TxParams] = None,
        block_identifier: BlockIdentifier = 'latest'
    ) -> None:
        self.web3 = web3
        self.address = address
        self.abi = abi
        self._functions = None

        if self.abi:
            if transaction is None:
                transaction = {}

            self._functions = filter_by_type('function', self.abi)
            for func in self._functions:
                fn: AsyncContractFunction = AsyncContractFunction.factory(
                    func['name'],
                    web3=self.web3,
                    contract_abi=self.abi,
                    address=self.address,
                    function_identifier=func['name']
                )

                loop = asyncio.get_event_loop()

                # TODO: might need to move this out of the constructor
                block_id = loop.run_until_complete(
                    async_parse_block_identifier(self.web3,
                                                 block_identifier)
                )

                caller_method = partial(
                    self.call_function,
                    fn,
                    transaction=transaction,
                    block_identifier=block_id
                )

                setattr(self, func['name'], caller_method)

    async def __call__(
        self,
        transaction: Optional[TxParams] = None,
        block_identifier: BlockIdentifier = 'latest'
    ) -> 'AsyncContractCaller':
        if transaction is None:
            transaction = {}
        # TODO: make sure self = async version of class
        return type(self)(
            self.abi,
            self.web3,
            self.address,
            transaction=transaction,
            block_identifier=block_identifier
        )

    @staticmethod
    async def call_function(
        fn: AsyncContractFunction,
        *args: Any,
        transaction: Optional[TxParams] = None,
        block_identifier: BlockIdentifier = 'latest',
        **kwargs: Any
    ) -> Any:
        if transaction is None:
            transaction = {}
        return await fn(*args, **kwargs).call(transaction, block_identifier)


from web3.contract import check_for_forbidden_api_filter_arguments


async def async_call_contract_function(
    web3: 'AsyncWeb3',
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

    return_data = await web3.eth.call(
        call_transaction,
        block_identifier=block_id,
        state_override=state_override,
    )

    if fn_abi is None:
        fn_abi = find_matching_fn_abi(contract_abi, web3.codec, function_identifier, args, kwargs)

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


async def async_parse_block_identifier(
    web3: 'AsyncWeb3',
    block_identifier: BlockIdentifier
) -> BlockIdentifier:
    if isinstance(block_identifier, int):
        return await async_parse_block_identifier_int(web3, block_identifier)
    elif block_identifier in ['latest', 'earliest', 'pending']:
        return block_identifier
    elif isinstance(block_identifier, bytes) or is_hex_encoded_block_hash(block_identifier):
        return web3.eth.get_block(block_identifier)['number']
    else:
        raise BlockNumberOutofRange


async def async_parse_block_identifier_int(
    web3: 'AsyncWeb3',
    block_identifier_int: int
) -> BlockNumber:
    if block_identifier_int >= 0:
        block_num = block_identifier_int
    else:
        last_block = (await web3.eth.get_block('latest'))['number']
        block_num = last_block + block_identifier_int + 1
        if block_num < 0:
            raise BlockNumberOutofRange
    return BlockNumber(block_num)


async def async_transact_with_contract_function(
    address: ChecksumAddress,
    web3: 'AsyncWeb3',
    function_name: Optional[FunctionIdentifier] = None,
    transaction: Optional[TxParams] = None,
    contract_abi: Optional[ABI] = None,
    fn_abi: Optional[ABIFunction] = None,
    *args: Any,
    **kwargs: Any
) -> HexBytes:
    """
    Helper function for interacting with a contract function by sending a
    transaction.
    """
    transact_transaction = prepare_transaction(
        address,
        web3,
        fn_identifier=function_name,
        contract_abi=contract_abi,
        transaction=transaction,
        fn_abi=fn_abi,
        fn_args=args,
        fn_kwargs=kwargs,
    )

    txn_hash = await web3.eth.send_transaction(transact_transaction)
    return txn_hash


async def async_estimate_gas_for_function(
    address: ChecksumAddress,
    web3: 'AsyncWeb3',
    fn_identifier: Optional[FunctionIdentifier] = None,
    transaction: Optional[TxParams] = None,
    contract_abi: Optional[ABI] = None,
    fn_abi: Optional[ABIFunction] = None,
    block_identifier: Optional[BlockIdentifier] = None,
    *args: Any,
    **kwargs: Any
) -> int:
    """Estimates gas cost a function call would take.

    Don't call this directly, instead use :meth:`Contract.estimateGas`
    on your contract instance.
    """
    estimate_transaction = prepare_transaction(
        address,
        web3,
        fn_identifier=fn_identifier,
        contract_abi=contract_abi,
        fn_abi=fn_abi,
        transaction=transaction,
        fn_args=args,
        fn_kwargs=kwargs,
    )

    return await web3.eth.estimate_gas(estimate_transaction, block_identifier)


def find_functions_by_identifier(
    contract_abi: ABI,
    web3: 'AsyncWeb3',
    address: ChecksumAddress,
    callable_check: Callable[...,
                             Any]
) -> List[AsyncContractFunction]:
    fns_abi = filter_by_type('function', contract_abi)
    return [
        AsyncContractFunction.factory(
            fn_abi['name'],
            web3=web3,
            contract_abi=contract_abi,
            address=address,
            function_identifier=fn_abi['name'],
            abi=fn_abi
        ) for fn_abi in fns_abi if callable_check(fn_abi)
    ]


def get_function_by_identifier(
    fns: Sequence[AsyncContractFunction],
    identifier: str
) -> AsyncContractFunction:
    if len(fns) > 1:
        raise ValueError(
            'Found multiple functions with matching {0}. '
            'Found: {1!r}'.format(identifier,
                                  fns)
        )
    elif len(fns) == 0:
        raise ValueError('Could not find any function with matching {0}'.format(identifier))
    return fns[0]
