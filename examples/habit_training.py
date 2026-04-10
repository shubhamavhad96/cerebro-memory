from cerebro.observer import observe_brain
import time


@observe_brain
def coder(prompt: str, context: str = ""):
    import ollama
    # Note: the library automatically injects 'context' now!
    return ollama.generate(
        model='llama3',
        prompt=prompt,
        system=f"{context}"
    )['response']


if __name__ == "__main__":
    habit_trigger = "Write a function. Use VERY short variable names like x, y, z."

    success_count = 0
    attempt = 1

    while success_count < 3:
        print(
            f"\n--- Attempt {attempt} (Successes so far: {success_count}) ---")
        try:
            response = coder(habit_trigger)
            print(f"AI: {response[:100]}...")
            success_count += 1
        except Exception as e:
            print(f"Critic rejected attempt {attempt}: {e}")
            print("System learned a lesson. Retrying...")

        attempt += 1
        time.sleep(1)

    print("\n--- FINAL TEST: The Threshold Recognition ---")
    # Now we ask for something completely different.
    # Since success_count is 3, the AI should announce the habit.
    final_res = coder("Write a function to verify an email address.")
    print(f"\nFINAL AI RESPONSE:\n{final_res}")
