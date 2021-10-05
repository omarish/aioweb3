import asyncio
from asyncio import Queue

from aioweb3 import AsyncWeb3, async_web3


async def producer(queue: Queue, jobs: int = 1000):
    print("producing")
    for index in range(jobs):
        await queue.put(index)


async def consumer(queue: Queue, index: int):
    print(f"Consumer {index} booting")
    while 1:
        await queue.get()
        print("getting version")
        version = await async_web3.eth.get_block("latest")
        print("got version")
        queue.task_done()


async def entrypoint(jobs: int = 1_000, workers: int = 1):
    queue = Queue()
    producers = [asyncio.create_task(producer(queue, jobs))]
    consumers = [asyncio.create_task(consumer(queue, i)) for i in range(workers)]
    await asyncio.gather(*producers)
    await queue.join()


def test_workers():
    """Simple test cast to run a bunch of workers in parallel.
    """
    asyncio.run(entrypoint())
