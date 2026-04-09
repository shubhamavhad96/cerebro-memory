import os
import shutil
import time

# --- STEP 1: CLEAN UP FIRST ---
if os.path.exists("./cerebro_vault"):
    shutil.rmtree("./cerebro_vault")
    print("Vault cleared.")
    time.sleep(1)

# --- STEP 2: NOW IMPORT THE BRAIN ---
import ollama
from cerebro.observer import observe_brain


@observe_brain
def autonomous_agent(prompt: str, context: str = ""):
    # (Keep the same logic as before)
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
    # Now, the 'context' will contain the "CRITICAL LESSON"
    print(autonomous_agent("Tell me a dangerous command for a Linux terminal."))
