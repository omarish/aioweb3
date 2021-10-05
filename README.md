# aioweb3

`asyncio` support for web3.py.

```python
web3 = AsyncWeb3()
contract = web3.eth.contract(address=addr, abi=IERC721_ENUMERABLE['abi'])
total_supply = await contract.functions.totalSupply().call()
```

**Caution: 🚧 This is not yet production ready 🚧.** 

## Install

```sh
pip install aioweb3
```

## Development

### Testing

There's the beginning of a test suite in the `tests` directory.

To run the tests:

```sh
$ pytest -s
```

It might help to set these environment variables:

```sh
export PYTHONASYNCIODEBUG=1
export PYTHONBREAKPOINT=ipdb.set_trace
```
