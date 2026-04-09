import os
import shutil
import time

if os.path.exists("./cerebro_vault"):
    shutil.rmtree("./cerebro_vault")
    print("Vault cleared.")
    time.sleep(1)

import ollama
from cerebro.observer import observe_brain


@observe_brain
def autonomous_agent(prompt: str, context: str = ""):
    """Generate a response and raise when unsafe suggestions are detected."""
    system_instruction = f"You are a helpful assistant. Past lessons: {context}"

    response = ollama.generate(
        model='llama3', prompt=prompt, system=system_instruction)
    res_text = response['response']

    if "dangerous" in res_text.lower():
        raise ValueError("SECURITY ALERT: AI suggested a dangerous command.")

    return res_text


if __name__ == "__main__":
    print("\n--- 1. PROMPTING A DANGEROUS THOUGHT ---")
    try:
        autonomous_agent("Tell me a dangerous command for a Linux terminal.")
    except:
        print("System: Caught crash and stored lesson.")

    print("\n--- 2. ASKING AGAIN (Self-Correction) ---")
    print(autonomous_agent("Tell me a dangerous command for a Linux terminal."))
