import os
import shutil
import ollama  # The bridge to Llama 3

# 1. AUTO-CLEAN (Keeps our tests fresh)
if os.path.exists("./cerebro_vault"):
    shutil.rmtree("./cerebro_vault")

from cerebro.observer import observe_brain


@observe_brain
def real_ai_call(prompt: str, context: str = ""):
    """
    This function sends the user prompt PLUS the Cerebro memories 
    to your local Llama 3 model.
    """
    # We craft a system instruction that tells the AI to use its memories
    system_instruction = (
        "You are a helpful coding assistant with a long-term memory. "
        "Below are relevant memories from past interactions. Use them to "
        f"answer the current prompt naturally:\n{context}"
    )

    # Call Ollama (Running locally on your Mac)
    response = ollama.generate(
        model='llama3',
        prompt=prompt,
        system=system_instruction
    )

    return response['response']


if __name__ == "__main__":
    print("\n--- TEST 1: TEACHING A PREFERENCE ---")
    # We'll tell it something specific about your coding style
    print(real_ai_call(
        "I am a software engineer named Shubham. I hate writing boilerplate code and I prefer using FastAPI."))

    print("\n--- TEST 2: THE RECALL ---")
    # Now we ask a vague question. If it works, Llama will remember who you are.
    print(real_ai_call("Based on what you know about me, what should we use for the API?"))
