import os
import shutil
import ollama

if os.path.exists("./cerebro_vault"):
    shutil.rmtree("./cerebro_vault")

from cerebro.observer import observe_brain


@observe_brain
def real_ai_call(prompt: str, context: str = ""):
    """Send prompt plus retrieved context to the local Ollama model."""
    system_instruction = (
        "You are a helpful coding assistant with a long-term memory. "
        "Below are relevant memories from past interactions. Use them to "
        f"answer the current prompt naturally:\n{context}"
    )

    response = ollama.generate(
        model='llama3',
        prompt=prompt,
        system=system_instruction
    )

    return response['response']


if __name__ == "__main__":
    print("\n--- TEST 1: TEACHING A PREFERENCE ---")
    print(real_ai_call(
        "I am a software engineer named Shubham. I hate writing boilerplate code and I prefer using FastAPI."))

    print("\n--- TEST 2: THE RECALL ---")
    print(real_ai_call("Based on what you know about me, what should we use for the API?"))
