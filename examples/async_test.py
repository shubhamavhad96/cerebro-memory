import asyncio
from cerebro.observer import observe_brain


@observe_brain
async def async_agent(prompt: str, context: str = ""):
    from ollama import AsyncClient
    # This call is now non-blocking
    res = await AsyncClient().generate(model='llama3', prompt=prompt, system=context)
    return res['response']


async def main():
    # Running two agents simultaneously!
    print("Launching concurrent agents...")
    task1 = async_agent("Tell me a joke about coding.")
    task2 = async_agent("Write a python function to sort a list.")

    # Wait for both to finish
    results = await asyncio.gather(task1, task2)

    for i, res in enumerate(results):
        print(f"\nResult {i+1}: {res[:100]}...")

if __name__ == "__main__":
    asyncio.run(main())
