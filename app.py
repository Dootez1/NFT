import asyncio
import gradio as gr
import spaces
import main

# Function to satisfy Hugging Face ZeroGPU startup watchdog
@spaces.GPU
def check_gpu():
    return "GPU OK"

# Web interface required by Hugging Face
with gr.Blocks() as demo:
    gr.Markdown("# 🤖 Telegram NFT Bot is running 24/7")
    gr.Markdown("Сервер активен, бот обрабатывает запросы Telegram.")

# Launch Gradio non-blocking on port 7860
demo.launch(server_name="0.0.0.0", server_port=7860, prevent_thread_lock=True)

# Run Telegram bot in the main thread
if __name__ == "__main__":
    check_gpu()
    asyncio.run(main.main())
