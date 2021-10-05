# aioweb3

`asyncio` support for web3.py.

**Caution: 🚧 This is not yet production ready 🚧.** I use it extensively in read-heavy environments for now.

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
