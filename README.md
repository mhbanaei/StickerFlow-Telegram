# 🎨 Telegram Sticker Master Bot (v4.1)

A powerful, all-in-one Telegram bot designed to create and manage sticker sets effortlessly. This bot supports static images, GIFs, and even video files (MP4/MOV/AVI), automatically converting them into the correct Telegram sticker format.

## ✨ Features

* **Multi-Format Support**: Works with JPG, PNG, WebP, BMP, GIF, MP4, MOV, and AVI.
* **Smart Conversion**: Automatically detects if a file should be a static or animated sticker.
* **Video-to-Sticker**: Converts short video clips into animated `.webm` stickers using FFmpeg.
* **Auto-Resizing**: Intelligent scaling and padding to ensure stickers fit the required $512 \times 512$ px dimensions.
* **Size Optimization**: Automatically compresses files to stay under the 256KB Telegram limit.
* **Pack Management**: Create, edit, view, and delete your sticker packs directly from the bot.
* **Custom Emojis**: Assign any emoji to your stickers.

## 🚀 Prerequisites

To run this bot, you need:
1.  **Python 3.8+**
2.  **FFmpeg**: Essential for processing video and animated stickers.
    * *Ubuntu*: `sudo apt install ffmpeg`
    * *MacOS*: `brew install ffmpeg`
    * *Windows*: Download from [ffmpeg.org](https://ffmpeg.org/download.html)

## 🛠️ Installation

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/your-username/Telegram-Sticker-Master.git](https://github.com/your-username/Telegram-Sticker-Master.git)
   cd Telegram-Sticker-Master```
   
2. **Install dependencies:**
	```
		pip install python-telegram-bot Pillow
	```
3. **Configuration: Open Sticker.py and replace the TOKEN variable with your bot token from @BotFather.**
	```
	TOKEN = "YOUR_BOT_TOKEN_HERE"
	```
🛡️ License
Distributed under the MIT License. See LICENSE for more information.

Developed with ❤️ for the Telegram Community.