import asyncio
import csv
import json
from pathlib import Path
from asyncio import Queue
from aioweb3 import AsyncContract, AsyncWeb3

BASE = Path(__file__).parent


def each_address():
    reader = csv.reader(open(BASE / "fixtures" / "addresses.csv"))
    for row in reader:
        yield row[0]


def contract_fixture():
    with open(BASE / "fixtures" / "IERC721Enumerable.json") as f:
        return json.load(f)


IERC721_ENUMERABLE = contract_fixture()


async def producer(queue: Queue):
    for addr in each_address():
        await queue.put(addr)


async def handle(w3, addr):
    contract = w3.eth.contract(address=addr, abi=IERC721_ENUMERABLE['abi'])
    return await contract.functions.totalSupply().call()


async def consumer(queue: Queue, index: int):
    def log(*args, **kwargs):
        print(f"Worker {index}: ", *args, **kwargs)

    log("boot")
    w3 = AsyncWeb3()
    while 1:
        addr = await queue.get()
        result = await handle(w3, addr)
        log(result)
        queue.task_done()


async def entrypoint(jobs: int = 5_000, workers: int = 50):
    queue = Queue()
    producers = [asyncio.create_task(producer(queue))]
    consumers = [asyncio.create_task(consumer(queue, i)) for i in range(workers)]
    await asyncio.gather(*producers)
    await queue.join()


if __name__ == '__main__':
    asyncio.run(entrypoint())