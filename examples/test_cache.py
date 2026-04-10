import asyncio
import time
from cerebro.observer import observe_brain
from loguru import logger

# A mock agent that simulates a slow LLM call


@observe_brain
async def slow_ai_agent(prompt: str, context: str = ""):
    # This represents your LLM call (e.g., Ollama/OpenAI)
    # The decorator handles the caching logic
    from ollama import AsyncClient
    client = AsyncClient()

    # We combine the prompt and the context injected by Cerebro
    full_prompt = f"{context}\n\nUser: {prompt}"

    response = await client.generate(model='llama3', prompt=full_prompt)
    return response['response']


async def main():
    test_prompt = "Explain the concept of 'Recursion' in exactly two sentences."

    # --- ROUND 1: THE COLD CALL ---
    logger.info("--- ROUND 1: INITIAL REQUEST (Cold Call) ---")
    start_time = time.perf_counter()

    response1 = await slow_ai_agent(prompt=test_prompt)

    end_time = time.perf_counter()
    logger.success(f"Round 1 finished in {end_time - start_time:.2f} seconds.")
    print(f"AI Response: {response1}\n")

    # --- ROUND 2: THE SEMANTIC CACHE HIT ---
    logger.info("--- ROUND 2: REPEAT REQUEST (Expecting Cache Hit) ---")
    start_time = time.perf_counter()

    response2 = await slow_ai_agent(prompt=test_prompt)

    end_time = time.perf_counter()
    logger.success(f"Round 2 finished in {end_time - start_time:.4f} seconds.")
    print(f"AI Response (Cached): {response2}")

if __name__ == "__main__":
    asyncio.run(main())
