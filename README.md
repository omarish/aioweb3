# aioweb3

## Testing

```sh
$ pytest -s
```

## Development

```sh
export PYTHONASYNCIODEBUG=1
export PYTHONBREAKPOINT=ipdb.set_trace
```

## Logging Setup

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
```